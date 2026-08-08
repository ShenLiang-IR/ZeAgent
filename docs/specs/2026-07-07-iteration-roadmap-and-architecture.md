# 调度链路迭代路线图与架构设计

> 日期：2026-07-07
> 状态：范围 A 已完成，范围 B 架构设计（可执行）
> 前置文档：
> - `docs/specs/2026-07-07-stategraph-builder-design.md`（子项目 1：StateGraphBuilder）
> - `docs/specs/2026-07-07-unified-dispatch-stategraph-design.md`（范围 A：dispatch 统一）

## 1. 迭代历史与当前状态

### 1.1 迭代历程

| 阶段 | 内容 | 状态 | 文档 |
|------|------|------|------|
| 子项目 1 | StateGraphBuilder + mode="langgraph" 分支 | ✅ 完成 | stategraph-builder-design.md |
| 范围 A | dispatch_stream 所有 mode 统一走 StateGraphBuilder + 补 GAP-2/5/10 + 删旧 executor 分支 | ✅ 完成 | unified-dispatch-stategraph-design.md |
| 修复轮 | review 发现的 8 个问题全部修复（deep_thinking/DispatchRecord/retry/max_concurrency/str(e)/前端 error/dag-sequential） | ✅ 完成 | — |
| **范围 B** | **PlanExecutor 迁移 + GAP-1 流式增量 + 问题 2 流式格式统一** | **🏗 架构设计（本文档）** | — |

### 1.2 当前架构状态

```
┌─────────────────────────────────────────────────────────────┐
│  范围 A 已完成（dispatch 路径统一）                          │
│  MultiAgentService.dispatch_stream(mode=parallel/dag/seq)   │
│  └── 全部走 StateGraphBuilder + graph.astream（super-step 级）│
│      ├── 双层 Semaphore（外部 S + Pregel M max_concurrency）  │
│      ├── RetryPolicy（读 config，按 on_failure 区分）         │
│      ├── Annotated[dict, operator.or_] reducer               │
│      └── MemorySaver checkpointer                            │
├─────────────────────────────────────────────────────────────┤
│  范围 B 未完成（chat stream 路径仍用旧 executor）            │
│  PlanExecutor.execute_stream                                 │
│  └── 旧 executor（WorkflowSequential/Parallel/DAGExecutor）  │
│      ├── execute_task_stream（token 级流式）                 │
│      ├── 自研 retry_queue / _try_retry                       │
│      └── 无 Semaphore（parallel 全并发）                      │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 范围 A 改进对比（自研 vs StateGraphBuilder）

| 维度 | 旧自研 | 新 StateGraphBuilder | 改进 |
|------|--------|---------------------|------|
| 执行器 | 3 个（Sequential/Parallel/DAG 各自实现） | 1 个（dependencies 驱动自动建图） | 3→1 |
| 图构建 | 自研 Schedule（adj_list+in_degree+BFS） | LangGraph add_edge fan-in | 删除自研拓扑 |
| 并发控制 | parallel 无信号量全并发 | 双层 Semaphore | 解决限流风险 |
| 重试 | 3 套不一致 | 统一 RetryPolicy（读 config） | 统一+配置驱动 |
| 状态管理 | mutable context dict | immutable state + reducer | 解决并发更新冲突 |
| 持久化 | 无 checkpointer | MemorySaver | 新增中断恢复 |
| 安全 | str(e) 直传 | 脱敏（type(e).__name__） | 不泄露内部细节 |
| 代码量 | executors.py 504行 + base/engine/dispatcher/scheduler | stategraph_builder.py 153行 | 大幅减少 |

### 1.4 当前流式 API 现状

| 路径 | API | 粒度 | 说明 |
|------|-----|------|------|
| dispatch_stream（范围 A） | `graph.astream`（stream_mode="updates"） | super-step 级 | task 完成时 yield 最终结果，非 token 级 |
| PlanExecutor（范围 B） | 旧 executor `execute_task_stream` | token/step 级 | LLM 逐字输出 + tool_call 实时 |
| **技术前提验证** | `get_stream_writer` ✅ + `astream_events` ✅ | — | LangGraph 版本支持 custom stream + events 捕获 |

## 2. 范围 B 架构设计（可执行）

### 2.1 目标

- **PlanExecutor 迁移**：chat stream 路径从旧 executor 迁移到 StateGraphBuilder（解决 GAP-4）
- **GAP-1 流式增量**：node 函数用 `execute_task_stream` + `get_stream_writer()` 转发 token 级增量（解决 GAP-1/8）
- **问题 2 流式格式统一**：chat stream 和 dispatch 统一 SSE 事件 schema
- **废弃旧 executor**：删除 executors.py（子项目 5，依赖范围 B + 问题 2）

### 2.2 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│  统一调度层（范围 B 后）                                      │
│  ├── MultiAgentService.dispatch_stream（多 agent 调度）       │
│  │   └── StateGraphBuilder + astream(stream_mode=["updates"])│
│  │       （task 级事件，不需要 token 级）                     │
│  │                                                            │
│  └── PlanExecutor.execute_stream（单 agent chat stream）      │
│      └── StateGraphBuilder + astream(stream_mode=["updates", │
│          "custom"])                                           │
│          ├── updates: super-step 级（task 完成）              │
│          └── custom: token 级（node 内 LLM 流式，via         │
│              get_stream_writer）                              │
│                                                               │
│  StateGraphBuilder（统一图构建）                               │
│  ├── node 函数：execute_task_stream + get_stream_writer       │
│  │   ├── adapter 事件 → stream writer 转发（token 级）        │
│  │   └── 返回 {"results": {task.id: final_result}}（最终）    │
│  ├── RetryPolicy（读 config，按 on_failure 区分）             │
│  ├── Annotated[dict, operator.or_] reducer                    │
│  └── Checkpointer（MysqlSaver 跨重启，替代 MemorySaver）      │
│                                                               │
│  统一 SSE 事件 schema（问题 2）                                │
│  ├── {type, task_id?, content?, reasoning?, done?}           │
│  ├── chat stream: task_id="chat"（单通道）                    │
│  └── dispatch: task_id=真实（多通道）                         │
└──────────────────────────────────────────────────────────────┘
（删除：executors.py + base.py + engine.py + dispatcher.py + scheduler.py）
```

### 2.3 核心组件设计

#### 2.3.1 StateGraphBuilder 扩展：流式 node 函数（GAP-1）

```python
# executor/workflow/stategraph_builder.py — _make_node_func 扩展

from langgraph.config import get_stream_writer

def _make_node_func(self, task, plan, semaphore, deep_thinking=False, stream_mode="final"):
    """创建 node 函数。

    Args:
        stream_mode: "final"（返回最终结果，dispatch 用）/"stream"（转发 token 增量，chat stream 用）
    """
    adapter = self._adapter

    async def node(state: WorkflowState) -> dict:
        async with semaphore:
            if stream_mode == "stream":
                # GAP-1 解决方案：用 execute_task_stream + get_stream_writer 转发增量
                writer = get_stream_writer()
                final_result = ""
                async for event in adapter.execute_task_stream(
                    task=task, plan=plan, context=state.get("results", {}),
                    deep_thinking=deep_thinking,
                ):
                    # 转发 adapter 事件到 custom stream channel
                    writer({"task_id": task.id, "event": event})
                    # 收集最终结果
                    if hasattr(event, 'data') and event.get('is_final'):
                        final_result = event.get('output', '')
                return {"results": {task.id: final_result}}
            else:
                # 现有逻辑：非流式 execute_task（dispatch 用）
                result = await adapter.execute_task(
                    task=task, plan=plan, context=state.get("results", {}),
                    deep_thinking=deep_thinking,
                )
                return {"results": {task.id: result}}

    return node
```

#### 2.3.2 PlanExecutor 迁移（GAP-4）

```python
# executor/plan_executor.py — _execute_with_workflow 改为 StateGraphBuilder

async def _execute_with_workflow(self, plan, context, event_sender, deep_thinking, context_health):
    # 旧：executor = self._workflow_executors[plan.mode.value]; executor.execute_stream(plan, context)
    # 新：StateGraphBuilder + astream(stream_mode=["updates", "custom"])

    from executor.workflow.stategraph_builder import StateGraphBuilder
    from langgraph.config import get_stream_writer

    semaphore = asyncio.Semaphore(get_config("agent.execution.parallel_tasks.max_concurrency", 5))
    checkpointer = MysqlSaver(...)  # 替代 MemorySaver，跨重启

    builder = StateGraphBuilder(adapter=self._adapter, checkpointer=checkpointer)
    graph = builder.build(plan=plan, semaphore=semaphore, deep_thinking=deep_thinking,
                          stream_mode="stream")  # chat stream 用流式 node

    config = {"configurable": {"thread_id": self.session_id}, "max_concurrency": ...}

    async for event in graph.astream(
        {"results": {}, "errors": {}},
        config=config,
        stream_mode=["updates", "custom"],  # 同时消费 super-step + token 增量
    ):
        # updates: {node_name: {results: {...}}} → task_completed
        # custom: {task_id, event} → token 级转发（content_chunk/tool_call/thinking）
        for mode, data in event:
            if mode == "updates":
                # 处理 task 完成（现有逻辑）
                ...
            elif mode == "custom":
                # 转发 token 级增量到 SSE
                yield self._translate_event_to_sse(data)
```

#### 2.3.3 统一 SSE 事件 schema（问题 2）

```python
# 统一事件格式（chat stream + dispatch 共用）
# {type, task_id, content?, reasoning_content?, agent?, done?}

# chat stream: task_id 固定 "chat"，单通道
# dispatch: task_id = 真实 task_id，多通道

def _translate_event_to_sse(stream_data):
    """将 custom stream 的 adapter 事件转为统一 SSE 格式。"""
    task_id = stream_data.get("task_id", "chat")
    event = stream_data.get("event")

    # adapter 事件类型映射
    if event.type == "message":  # LLM token 增量
        return {"type": "content_chunk", "task_id": task_id, "content": event.data}
    elif event.type == "thinking":
        return {"type": "content_chunk", "task_id": task_id, "reasoning_content": event.data}
    elif event.type == "tool_call":
        return {"type": "tool_start", "task_id": task_id, "data": event.data}
    elif event.type == "tool_result":
        return {"type": "tool_end", "task_id": task_id, "data": event.data}
    ...
```

### 2.4 实施路径与优先级

| 顺序 | 子任务 | 依赖 | 复杂度 | 风险 |
|------|--------|------|--------|------|
| B-1 | StateGraphBuilder 扩展 stream_mode 参数 + node 用 execute_task_stream + get_stream_writer | 范围 A ✅ | 中 | 低（dispatch 不受影响，stream_mode="final" 默认） |
| B-2 | PlanExecutor 迁移到 StateGraphBuilder（stream_mode="stream"） | B-1 | 高 | 中（chat stream 体验可能变化，需验证 token 级流式） |
| B-3 | 统一 SSE 事件 schema（chat stream + dispatch） | B-2 | 中 | 中（前端需适配） |
| B-4 | 删除旧 executor（executors.py + base/engine/dispatcher/scheduler） | B-2 + B-3 | 低 | 低（删除前确认无引用） |
| B-5 | Checkpointer 升级（MemorySaver → MysqlSaver，跨重启） | B-2 | 中 | 中（DB 依赖） |

### 2.5 风险与回退

| 风险 | 等级 | 缓解 |
|------|------|------|
| B-2 chat stream 体验退化（astream custom 丢失某些 adapter 事件） | 中 | 先写端到端测试对比旧/新输出；保留旧 executor 代码直到 B-2 验证通过 |
| B-3 前端适配（ChatView + AgentList onEvent 改动） | 中 | 统一 schema 时保留兼容期（同时发新旧字段） |
| get_stream_writer 在 subgraph 场景行为未知 | 低 | B-1 先写 POC 验证 get_stream_writer + stream_mode="custom" |
| MysqlSaver 配置复杂 | 低 | B-5 可延后，MemorySaver 先用 |

### 2.6 验证策略

| 验证点 | 方法 |
|--------|------|
| B-1 stream_mode 不影响 dispatch | 范围 A 的 28 测试全通过（stream_mode="final" 默认） |
| B-2 chat stream token 级流式 | 端到端：单 agent 对话，前端看到逐字输出 + tool_call |
| B-2 chat stream 不退化 | 对比旧/新：相同输入，输出事件类型/内容一致 |
| B-3 统一 schema | 前端 ChatView + AgentList 都能消费统一格式 |
| B-4 无引用 | grep WorkflowSequentialExecutor 等，确认 0 引用 |

## 3. 范围 B 可执行架构总结

**核心架构决策**：
1. **node 函数双模式**：`stream_mode="final"`（dispatch，非流式）/ `"stream"`（chat stream，get_stream_writer 转发 token 级）
2. **消费方双 stream_mode**：dispatch 用 `astream(stream_mode="updates")`；chat stream 用 `astream(stream_mode=["updates", "custom"])`
3. **统一 SSE schema**：`{type, task_id, content?, reasoning_content?, agent?, done?}`，chat stream 用 task_id="chat"
4. **Checkpointer 升级**：MemorySaver → MysqlSaver（跨重启状态持久化）
5. **废弃旧 executor**：B-2 + B-3 完成后删除 executors.py

**技术前提已验证**：`get_stream_writer` ✅ + `astream_events` ✅ 可用。

**下一步**：按 B-1 → B-2 → B-3 → B-4 → B-5 顺序实施。B-1 是最小切入点（扩展 StateGraphBuilder，不影响 dispatch），可先做 POC 验证 get_stream_writer + stream_mode="custom" 的 token 级流式效果。
