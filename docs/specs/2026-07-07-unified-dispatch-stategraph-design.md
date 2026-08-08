# dispatch_stream 统一走 StateGraphBuilder — 设计文档

> 日期：2026-07-07
> 子项目：问题 3 治本（dispatch 调度路径统一，子项目 1 后续）
> 范围：A（只统一 dispatch_stream，不动 PlanExecutor/chat stream）
> 方案：1（dependencies 驱动统一入口）
> Spec 依据：`docs/specs/2026-07-07-stategraph-builder-design.md` §10 后续子项目

## 1. 背景

### 1.1 当前问题：并发控制不一致

设计文档 §1.1 的"并发控制不一致"仍存在：

| 路径 | 并发控制 | 问题 |
|------|----------|------|
| langgraph（StateGraphBuilder） | 双层 Semaphore（外部 S=10 + 内部 M=10） | ✅ 真实限制并发 |
| 旧 parallel execute_stream | `create_task`+`gather` 全并发 | ❌ `_max_concurrency` 只用于日志，**无 Semaphore**，N 个 agent 同时发 N 个 LLM 请求，可能触发限流 |
| 旧 dag/sequential execute_stream | `asyncio.gather` 按层/串行 | ❌ 无 Semaphore（dag 层内全并行） |

### 1.2 当前 langgraph 分支局限

`dispatch_stream` 的 langgraph 分支（multi_agent_service.py L177-245）**只支持 parallel 语义**：
- `mode=="langgraph"` 落入 else 分支（L150-164），按 parallel 构建 task_nodes（无 dependencies）
- DAG/sequential 走不到 StateGraphBuilder

### 1.3 能力缺口（需补）

StateGraphBuilder vs 旧 executor 的 11 个缺口中，本设计需补：

| GAP | 描述 | 影响 | 本设计 |
|-----|------|------|--------|
| GAP-2 | `deep_thinking` 参数未透传到 node | deep_thinking 模式静默失效 | ✅ 补 |
| GAP-5 | `on_failure` 语义被 RetryPolicy 抹平 | on_failure="continue" 被错误重试 | ✅ 补 |
| GAP-10 | RetryPolicy `max_attempts` 硬编码 3 | 配置驱动重试失效 | ✅ 补 |
| GAP-1 | 无任务内流式增量 | 丢失 LLM 逐字输出 | ❌ 不补（dispatch 是 task 级事件，非 token 级，影响小） |
| GAP-4 | PlanExecutor 未接入 | chat stream 仍用旧 executor | ❌ 不补（范围 B） |
| GAP-8 | tool_call/tool_result 事件消失 | 工具调用可视化丢失 | ❌ 不补（与 GAP-1 同源，dispatch 不需要） |

## 2. 目标

- dispatch_stream 所有 mode（parallel/dag/sequential/langgraph）统一走 StateGraphBuilder
- 删除 dispatch_stream 旧 executor 分支（L245-328）
- 补 GAP-2（deep_thinking 透传）、GAP-5（on_failure 区分）、GAP-10（retry 读 config）
- StateGraphBuilder 根据 `plan.tasks` 的 `dependencies` 自动构建图结构（无依赖=并行、链式=顺序、fan-in=DAG）

## 3. 非目标

- 不迁移 PlanExecutor/chat stream（范围 B，后续子项目）
- 不统一 chat stream/dispatch 流式格式（问题 2，后续子项目）
- 不补 GAP-1（流式增量，需 LangGraph `astream_events` 调研，独立规划）
- 不删除 `executor/workflow/executors.py`（PlanExecutor 仍用，只删 dispatch_stream 引用）

## 4. 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│  MultiAgentService.dispatch_stream(agent_ids, message, mode)│
│  ├── 构建 ExecutionPlan（根据 mode 设 dependencies）         │
│  │   ├── parallel  → task_nodes 无 dependencies              │
│  │   ├── sequential → task_nodes 链式 dependencies           │
│  │   ├── dag       → task_nodes 用 tasks 参数的 dependencies │
│  │   └── langgraph → 同 parallel（兼容保留）                 │
│  │                                                          │
│  ├── StateGraphBuilder.build(plan, semaphore, max_concurrency, deep_thinking)│
│  │   └── 根据 dependencies 自动建图（fan-in/链式/并行）      │
│  │                                                          │
│  ├── graph.astream(initial_state, config) + DispatchRecord  │
│  │   └── node: semaphore 共享 + adapter.execute_task(deep_thinking) + on_failure│
│  │                                                          │
│  └── 事件包装（去重 + task_failed 检测）→ yield SSE dict     │
└─────────────────────────────────────────────────────────────┘
（删除：旧 executor 分支 L245-328，不再引用 WorkflowParallelExecutor/DAGExecutor/SequentialExecutor）
```

## 5. 组件改动

### 5.1 `services/multi_agent_service.py` dispatch_stream

**移除**：L245-328 旧 executor 分支（`if plan_mode == PlanMode.DAG...` 选 executor + execute_stream 转发 + 持久化）。

**扩展 langgraph 分支为通用入口**（当前 L177-245）：
- 移除 `if mode == "langgraph":` 专属判断，让所有 mode 进入 StateGraphBuilder 路径
- `mode="dag"` 分支（L111-127）：保留现有 task_nodes 构建（从 tasks 的 dependencies 转 task_id 依赖）
- `mode="sequential"` 分支（L135-149）：改为链式 dependencies
  ```python
  # sequential：链式依赖 t_i 依赖 t_{i-1}
  for i, aid in enumerate(agent_ids):
      deps = [f"task_{i-1}_{agent_ids[i-1]}"] if i > 0 else []
      task_nodes.append(TaskNode(id=f"task_{i}_{aid}", ..., dependencies=deps, on_failure="continue"))
  ```
- `mode="parallel"` 分支（L150-164）：无 dependencies（现状不变）
- `mode="langgraph"`：映射到 parallel（兼容保留），或直接废弃（用户可选）

**保留**：DispatchRecord 持久化逻辑（running→completed/failed）。

### 5.2 `executor/workflow/stategraph_builder.py`（补 GAP）

**GAP-2 — deep_thinking 透传**：
- `build()` 增加 `deep_thinking: bool = False` 形参
- `_make_node_func()` 的 node 函数调用 `adapter.execute_task(..., deep_thinking=deep_thinking)`

**GAP-5 — on_failure 区分**：
- `_get_retry_policy(task)` 根据 `task.on_failure` 决定：
  - `on_failure="continue"` → 不设 RetryPolicy（返回 None，node catch 异常返回 errors dict）
  - `on_failure="stop"` / `"retry"` → 设 RetryPolicy（重试 max_attempts 次）
- `build()` 的 `add_node(retry_policy=...)` 仅在 retry_policy 非 None 时传入

**GAP-10 — retry 读 config**：
- `_get_retry_policy()` 的 `max_attempts` 改为 `get_config('agent.execution.retry.max_attempts', 3)`

### 5.3 不改动

- `executor/workflow/executors.py`（PlanExecutor 仍用，保留）
- `executor/workflow/base.py` / `engine.py` / `dispatcher.py` / `scheduler.py`（PlanExecutor 仍用）
- 前端（事件格式不变：task_started/content_chunk/task_completed/task_failed）
- StateGraphBuilder 的 `build`/`_add_edges`/reducer/dedup（已验证）
- `executor/plan_executor.py`（chat stream 路径，保持旧 executor）

## 6. 数据流

```
dispatch_stream(agent_ids, message, mode, tasks)
  │
  ├─ 1. 构建 adapter（create_langgraph_adapter，现状 L100-107）
  │
  ├─ 2. 构建 ExecutionPlan（根据 mode 设 dependencies）
  │    ├─ parallel  → 无 deps
  │    ├─ sequential → 链式 deps (t_i → t_{i-1})
  │    ├─ dag       → tasks 参数的 deps
  │    └─ langgraph → 同 parallel
  │
  ├─ 3. 循环依赖检测（dag 分支已有 L128-132）
  │
  ├─ 4. StateGraphBuilder.build(plan, semaphore, max_concurrency, deep_thinking)
  │    └─ add_node(task.id, node_func, retry_policy=按 on_failure)
  │    └─ add_edge(START/dependencies/END)
  │    └─ compile(checkpointer)
  │
  ├─ 5. DispatchRecord 持久化（running）
  │
  ├─ 6. graph.astream(initial_state, config)
  │    └─ node: async with semaphore → adapter.execute_task(deep_thinking)
  │    └─ on_failure="stop" → raise → RetryPolicy 重试 → 仍失败 graph 终止
  │    └─ on_failure="continue" → 返回 errors dict → task_failed 事件
  │
  ├─ 7. 事件包装（去重 + errors 检测 → task_failed/task_completed）
  │
  └─ 8. DispatchRecord 更新（completed/failed）
```

## 7. 错误处理

| 场景 | 行为 |
|------|------|
| task 异常 + on_failure="stop" | node raise → RetryPolicy（max_attempts from config）重试 → 仍失败 graph 终止 → yield error 事件 + DispatchRecord=failed |
| task 异常 + on_failure="continue" | node catch → 返回 errors dict → yield task_failed + content_chunk(error 内容) → graph 继续 → DispatchRecord=completed（部分失败） |
| task 异常 + on_failure="retry" | 同 "stop"（RetryPolicy 重试），仍失败后 graph 终止 |
| 循环依赖（dag） | L128-132 Kahn 检测 → yield error "DAG 循环依赖检测到" + return |
| 无有效 agent | L166-168 → yield error "无有效 agent" + return |

## 8. 测试策略

| 测试 | 类型 | 验证 |
|------|------|------|
| `test_dispatch_dag_via_stategraph` | 新增集成 | mode="dag" 走 StateGraphBuilder，fan-in 依赖正确，事件流完整 |
| `test_dispatch_sequential_via_stategraph` | 新增集成 | mode="sequential" 走 StateGraphBuilder，链式依赖 + context 传递（后 task 读前 task 结果） |
| `test_deep_thinking_passthrough` | 新增单元 | node 函数透传 deep_thinking 到 adapter.execute_task |
| `test_retry_policy_reads_config` | 新增单元 | RetryPolicy max_attempts 从 config 读取（mock config） |
| `test_on_failure_continue_no_retry` | 新增单元 | on_failure="continue" 不设 RetryPolicy（不重试） |
| 现有 `test_stategraph_builder` (5 case) | 回归 | build/dag/semaphore/on_failure 不破坏 |
| 现有 `test_langgraph_dispatch` (3 case) | 回归 | parallel/multi-task/task_failed 不破坏 |
| `test_dag_dispatch` / `test_parallel_stream` / `test_crash_recovery_sequential` | 回归 | 旧测试适配新路径（dispatch 事件格式不变，应通过；若 mock 旧 executor 则调整 mock） |

**测试命令**：`"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest <test_file> -v`

## 9. 风险与回退

| 风险 | 等级 | 缓解 |
|------|------|------|
| 旧回归测试依赖旧 executor mock | 中 | dispatch 事件格式不变（task_started/content_chunk/task_completed/task_failed），测试应通过；若直接 mock WorkflowXxxExecutor 则改为 mock adapter |
| sequential context 传递 | 低 | GAP-11 已确认功能等价（reducer 合并 + adapter 读 deps） |
| on_failure="retry" 语义变化 | 低 | 旧 retry_queue 退避 vs RetryPolicy 退避，参数不同但语义一致（重试 max_attempts 次后退避），可接受 |
| 前端兼容 | 低 | 事件格式不变，前端无需改 |

**回退策略**：保留 `executor/workflow/executors.py` 不删除。若新路径有问题，恢复 dispatch_stream L245-328 旧 executor 分支引用即可（git diff 可逆，非 git repo 则手动恢复）。

## 10. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `services/multi_agent_service.py` | 修改 | dispatch_stream 删除旧 executor 分支（L245-328），扩展 langgraph 分支为通用入口，sequential 改链式 deps |
| `executor/workflow/stategraph_builder.py` | 修改 | 补 GAP-2（deep_thinking）、GAP-5（on_failure 区分）、GAP-10（retry 读 config） |
| `test/test_langgraph_dispatch.py` | 修改 | 新增 dag/sequential dispatch 测试 |
| `test/test_stategraph_builder.py` | 修改 | 新增 deep_thinking/retry_config/on_failure_continue 测试 |

### 不修改的文件

- `executor/workflow/executors.py`（PlanExecutor 仍用）
- `executor/workflow/base.py` / `engine.py` / `dispatcher.py` / `scheduler.py`（PlanExecutor 仍用）
- `executor/plan_executor.py`（chat stream 路径，范围 B）
- `frontend/`（事件格式不变）
- `api/admin/agent_manage.py`（dispatch-multi 路由不变）

## 11. 后续子项目

| 顺序 | 子项目 | 依赖 |
|------|--------|------|
| 本设计 | dispatch 统一 StateGraphBuilder | 子项目 1 ✅ |
| B | 迁移 PlanExecutor/chat stream | 本设计 + GAP-1 调研 |
| 问题 2 | 统一 chat stream/dispatch 流式格式 | B |
| 子项目 5 | 废弃 executors.py | B + 问题 2 |
