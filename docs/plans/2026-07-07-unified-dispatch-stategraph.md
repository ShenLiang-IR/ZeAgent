# dispatch_stream 统一走 StateGraphBuilder 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 dispatch_stream 的所有 mode（parallel/dag/sequential）统一走 StateGraphBuilder，废弃旧 executor 分支，补 GAP-2/5/10

**Architecture:** 删除 dispatch_stream 旧 executor 分支（L245-328），扩展 langgraph 分支为通用入口；StateGraphBuilder 根据 plan.tasks 的 dependencies 自动建图（无依赖=并行、链式=顺序、fan-in=DAG）；补 deep_thinking 透传 + on_failure 语义 + retry 读 config

**Tech Stack:** LangGraph StateGraph + RetryPolicy + Annotated reducer + asyncio.Semaphore

**Spec:** `docs/specs/2026-07-07-unified-dispatch-stategraph-design.md`

**Environment:** conda env `D:\ProgramData\miniconda3\envs\install_deb_refactor`，非 git repo（无 commit 步骤），Python 3.13，pytest + pytest-asyncio（asyncio_mode=auto）

**Test command:** `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest <test_file> -v`

---

## File Structure

| File | Type | Responsibility |
|------|------|----------------|
| `executor/workflow/stategraph_builder.py` | Modify | 补 GAP-2（deep_thinking）+ GAP-5（on_failure 区分）+ GAP-10（retry 读 config） |
| `services/multi_agent_service.py` | Modify | dispatch_stream sequential 改链式 deps + 删除旧 executor 分支 + 统一走 StateGraphBuilder |
| `test/test_stategraph_builder.py` | Modify | 新增 deep_thinking/retry_config/on_failure_continue 测试 |
| `test/test_langgraph_dispatch.py` | Modify | 新增 dag/sequential dispatch 端到端测试 |

---

### Task 1: StateGraphBuilder 补 GAP-2 deep_thinking 透传

**Files:**
- Modify: `executor/workflow/stategraph_builder.py`
- Modify: `test/test_stategraph_builder.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 test/test_stategraph_builder.py
@pytest.mark.asyncio
async def test_build_passes_deep_thinking_to_node_func():
    """build() 的 deep_thinking 参数透传到 node 函数的 adapter.execute_task 调用。"""
    import asyncio
    from utils.planning.schemas import ExecutionPlan, TaskNode, PlanMode
    from langgraph.checkpoint.memory import MemorySaver

    plan = ExecutionPlan(
        tasks=[TaskNode(id="t1", agent="a", description="test")],
        original_query="test", mode=PlanMode.PARALLEL,
    )
    adapter = MagicMock()
    adapter.execute_task = AsyncMock(return_value="result")

    builder = StateGraphBuilder(adapter=adapter, checkpointer=MemorySaver())
    node_func = builder._make_node_func(
        plan.tasks[0], plan, asyncio.Semaphore(10), deep_thinking=True
    )

    await node_func({"results": {}})

    # 验证 deep_thinking=True 被透传
    _, kwargs = adapter.execute_task.call_args
    assert kwargs.get("deep_thinking") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_stategraph_builder.py::test_build_passes_deep_thinking_to_node_func -v`
Expected: FAIL with `TypeError: _make_node_func() got an unexpected keyword argument 'deep_thinking'`

- [ ] **Step 3: Modify _make_node_func to accept deep_thinking**

```python
# executor/workflow/stategraph_builder.py — _make_node_func 方法
# 修改签名 + node 函数内调用 adapter.execute_task 加 deep_thinking

    def _make_node_func(
        self,
        task: TaskNode,
        plan: ExecutionPlan,
        semaphore: asyncio.Semaphore,
        deep_thinking: bool = False,
    ):
        """创建 node 函数，内部共享 semaphore 并调用 adapter。"""
        adapter = self._adapter

        async def node(state: WorkflowState) -> dict:
            async with semaphore:
                try:
                    result = await adapter.execute_task(
                        task=task,
                        plan=plan,
                        context=state.get("results", {}),
                        deep_thinking=deep_thinking,
                    )
                    return {"results": {task.id: result}}
                except Exception as e:
                    logger.error(f"[StateGraphBuilder] task {task.id} failed: {e}")
                    if task.on_failure == "stop":
                        raise
                    return {
                        "errors": {task.id: str(e)},
                        "results": {task.id: f"error: {e}"},
                    }

        return node
```

- [ ] **Step 4: Modify build() to accept and pass deep_thinking**

```python
# executor/workflow/stategraph_builder.py — build 方法签名
# 加 deep_thinking 形参，传给 _make_node_func

    def build(
        self,
        plan: ExecutionPlan,
        semaphore: asyncio.Semaphore,
        max_concurrency: int = 10,
        deep_thinking: bool = False,
    ) -> CompiledStateGraph:
        # ... 现有 docstring ...
        builder = StateGraph(WorkflowState)

        # 1. 为每个 task 创建 node 函数
        for task in plan.tasks:
            node_func = self._make_node_func(task, plan, semaphore, deep_thinking=deep_thinking)
            retry_policy = self._get_retry_policy(task)
            builder.add_node(task.id, node_func, retry_policy=retry_policy)

        # ... 其余不变 ...
```

- [ ] **Step 5: Run test to verify it passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_stategraph_builder.py::test_build_passes_deep_thinking_to_node_func -v`
Expected: PASS

---

### Task 2: StateGraphBuilder 补 GAP-10 retry 读 config + GAP-5 on_failure 区分

**Files:**
- Modify: `executor/workflow/stategraph_builder.py`
- Modify: `test/test_stategraph_builder.py`

- [ ] **Step 1: Write the failing tests**

```python
# 追加到 test/test_stategraph_builder.py
def test_get_retry_policy_reads_config_max_attempts():
    """RetryPolicy max_attempts 从 config 读取。"""
    from unittest.mock import patch
    with patch("executor.workflow.stategraph_builder.get_config", return_value=5):
        builder = StateGraphBuilder(adapter=MagicMock(), checkpointer=None)
        from utils.planning.schemas import TaskNode
        task = TaskNode(id="t1", agent="a", description="t", on_failure="stop")
        policy = builder._get_retry_policy(task)
        assert policy.max_attempts == 5


def test_get_retry_policy_none_for_on_failure_continue():
    """on_failure="continue" 不设 RetryPolicy（不重试）。"""
    from utils.planning.schemas import TaskNode
    builder = StateGraphBuilder(adapter=MagicMock(), checkpointer=None)
    task = TaskNode(id="t1", agent="a", description="t", on_failure="continue")
    policy = builder._get_retry_policy(task)
    assert policy is None


def test_get_retry_policy_set_for_on_failure_stop():
    """on_failure="stop" 设 RetryPolicy（重试）。"""
    from langgraph.types import RetryPolicy
    from utils.planning.schemas import TaskNode
    builder = StateGraphBuilder(adapter=MagicMock(), checkpointer=None)
    task = TaskNode(id="t1", agent="a", description="t", on_failure="stop")
    policy = builder._get_retry_policy(task)
    assert isinstance(policy, RetryPolicy)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_stategraph_builder.py::test_get_retry_policy_reads_config_max_attempts test/test_stategraph_builder.py::test_get_retry_policy_none_for_on_failure_continue test/test_stategraph_builder.py::test_get_retry_policy_set_for_on_failure_stop -v`
Expected: FAIL（当前 _get_retry_policy 不看 on_failure，不读 config，总返回 RetryPolicy）

- [ ] **Step 3: Rewrite _get_retry_policy + import get_config**

```python
# executor/workflow/stategraph_builder.py — 顶部 import 区加 get_config
from utils.config import get_config
from utils.planning.schemas import ExecutionPlan, TaskNode

# executor/workflow/stategraph_builder.py — _get_retry_policy 方法重写
    def _get_retry_policy(self, task: TaskNode):
        """获取节点的重试策略。

        GAP-5: on_failure="continue" 不重试（node catch 异常返回 errors）；
              on_failure="stop"/"retry" 设 RetryPolicy 重试。
        GAP-10: max_attempts 从 config 读取。
        """
        if task.on_failure == "continue":
            return None  # 不重试，node 函数 catch 后返回 errors dict
        return RetryPolicy(
            initial_interval=0.5,
            backoff_factor=2.0,
            max_interval=128.0,
            max_attempts=get_config("agent.execution.retry.max_attempts", 3),
            jitter=True,
        )
```

- [ ] **Step 4: Modify build() add_node to handle None retry_policy**

```python
# executor/workflow/stategraph_builder.py — build 方法内 add_node 调用
# retry_policy 可能 None，add_node 只在非 None 时传

        for task in plan.tasks:
            node_func = self._make_node_func(task, plan, semaphore, deep_thinking=deep_thinking)
            retry_policy = self._get_retry_policy(task)
            if retry_policy is not None:
                builder.add_node(task.id, node_func, retry_policy=retry_policy)
            else:
                builder.add_node(task.id, node_func)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_stategraph_builder.py::test_get_retry_policy_reads_config_max_attempts test/test_stategraph_builder.py::test_get_retry_policy_none_for_on_failure_continue test/test_stategraph_builder.py::test_get_retry_policy_set_for_on_failure_stop -v`
Expected: PASS

- [ ] **Step 6: Run existing stategraph tests to verify no regression**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_stategraph_builder.py -v`
Expected: 全部 PASS（注意：现有测试用 on_failure="stop" 默认，仍走 RetryPolicy；on_failure_stop_propagates_exception 测试仍通过）

---

### Task 3: dispatch_stream sequential 改链式 dependencies

**Files:**
- Modify: `services/multi_agent_service.py` (sequential 分支 L135-149)
- Modify: `test/test_langgraph_dispatch.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 test/test_langgraph_dispatch.py
@pytest.mark.asyncio
async def test_dispatch_sequential_via_stategraph():
    """mode="sequential" 走 StateGraphBuilder，链式依赖 t1→t2，context 传递。"""
    from services.multi_agent_service import MultiAgentService

    service = MultiAgentService.__new__(MultiAgentService)
    service._db = MagicMock()
    configs = {"a1": {"agent_name": "agent_a"}, "a2": {"agent_name": "agent_b"}}
    service._db.subagents.get_by_id.side_effect = lambda aid: configs.get(aid)

    # adapter 按 task.id 返回不同结果，验证 context 传递
    mock_adapter = MagicMock()
    async def fake_execute(task, **kw):
        ctx = kw.get("context", {})
        dep_result = ctx.get("task_0_a1", "") if task.id == "task_1_a2" else ""
        return f"{task.id} saw: {dep_result}"
    mock_adapter.execute_task = AsyncMock(side_effect=fake_execute)

    with patch("executor.langgraph.LangGraphTaskExecutor"), \
         patch("executor.workflow.langgraph_adapter.create_langgraph_adapter", return_value=mock_adapter), \
         patch("utils.llm.get_default_llm", return_value=MagicMock()), \
         patch("infrastructure.database.sessions.get_config_session") as mock_gs:
        mock_gs.return_value.__enter__.return_value = MagicMock()
        events = []
        async for event in service.dispatch_stream(
            agent_ids=["a1", "a2"], message="hi", mode="sequential"
        ):
            events.append(event)

    # 验证：两个 task 都执行，顺序产出
    assert any(e["type"] == "task_completed" for e in events)
    assert mock_adapter.execute_task.call_count == 2
    # task_1_a2 应该看到 task_0_a1 的结果（context 传递）
    t1_events = [e for e in events if e.get("task_id") == "task_1_a2" and e["type"] == "content_chunk"]
    if t1_events:
        assert "task_0_a1" in t1_events[0]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langgraph_dispatch.py::test_dispatch_sequential_via_stategraph -v`
Expected: FAIL（当前 sequential 走旧 executor，不经过 mock_adapter；或 mode="sequential" 走旧 WorkflowSequentialExecutor）

- [ ] **Step 3: Modify sequential branch to set chain dependencies**

```python
# services/multi_agent_service.py — sequential 分支（约 L135-149）
# 当前：task_nodes 无 dependencies
# 改为：链式 dependencies（t_i 依赖 t_{i-1}）

        elif mode == "sequential":
            # ③顺序调度：链式顺序执行（context 传递）
            prev_task_id = None
            for i, aid in enumerate(agent_ids):
                cfg = self._db.subagents.get_by_id(aid)
                if not cfg:
                    logger.warning(f"[MultiAgent] agent {aid} 不存在，跳过")
                    continue
                task_id = f"task_{i}_{aid}"
                deps = [prev_task_id] if prev_task_id else []
                task_nodes.append(TaskNode(
                    id=task_id,
                    agent=cfg.get("agent_name", ""),
                    description=message,
                    dependencies=deps,
                    on_failure="continue",
                ))
                prev_task_id = task_id
            plan_mode = PlanMode.SEQUENTIAL
            session_id = "seq_dispatch"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langgraph_dispatch.py::test_dispatch_sequential_via_stategraph -v`
Expected: PASS（注意：此测试在 Task 4 删除旧分支后才真正走 StateGraphBuilder；此步可能仍走旧分支——若失败，先做 Task 4 再回来）

> **注意**：此测试依赖 Task 4（删除旧 executor 分支）。如果 Step 4 失败（sequential 仍走旧 executor），先执行 Task 4，再回来跑此测试。

---

### Task 4: dispatch_stream 删除旧 executor 分支，统一走 StateGraphBuilder

**Files:**
- Modify: `services/multi_agent_service.py` (删除 L245-328 旧分支 + 移除 langgraph 专属判断)

- [ ] **Step 1: Read current dispatch_stream to confirm line numbers**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -c "import services.multi_agent_service as m; import inspect; src=inspect.getsource(m.MultiAgentService.dispatch_stream); print(src)" 2>&1 | head -5`
确认 L177 `if mode == "langgraph":` 和 L245-328 旧 executor 分支位置。

- [ ] **Step 2: Remove the `if mode == "langgraph":` guard, make StateGraphBuilder the universal path**

```python
# services/multi_agent_service.py — 将 L177 的 `if mode == "langgraph":` 改为
# 所有 mode 都走 StateGraphBuilder（移除 if 守卫，保留内部逻辑）
# 即把 L177 `if mode == "langgraph":` 改为无条件执行（或保留 if 但移除 mode 条件）

        # 统一调度：StateGraphBuilder 动态构建 StateGraph（所有 mode）
        import asyncio as _aio
        import uuid as _uuid
        import json as _json
        from executor.workflow.stategraph_builder import StateGraphBuilder
        from langgraph.checkpoint.memory import MemorySaver
        from infrastructure.database.sessions import get_config_session
        from infrastructure.database.models.dispatch_record import DispatchRecord

        dispatch_id = str(_uuid.uuid4())
        max_concurrency = 10
        semaphore = _aio.Semaphore(max_concurrency)
        checkpointer = MemorySaver()

        builder = StateGraphBuilder(
            adapter=adapter,
            checkpointer=checkpointer,
        )
        graph = builder.build(
            plan=plan,
            semaphore=semaphore,
            max_concurrency=max_concurrency,
        )

        # ... 保留 DispatchRecord 持久化 + astream + 事件包装逻辑 ...
        # ... （L200-244 的逻辑不变） ...
```

- [ ] **Step 3: Delete old executor branch (L245-328)**

删除从 `# 3. 选 executor（parallel/dag/sequential）` 到 dispatch_stream 方法结束的旧 executor 分支代码（`if plan_mode == PlanMode.DAG...` 选 executor + execute_stream 转发 + 持久化 + finally close）。

同时删除顶部 import：`from executor.workflow.executors import WorkflowParallelExecutor, WorkflowDAGExecutor, WorkflowSequentialExecutor`（L96）。

- [ ] **Step 3b: Align DispatchRecord persistence with old branch**

当前 langgraph 分支的 DispatchRecord 持久化与旧 executor 分支有两处差异，需对齐：

1. **completed 时补写 result 字段**（旧分支写 `result=json(collected_results)`，langgraph 分支不写）：
```python
# services/multi_agent_service.py — langgraph 分支 completed 更新处（约 L233-237）
# 当前：session.query(DispatchRecord).filter(...).update({"status": "completed"})
# 改为：
                with get_config_session() as session:
                    session.query(DispatchRecord).filter(
                        DispatchRecord.pr_key_id == record_pk
                    ).update({
                        "status": "completed",
                        "result": _json.dumps(collected_results, ensure_ascii=False),
                    })
```

2. **failed 时 error 截断 500 字符**（旧分支 `str(e)[:500]`，langgraph 分支不截断）：
```python
# services/multi_agent_service.py — langgraph 分支 failed 更新处（约 L238-243）
# 当前：.update({"status": "failed", "error": str(e)})
# 改为：
                with get_config_session() as session:
                    session.query(DispatchRecord).filter(
                        DispatchRecord.pr_key_id == record_pk
                    ).update({"status": "failed", "error": str(e)[:500]})
```

> **依据**：agent 3 调查报告缺口 4 — DispatchRecord 持久化差异。统一后所有 mode 的持久化行为一致。

- [ ] **Step 4: Run sequential + dag dispatch tests**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langgraph_dispatch.py -v`
Expected: 全部 PASS（parallel + multi-task + task_failed + sequential）

- [ ] **Step 5: Run existing langgraph dispatch tests to verify no regression**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langgraph_dispatch.py::test_dispatch_stream_langgraph_mode test/test_langgraph_dispatch.py::test_dispatch_stream_langgraph_multi_task_no_duplicate_events -v`
Expected: PASS（注意：mode="langgraph" 仍走 StateGraphBuilder，行为不变）

---

### Task 5: dag dispatch 端到端测试

**Files:**
- Modify: `test/test_langgraph_dispatch.py`

- [ ] **Step 1: Write the test**

```python
# 追加到 test/test_langgraph_dispatch.py
@pytest.mark.asyncio
async def test_dispatch_dag_via_stategraph():
    """mode="dag" 走 StateGraphBuilder，fan-in 依赖正确，t3 等 t1+t2 完成。"""
    from services.multi_agent_service import MultiAgentService

    service = MultiAgentService.__new__(MultiAgentService)
    service._db = MagicMock()
    configs = {"a1": {"agent_name": "agent_a"}, "a2": {"agent_name": "agent_b"}, "a3": {"agent_name": "agent_c"}}
    service._db.subagents.get_by_id.side_effect = lambda aid: configs.get(aid)

    mock_adapter = MagicMock()
    mock_adapter.execute_task = AsyncMock(side_effect=lambda task, **kw: f"result_{task.id}")

    # dag tasks: t0(a1) → t2(a3), t1(a2) → t2(a3)
    tasks_def = [
        {"agent_id": "a1", "dependencies": []},
        {"agent_id": "a2", "dependencies": []},
        {"agent_id": "a3", "dependencies": [0, 1]},
    ]

    with patch("executor.langgraph.LangGraphTaskExecutor"), \
         patch("executor.workflow.langgraph_adapter.create_langgraph_adapter", return_value=mock_adapter), \
         patch("utils.llm.get_default_llm", return_value=MagicMock()), \
         patch("infrastructure.database.sessions.get_config_session") as mock_gs:
        mock_gs.return_value.__enter__.return_value = MagicMock()
        events = []
        async for event in service.dispatch_stream(
            agent_ids=["a1", "a2", "a3"], message="dag test", mode="dag", tasks=tasks_def
        ):
            events.append(event)

    # 验证：3 个 task 都完成
    completed = [e for e in events if e["type"] == "task_completed"]
    assert len(completed) == 3
    # 无 error
    assert not any(e["type"] == "error" for e in events)
    # adapter 被调用 3 次
    assert mock_adapter.execute_task.call_count == 3
```

- [ ] **Step 2: Run test to verify it passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langgraph_dispatch.py::test_dispatch_dag_via_stategraph -v`
Expected: PASS（dag 分支已有 task_nodes 构建 + 循环检测，StateGraphBuilder 支持 fan-in）

---

### Task 6: 回归测试

**Files:**
- No changes

- [ ] **Step 1: Run all stategraph_builder tests**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_stategraph_builder.py -v`
Expected: 全部 PASS（含 deep_thinking + retry_config + on_failure 区分）

- [ ] **Step 2: Run all langgraph_dispatch tests**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langgraph_dispatch.py -v`
Expected: 全部 PASS（parallel + multi-task + task_failed + sequential + dag）

- [ ] **Step 3: Run old regression tests**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test_multi_agent_dispatch.py test_dag_dispatch.py test_dispatch_persistence.py test_parallel_stream.py test_crash_recovery_sequential.py test_mcp_stdio.py -v --tb=short 2>&1 | tail -20`
Expected: 全部 PASS（事件格式不变，测试应通过；若 test_dag_dispatch/test_parallel_stream mock 旧 executor，需调整为 mock adapter）

> **注意**：如果旧回归测试因 mock WorkflowXxxExecutor 而失败，需检查测试是否直接 mock 旧 executor 类。如果是，改为 mock adapter（`create_langgraph_adapter`），因为 dispatch_stream 不再用旧 executor。

- [ ] **Step 4: Verify dispatch-multi API end-to-end (if backend running)**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -c "
import httpx, json
payload = {'agentIds': ['7', '24'], 'message': '你好', 'mode': 'parallel'}
with httpx.Client(timeout=60) as c:
    with c.stream('POST', 'http://127.0.0.1:8050/api/admin/agents/dispatch-multi', json=payload) as r:
        print('HTTP', r.status_code)
        n = 0
        for line in r.iter_lines():
            if line.startswith('data: '):
                n += 1
        print(f'events: {n}')
" 2>&1 | tail -3`
Expected: HTTP 200, events > 0（如果后端 8050 未运行，跳过此步）

---

## Self-Review

**Spec coverage:**
- ✅ dispatch_stream 所有 mode 走 StateGraphBuilder → Task 4
- ✅ 删除旧 executor 分支 → Task 4 Step 3
- ✅ GAP-2 deep_thinking 透传 → Task 1
- ✅ GAP-5 on_failure 区分 → Task 2
- ✅ GAP-10 retry 读 config → Task 2
- ✅ sequential 链式 dependencies → Task 3
- ✅ dag 端到端测试 → Task 5
- ✅ 回归测试 → Task 6

**Placeholder scan:** 无 TBD/TODO，所有代码完整。Task 4 Step 2/3 用 `...` 标注保留逻辑，需实现者对照实际代码确认行号。

**Type consistency:** _make_node_func(deep_thinking) / _get_retry_policy(task) / build(deep_thinking) 在所有 task 中一致。on_failure="continue" → None retry_policy，add_node 条件传入。

**风险提示：**
- Task 4 删除 L245-328 前，确认行号（reload 可能改变行号）
- Task 6 Step 3 旧回归测试可能需调整 mock（如果直接 mock 旧 executor）
- Task 3 Step 4 可能需先做 Task 4（sequential 走旧 executor → StateGraphBuilder）
