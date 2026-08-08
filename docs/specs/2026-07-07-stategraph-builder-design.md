# StateGraph 图构建器 + 并发控制 — 设计文档

> 日期：2026-07-07
> 子项目：1/5（统一调度链路）
> 方案：A（完全动态构建，无 StateGraph 层缓存）

## 1. 背景

### 1.1 当前问题

项目存在两套独立的图构建路径：

| | 路径 A（主链路） | 路径 B（调度链路） |
|---|---|---|
| 构建函数 | `build_graph()` subagent_builder.py:57 | `LangGraphTaskExecutor._get_or_build_graph()` task_executor.py:276 |
| Checkpointer | 无 | 有（MysqlSaver/MemorySaver） |
| Middleware | 无 | 有（ContextEditingMiddleware + CleanThinkMiddleware） |
| 图缓存 | 无 | 有（`self._compiled_graphs`） |
| 使用方 | ReActExecutor / DeepAgentExecutor | PlanExecutor / multi_agent_service |

两套路径导致：单 agent 对话无 checkpointer/middleware、流式格式不统一、并发控制不一致。

### 1.2 已验证的技术可行性

3 个"金科玉律"已通过源码分析 + POC 实测验证：

| 金科玉律 | 验证方式 | 结果 |
|----------|----------|------|
| 1. `config["max_concurrency"]` 穿透到 Pregel | POC：10 个 Send API 分支，max_concurrency=3 → 同时只跑 3 个 | ✅ 通过 |
| 2. `add_node(retry_policy=RetryPolicy(...))` 节点级重试 | 源码：`graph/state.py add_node()` 签名包含 retry_policy | ✅ 确认 |
| 3. Checkpointer 为状态唯一事实来源 | 源码：`graph.get_state(thread_id)` + `ainvoke(config={"configurable":{"thread_id":...}})` | ✅ 确认 |

源码证据：
- `pregel/_executor.py:135`：`if max_concurrency := config.get("max_concurrency"):` → 创建 Semaphore
- `pregel/_executor.py:154`：`coro = gated(self.semaphore, coro)` → 每个并行分支经过 semaphore
- `pregel/_executor.py:214-217`：`async def gated(semaphore, coro): async with semaphore: return await coro`
- `langgraph/types.py`：`RetryPolicy(initial_interval=0.5, backoff_factor=2.0, max_interval=128, max_attempts=3, jitter=True, retry_on=default_retry_on)`

## 2. 目标

- 实现 `StateGraphBuilder`，从 `ExecutionPlan` 动态构建 LangGraph StateGraph
- 用 `add_edge([...], target)` fan-in 替代自研 Schedule 拓扑排序
- 用 `config["max_concurrency"]` + 共享 Semaphore 实现图间+图内统一并发控制
- 用 `add_node(retry_policy=RetryPolicy(...))` 实现节点级重试
- 新增 `mode="langgraph"` 分支，新旧并行，可回退

## 3. 非目标

- 不废弃自研 DAG/Parallel/Sequential Executor（子项目 5）
- 不迁移 ReActExecutor/DeepAgentExecutor（子项目 3）
- 不统一流式输出格式（子项目 2）
- 不修改前端代码

## 4. 架构概览

```
┌─────────────────────────────────────────────────────────┐
│              自研调度层（保留现有，最小改动）               │
│  MultiAgentService.dispatch_stream(mode="langgraph")    │
│  ├── Semaphore（图间并发，保留现有）                       │
│  ├── _try_retry（图间 infra 重试，保留现有）              │
│  └── dispatch_record（审计日志，保留现有）                 │
└───────────────────────┬─────────────────────────────────┘
                        │ 新增 mode="langgraph" 分支
                        ▼
┌─────────────────────────────────────────────────────────┐
│         StateGraphBuilder（新模块，核心）                  │
│  build_state_graph(plan, adapter, semaphore)            │
│  ├── 从 ExecutionPlan.tasks 构建 StateGraph              │
│  │   ├── add_node(task.id, node_func, retry_policy)     │
│  │   ├── add_edge(START, entry_tasks)                   │
│  │   ├── add_edge(dependencies, task.id)  ← fan-in      │
│  │   └── add_edge(terminal_tasks, END)                   │
│  ├── node_func 内部用 semaphore 共享图间并发上限           │
│  └── compile(checkpointer) → CompiledStateGraph         │
└───────────────────────┬─────────────────────────────────┘
                        │ graph.astream(state, config)
                        ▼
┌─────────────────────────────────────────────────────────┐
│         LangGraph 执行层（图内，现有）                     │
│  Pregel Engine                                          │
│  ├── config["max_concurrency"] → Semaphore（图内并发）    │
│  ├── RetryPolicy → 节点级重试（LLM 429/工具超时）         │
│  ├── Checkpointer → 状态持久化 + 中断恢复                 │
│  └── Send API → 动态 fan-out（parallel 模式）             │
└─────────────────────────────────────────────────────────┘
```

## 5. 组件设计

### 5.1 StateGraphBuilder

**文件**：`executor/workflow/stategraph_builder.py`（新增）

**接口**：

```python
class StateGraphBuilder:
    def __init__(
        self,
        adapter: LangGraphWorkflowAdapter,
        checkpointer: BaseCheckpointer,
    ):
        self._adapter = adapter
        self._checkpointer = checkpointer

    def build(
        self,
        plan: ExecutionPlan,
        semaphore: asyncio.Semaphore,
        max_concurrency: int = 10,
    ) -> CompiledStateGraph:
        """从 ExecutionPlan 动态构建 StateGraph。

        1. 定义 State schema（results + errors）
        2. 为每个 TaskNode 创建 node 函数（含 semaphore + retry_policy）
        3. 根据 dependencies 创建 add_edge（含 fan-in）
        4. compile(checkpointer) → CompiledStateGraph
        """
```

### 5.2 State Schema

```python
class WorkflowState(TypedDict):
    results: dict   # {task_id: result_str}
    errors: dict    # {task_id: error_str}，on_failure="continue" 时填充
```

### 5.3 Node 函数

```python
async def _make_node_func(task, plan, adapter, semaphore):
    """创建 node 函数，内部共享 semaphore 并调用 adapter。"""
    async def node(state):
        async with semaphore:  # 与自研调度层共享同一个 Semaphore 实例
            try:
                result = await adapter.execute_task(
                    task=task, plan=plan, context=state.get("results", {})
                )
                return {"results": {task.id: result}}
            except Exception as e:
                if task.on_failure == "stop":
                    raise  # 让整个 StateGraph 失败
                else:
                    return {
                        "errors": {task.id: str(e)},
                        "results": {task.id: f"error: {e}"}
                    }
    return node
```

### 5.4 Edge 构建

```python
# 无依赖的 task → START
for task in plan.tasks:
    if not task.dependencies:
        builder.add_edge(START, task.id)

# 有依赖的 task → fan-in
for task in plan.tasks:
    if task.dependencies:
        builder.add_edge(task.dependencies, task.id)

# 终点 task → END
terminal_tasks = [t.id for t in plan.tasks if not _has_dependents(t, plan)]
for tid in terminal_tasks:
    builder.add_edge(tid, END)
```

### 5.5 RetryPolicy 配置

```python
from langgraph.types import RetryPolicy

DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=0.5,     # 首次重试前 0.5s
    backoff_factor=2.0,       # 指数退避：0.5 → 1 → 2 → 4
    max_interval=128.0,       # 上限 128s
    max_attempts=3,           # 最多 3 次（含首次）
    jitter=True,              # 随机抖动，避免重试风暴
    retry_on=RateLimitError,  # 仅重试 LLM 限流错误
)

builder.add_node(task.id, node_func, retry_policy=DEFAULT_RETRY_POLICY)
```

## 6. 数据流

```
MultiAgentService.dispatch_stream(mode="langgraph")
  │
  ├── 1. StateGraphBuilder.build(plan, semaphore, max_concurrency)
  │     ├── add_node(task.id, node_func, retry_policy=RetryPolicy(...))
  │     ├── add_edge(START / dependencies / END)
  │     └── compile(checkpointer) → CompiledStateGraph
  │
  ├── 2. graph.astream(initial_state, config={
  │         "max_concurrency": max_concurrency,
  │         "configurable": {"thread_id": run_id}
  │       })
  │     │
  │     └── Pregel Engine
  │         ├── 内部 Semaphore(max_concurrency)  ← 控制并行分支数
  │         ├── node_func 执行
  │         │   ├── async with semaphore  ← 外部 Semaphore（图间+图内共享）
  │         │   └── adapter.execute_task_stream(task, plan, context)
  │         │       └── LangGraphTaskExecutor（per-agent graph 缓存）
  │         ├── RetryPolicy  ← 节点级重试
  │         └── Checkpointer  ← 状态持久化
  │
  └── 3. async for event in graph.astream(...)
        └── yield 包装为 ExecutionEvent（复用现有格式）
```

### 6.1 并发控制双层设计

**两个独立的 Semaphore**：

| Semaphore | 创建者 | 控制对象 | 实例数 |
|-----------|--------|----------|--------|
| 外部 S | 自研调度层 | graph.ainvoke 入口 + node 函数内部 | 1 个（所有 graph 共享） |
| 内部 M | Pregel 引擎 | 单个 graph 内的并行分支 | per-graph（每个 graph 独立） |

**总并发公式**：`min(N × M, S)`
- N = 同时执行的 graph 数（受外部 Semaphore(S) 限制，N ≤ S）
- M = 每个 graph 的 `max_concurrency`（Pregel 内部 Semaphore）
- S = 外部 Semaphore 的 limit

**工作原理**：
1. 外部 Semaphore(S) 限制同时执行的 graph 数（N ≤ S）
2. 每个 graph 内部 Pregel Semaphore(M) 限制并行分支数
3. node 函数内部 `async with semaphore`（外部 S）进一步限制实际并发
4. 最终实际并发 = min(N × M, S)，因为所有 node 函数共享同一个外部 Semaphore

**推荐配置**（以 LLM 限流阈值 10 为例）：
- S = 10, M = 1：10 个 graph 同时执行，每个 graph 内串行 → 总并发 = min(10×1, 10) = 10
- S = 10, M = 5, N = 2：2 个 graph 同时执行，每个最多 5 并行 → 总并发 = min(2×5, 10) = 10
- S = 10, M = 10, N = 1：1 个 graph 执行，最多 10 并行 → 总并发 = min(1×10, 10) = 10

## 7. 错误处理

| 层级 | 错误类型 | 机制 | 最大重试 |
|------|----------|------|----------|
| 图间（自研） | graph 编译失败 / checkpointer 连接超时 | `_try_retry`（保留现有） | 1 次 |
| 图内（LangGraph） | LLM 429 / 工具超时 / RateLimitError | `RetryPolicy` | 3 次 |
| 全局超时 | 死循环 / 无限挂起 | `asyncio.wait_for`（保留现有） | 不重试 |
| node 失败 | on_failure="stop" → raise | StateGraph 终止 | N/A |
| node 失败 | on_failure="continue" → 返回 error | StateGraph 继续 | N/A |

## 8. 测试策略

| 测试 | 类型 | 验证内容 |
|------|------|----------|
| `test_max_concurrency_poc.py`（已有） | POC | max_concurrency 控制 Send API 并行 |
| `test_stategraph_builder.py`（新增） | 单元 | build() 从 ExecutionPlan 构建 StateGraph，edge 正确 |
| `test_langgraph_dispatch.py`（新增） | 集成 | dispatch_stream(mode="langgraph") 端到端 |
| `test_multi_agent_dispatch.py`（现有） | 回归 | mode="parallel" 旧路径仍通过 |
| `test_dag_dispatch.py`（现有） | 回归 | mode="dag" 旧路径仍通过 |

## 9. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `executor/workflow/stategraph_builder.py` | 新增 | StateGraphBuilder 类 |
| `services/multi_agent_service.py` | 修改 | dispatch_stream 新增 mode="langgraph" 分支 |
| `executor/workflow/__init__.py` | 修改 | 导出 StateGraphBuilder |
| `test/test_stategraph_builder.py` | 新增 | 单元测试 |
| `test/test_langgraph_dispatch.py` | 新增 | 集成测试 |

### 不修改的文件

- `executor/workflow/executors.py`（自研 DAG/Parallel/Sequential 保留）
- `executor/react_executor.py`（子项目 3 迁移）
- `core/builder/subagent_builder.py`（子项目 3 迁移）
- `frontend/`（子项目 2 适配）

## 10. 后续子项目

| 顺序 | 子项目 | 依赖 |
|------|--------|------|
| 2 | 统一流式输出 | 子项目 1 |
| 3 | 迁移单 agent 到路径 B | 子项目 1+2 |
| 4 | 统一状态持久化 | 子项目 1 |
| 5 | 废弃旧代码 | 子项目 1-4 |
