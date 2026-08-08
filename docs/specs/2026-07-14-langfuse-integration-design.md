# langfuse 集成设计 — langgraph 编排结果可视化

> 日期：2026-07-14
> 方案：B（完整集成 — Path A+B 全覆盖 + 嵌套 trace + 自托管）
> 前置调查：explore agent 确认项目两条执行路径的 observability 现状 + context7 langfuse 官方集成方式

---

## 1. 背景

### 1.1 项目现状

项目是基于 LangChain 1.x + LangGraph 1.x 的两层图嵌套多 agent 编排框架：

- **外层图**（`StateGraphBuilder`）：把 LLM 生成的 `ExecutionPlan` 动态编译为 DAG，利用 Pregel 引擎的 fan-in edge 和 `operator.or_` reducer 实现依赖调度与并发 state 合并。
- **内层图**（`LangGraphTaskExecutor` + `AgentFactory`）：每个 task node 内部构建独立 ReAct/DeepAgent 图，负责单个 agent 的 LLM↔Tool 交互循环。

### 1.2 两条执行路径的 observability 缺口（explore 确认）

| 路径 | 入口 | graph.astream 的 config | callbacks 注入 | observability 现状 |
|---|---|---|---|---|
| **Path A** 直接 Agent 流式 | `react_executor` → `agent_stream_handler.generate_simple_stream` | `{callbacks:[AgentCallbackHandler], recursion_limit, configurable}` | ✅ 有 | 自研 callback + token 统计 |
| **Path B** 工作流/多 agent 调度（生产主路径） | `plan_executor._execute_with_workflow` / `multi_agent_service.dispatch_stream` → `task_executor` | `{configurable:{thread_id}, max_concurrency/recursion_limit}` | ❌ **无** | 仅手写 `PerformanceLogger`（`model="unknown", duration=0` 占位，缺真实 LLM 元数据） |

Path B（生产主路径）完全无 langchain callbacks 注入，是 langfuse 集成的核心缺口。

### 1.3 langfuse 价值

- **自动 trace**：CallbackHandler 经 `config["callbacks"]` 注入，自动捕获 LLM/tool/token，无需手写埋点
- **Agent Graphs 自动可视化**：langgraph 集成时自动生成 graph 视图（编排拓扑）
- **嵌套 trace**：`predefined_trace_id` + `propagate_attributes` 把外层 DAG + 内层 agent 关联为一个 trace
- **补齐占位洞**：Path B 的 `PerformanceLogger.log_llm_call(model="unknown")` → langfuse 经 `on_llm_end` 拿真实 model/tokens/duration

---

## 2. 目标

- langfuse 接入 Path B（工作流主路径）+ Path A（单 agent 对话），实现编排结果可视化
- 外层 DAG task 级 + 内层 LLM/tool 级通过 `predefined_trace_id` 关联为嵌套 trace，langfuse Agent Graphs 自动生成编排拓扑
- 生产态自托管部署，数据完全本地（契合项目本地化环境 + 金融研究数据敏感）；验证期（阶段 1-3）可临时用云端 cloud.langfuse.com 快速验证 SDK 兼容性与可视化效果，阶段 4 切自托管
- `enabled` 开关，关闭时零影响现有链路（降级安全）

## 3. 非目标

- 不替换自研 `AgentCallbackHandler`（它管流式输出，langfuse 管 trace，职责不同，并存）
- 不替换 `PerformanceLogger`（保留作本地快速日志，后续可选淘汰）
- 不引入 langfuse 的 evals/prompt management/playground（本期只做 tracing + 可视化）
- 不改图构建逻辑（runtime `config["callbacks"]` 注入，不动 `StateGraphBuilder.build` / `AgentFactory.create`）

---

## 4. 架构概览

```
config/agent_config.json
  └─ observability.langfuse.{enabled, public_key, secret_key, host, self_hosted}
        │ get_config 通用点分查询（无需改 get_config）
        ▼
utils/observability/langfuse_handler.py  (新建)
  └─ LangfuseHandlerFactory.create() → CallbackHandler | None
        │ enabled=false 或 import 失败 → None（降级，不阻断）
        ▼
┌──────────────────────────────────────────────────────────────┐
│  入口层：propagate_attributes(trace_name, session_id, tags)   │
│  plan_executor.execute_stream / multi_agent_service.dispatch │
└──────────────────────────────────────────────────────────────┘
        │
        ▼  外层 graph.astream(config={callbacks:[handler], ...})
┌──────────────────────────────────────────────────────────────┐
│  外层 DAG trace（task 级：哪些 task/依赖/并行/结果传递）      │
└──────────────────────────────────────────────────────────────┘
        │ 每个 task node 内
        ▼  task_executor.execute_task_stream(config={callbacks:[handler]})
┌──────────────────────────────────────────────────────────────┐
│  内层 agent trace（LLM 调用/tool_call/token/耗时）            │
│  predefined_trace_id 关联外层+内层 → 嵌套 trace               │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
langfuse dashboard → Agent Graphs 自动可视化编排拓扑
```

---

## 5. 组件设计

### 5.1 LangfuseHandlerFactory（新建）

**文件**：`utils/observability/langfuse_handler.py`

**职责**：读 config，enabled 时创建 `langfuse.langchain.CallbackHandler`，否则返回 None。单例缓存避免每次 astream 重建。

**接口**：
```python
class LangfuseHandlerFactory:
    _handler: Optional[CallbackHandler] = None
    _initialized: bool = False

    @classmethod
    def create(cls) -> Optional[CallbackHandler]:
        """读 config 创建/返回缓存的 langfuse CallbackHandler。
        enabled=false 或 langfuse 未装或 key 缺失 → 返回 None。
        """
        if cls._initialized:
            return cls._handler
        cls._initialized = True
        if not get_config("observability.langfuse.enabled", False):
            return None
        try:
            from langfuse.langchain import CallbackHandler
        except ImportError:
            logger.warning("[Langfuse] langfuse 未安装，trace 降级禁用")
            return None
        public_key = get_config("observability.langfuse.public_key", "")
        secret_key = get_config("observability.langfuse.secret_key", "")
        host = get_config("observability.langfuse.host", "http://localhost:3000")
        if not public_key or not secret_key:
            logger.warning("[Langfuse] public_key/secret_key 缺失，trace 降级禁用")
            return None
        cls._handler = CallbackHandler(public_key=public_key, secret_key=secret_key, host=host)
        logger.info(f"[Langfuse] handler 已创建，host={host}")
        return cls._handler
```

### 5.2 trace_context（新建）

**文件**：`utils/observability/trace_context.py`

**职责**：封装 `propagate_attributes` 上下文管理器 + `predefined_trace_id` 生成（用项目 session_id/dispatch_id 派生）。

**接口**：
```python
from contextlib import contextmanager

@contextmanager
def trace_context(trace_name: str, session_id: str, tags: list = None, metadata: dict = None):
    """包裹执行入口，设 trace 元信息。
    langfuse 未装时降级为 no-op（不影响主流程）。
    """
    handler = LangfuseHandlerFactory.create()
    if handler is None:
        yield  # 降级：no-op
        return
    try:
        from langfuse import propagate_attributes
        with propagate_attributes(
            trace_name=trace_name,
            session_id=session_id,
            tags=tags or [],
            metadata=metadata or {},
        ):
            yield
    except ImportError:
        yield  # langfuse 未装降级
```

### 5.3 配置节（新增）

**文件**：`config/agent_config.json`

```json
{
  "observability": {
    "langfuse": {
      "enabled": false,
      "public_key": "",
      "secret_key": "",
      "host": "http://localhost:3000",
      "self_hosted": true
    }
  }
}
```

`get_config("observability.langfuse.enabled")` 通用点分查询自动支持，无需改 `get_config`。

### 5.4 注入点改造

| 注入点 | 文件:行 | 改造 |
|---|---|---|
| ① 内层（Path B 单点，覆盖所有工作流 task） | `task_executor.py:123-126`（execute_task）/ `192-195`（execute_task_stream） | config dict 加 `"callbacks": [h]`（h = `LangfuseHandlerFactory.create()`，None 时跳过） |
| ② 外层 DAG | `plan_executor.py:371-374`（_execute_with_workflow）/ `multi_agent_service.py:219-222`（dispatch_stream） | config 加 callbacks + 入口 `trace_context(...)` 包裹 |
| ③ Path A | `agent_stream_handler.py:904-908`（generate_simple_stream） | 现有 `[AgentCallbackHandler]` 数组追加 `langfuse_handler`（None 时跳过） |

**注入辅助函数**（放 `langfuse_handler.py`）：
```python
def attach_callbacks(config: dict) -> dict:
    """向 config 注入 langfuse callbacks（handler 非 None 时）。返回新 config（不改原 dict）。"""
    handler = LangfuseHandlerFactory.create()
    if handler is None:
        return config
    new_config = dict(config)
    existing = new_config.get("callbacks", [])
    new_config["callbacks"] = [*existing, handler]
    return new_config
```

注入点调用：`config = attach_callbacks(config)`。

### 5.5 部署（新建）

**文件**：`docker-compose.langfuse.yml`

自托管 langfuse 栈（langfuse-web + worker + postgres + clickhouse + redis + minio）。用项目独立的 compose 文件，不污染现有基础设施。端口 3000。

---

## 6. 数据流

```
用户请求 → plan_executor.execute_stream(messages, session_id="abc")
  → trace_context(trace_name="plan_executor", session_id="abc", tags=[plan.mode.value])
    → StateGraphBuilder.build → graph.astream(config=attach_callbacks({configurable, max_concurrency}), stream_mode=["updates","custom"])
      → 外层 DAG super-step：每个 task node 的执行被 trace（task_started/completed/failed）
        → adapter.execute_task_stream → task_executor.execute_task_stream
          → graph.astream(config=attach_callbacks({configurable, recursion_limit}))
            → LLM 调用（model/input/output tokens/duration）
            → tool_call（tool_name/args/result）
            → 内层 trace 通过同一 trace_id（propagate_attributes 传播）关联到外层 task
  → langfuse SDK 异步 flush → dashboard 显示嵌套 trace + Agent Graphs 编排拓扑
```

multi_agent_service.dispatch_stream 同理（trace_name="multi_agent_dispatch", session_id=dispatch_id）。

---

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| langfuse 未装 / import 失败 | factory catch ImportError，返回 None，`attach_callbacks` 跳过，主流程不受影响 |
| langfuse 后端不可达（网络/key 错误） | SDK 异步 flush + 内部重试，异常吞掉，不影响 graph.astream（tracing 不影响业务） |
| enabled=false | factory 不创建 handler，`attach_callbacks` no-op，零开销 |
| API key 配置缺失 | factory 检测 key 为空返回 None + loguru warning |
| 与现有 AgentCallbackHandler 冲突 | 不冲突——langchain `config["callbacks"]` 支持多 handler 并存，各自独立触发 |
| docker 栈启动失败 | 回退 `enabled=false`，主流程继续（无 trace 但业务正常） |

---

## 8. 测试策略

| 测试 | 文件 | 类型 | 验证 |
|---|---|---|---|
| factory 单元 | `test/test_langfuse_handler_factory.py` | 单元 | enabled=true 返回 handler；enabled=false 返回 None；langfuse 未装降级不抛异常；key 为空返回 None；单例（多次 create 返回同实例） |
| 注入点单元 | `test/test_langfuse_callbacks_injection.py` | 单元 | mock factory，验证 task_executor config 含 callbacks（enabled）vs 不含（disabled）；attach_callbacks 不改原 config |
| 降级测试 | 同上 | 单元 | langfuse 挂了/factory 返回 None，graph.astream 仍执行不阻断 |
| trace_context | `test/test_trace_context.py` | 单元 | langfuse 未装时 no-op；正常时 propagate_attributes 包裹；session_id/tags 透传 |
| 回归 | 现有 `test_task_executor_build_input_bug.py` 等 | 回归 | 注入 callbacks 后现有测试仍通过（callbacks 不影响业务逻辑） |

**测试命令**：`"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langfuse_*.py -v`

---

## 9. 实施分阶段

| 阶段 | 内容 | 验证 |
|---|---|---|
| 1 | langfuse_handler factory + config 节 + `attach_callbacks` + task_executor 单点注入（注入点①） | langfuse dashboard 出现内层 task trace（enabled=true 云端或自托管均可） |
| 2 | plan_executor/multi_agent_service 外层注入（注入点②）+ trace_context 包裹 | 嵌套 trace 含外层 DAG + 内层 LLM/tool，Agent Graphs 可视化编排拓扑 |
| 3 | agent_stream_handler 数组追加（注入点③，Path A） | 单 agent 对话也 trace |
| 4 | docker-compose.langfuse.yml 自托管部署 + env/config 切换 | 数据本地化，生产可用；enabled 开关切换云端/自托管/禁用 |

每阶段独立验证，前一阶段通过才进下一阶段（风险递增控制）。

---

## 10. 文件变更清单

| 文件 | 变更类型 | 阶段 |
|---|---|---|
| `utils/observability/__init__.py` | 新建 | 1 |
| `utils/observability/langfuse_handler.py` | 新建（factory + attach_callbacks） | 1 |
| `utils/observability/trace_context.py` | 新建 | 2 |
| `config/agent_config.json` | 改（加 observability.langfuse 节） | 1 |
| `executor/langgraph/task_executor.py` | 改（L123/192 config 注入） | 1 |
| `executor/plan_executor.py` | 改（L371 注入 + 入口 trace_context） | 2 |
| `services/multi_agent_service.py` | 改（L219 注入 + 入口 trace_context） | 2 |
| `executor/agent_stream_handler.py` | 改（L904 数组追加） | 3 |
| `requirements.txt` | 改（加 langfuse） | 1 |
| `docker-compose.langfuse.yml` | 新建 | 4 |
| `test/test_langfuse_handler_factory.py` | 新建 | 1 |
| `test/test_langfuse_callbacks_injection.py` | 新建 | 1 |
| `test/test_trace_context.py` | 新建 | 2 |

---

## 11. 风险与回退

| 风险 | 等级 | 缓解 |
|---|---|---|
| langfuse SDK 与 langchain 1.x 兼容性 | 中 | 阶段 1 单点注入先验证（context7 确认 v3 兼容 langchain-core 1.x，但需实测） |
| callback 注入影响 graph.astream 性能 | 低 | langfuse SDK 异步 flush，非阻塞；阶段 1 验证耗时 |
| 与自研 AgentCallbackHandler 冲突 | 低 | langchain 多 handler 并存设计，各自独立触发 |
| 自托管 docker 栈资源占用 | 中 | 独立 compose 文件，可单独启停；enabled=false 可完全禁用 |
| trace 数据量大（LLM 输入输出） | 低 | langfuse 支持采样配置（后续可加 sampling_rate） |

**回退**：`observability.langfuse.enabled=false` 即完全禁用（factory 返回 None，注入点 no-op），主流程零影响。删除 docker-compose.langfuse.yml 不影响业务。

---

## 12. 后续（非本期）

- langfuse evals（自动评估 LLM 输出质量）
- langfuse prompt management（版本化 prompt）
- 逐步淘汰 PerformanceLogger（langfuse 已覆盖其功能 + 更全）
- trace 采样配置（高流量场景）
