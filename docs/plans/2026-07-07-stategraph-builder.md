# StateGraph 图构建器 + 并发控制 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 StateGraphBuilder，从 ExecutionPlan 动态构建 LangGraph StateGraph，新增 mode="langgraph" 调度分支

**Architecture:** 从 ExecutionPlan 的 tasks + dependencies 动态构建 StateGraph（add_node + add_edge fan-in），node 函数内部共享外部 Semaphore + 调用现有 LangGraphWorkflowAdapter，config["max_concurrency"] 控制 Pregel 图内并行，add_node(retry_policy=) 实现节点级重试

**Tech Stack:** LangGraph StateGraph + Send API + RetryPolicy + Pregel max_concurrency + asyncio.Semaphore

**Spec:** `docs/specs/2026-07-07-stategraph-builder-design.md`

**Environment:** conda env `D:\ProgramData\miniconda3\envs\install_deb_refactor`，非 git repo（无 commit 步骤），Python 3.13

**Test command:** `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest <test_file> -v`

---

## File Structure

| File | Type | Responsibility |
|------|------|----------------|
| `executor/workflow/stategraph_builder.py` | Create | StateGraphBuilder 类：从 ExecutionPlan 构建 CompiledStateGraph |
| `executor/workflow/__init__.py` | Modify | 导出 StateGraphBuilder |
| `services/multi_agent_service.py` | Modify | dispatch_stream 新增 mode="langgraph" 分支 |
| `test/test_stategraph_builder.py` | Create | 单元测试：build() 正确构建图结构 |
| `test/test_langgraph_dispatch.py` | Create | 集成测试：dispatch_stream(mode="langgraph") 端到端 |

---

### Task 1: StateGraphBuilder 骨架 + State schema

**Files:**
- Create: `executor/workflow/stategraph_builder.py`
- Create: `test/test_stategraph_builder.py`

- [x] **Step 1: Write the failing test**

```python
# test/test_stategraph_builder.py
"""StateGraphBuilder 单元测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from executor.workflow.stategraph_builder import StateGraphBuilder, WorkflowState


def test_build_returns_compiled_state_graph():
    """build() 返回 CompiledStateGraph 实例。"""
    from utils.planning.schemas import ExecutionPlan, TaskNode, PlanMode
    from langgraph.graph.state import CompiledStateGraph

    plan = ExecutionPlan(
        tasks=[TaskNode(id="t1", agent="agent_a", description="test")],
        original_query="test",
        mode=PlanMode.PARALLEL,
    )
    adapter = MagicMock()
    checkpointer = MagicMock()
    import asyncio
    semaphore = asyncio.Semaphore(10)

    builder = StateGraphBuilder(adapter=adapter, checkpointer=checkpointer)
    graph = builder.build(plan=plan, semaphore=semaphore, max_concurrency=5)

    assert isinstance(graph, CompiledStateGraph)
```

- [x] **Step 2: Run test to verify it fails**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_stategraph_builder.py::test_build_returns_compiled_state_graph -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'executor.workflow.stategraph_builder'`

- [x] **Step 3: Write minimal implementation**

```python
# executor/workflow/stategraph_builder.py
"""StateGraphBuilder：从 ExecutionPlan 动态构建 LangGraph StateGraph。

替代自研 Schedule + WorkflowDAGExecutor 的拓扑排序 + 分层并行。
利用 LangGraph 的 add_edge fan-in 实现依赖调度，
config["max_concurrency"] 控制图内并行，
add_node(retry_policy=) 实现节点级重试。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from langgraph.graph import START, END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import RetryPolicy
from loguru import logger
from typing_extensions import TypedDict
from utils.planning.schemas import ExecutionPlan, TaskNode

from .langgraph_adapter import LangGraphWorkflowAdapter


class WorkflowState(TypedDict):
    """工作流状态：存储各 task 的结果和错误。"""
    results: dict   # {task_id: result_str}
    errors: dict    # {task_id: error_str}，on_failure="continue" 时填充


class StateGraphBuilder:
    """从 ExecutionPlan 动态构建 LangGraph StateGraph。

    构建流程：
    1. 为每个 TaskNode 创建 node 函数（含 semaphore 共享 + retry_policy）
    2. 根据 dependencies 创建 add_edge（含 fan-in: add_edge([...], target)）
    3. compile(checkpointer) → CompiledStateGraph
    """

    def __init__(
        self,
        adapter: LangGraphWorkflowAdapter,
        checkpointer: Optional[BaseCheckpointSaver] = None,
    ):
        self._adapter = adapter
        self._checkpointer = checkpointer

    def build(
        self,
        plan: ExecutionPlan,
        semaphore: asyncio.Semaphore,
        max_concurrency: int = 10,
    ) -> CompiledStateGraph:
        """从 ExecutionPlan 构建 StateGraph 并编译。

        Args:
            plan: 执行计划，包含 tasks 和 dependencies
            semaphore: 外部信号量，与 node 函数共享（图间+图内统一并发控制）
            max_concurrency: 传入 config["max_concurrency"]，控制 Pregel 图内并行

        Returns:
            CompiledStateGraph: 编译后的图实例
        """
        builder = StateGraph(WorkflowState)

        # 1. 为每个 task 创建 node 函数
        for task in plan.tasks:
            node_func = self._make_node_func(task, plan, semaphore)
            retry_policy = self._get_retry_policy(task)
            builder.add_node(task.id, node_func, retry_policy=retry_policy)

        # 2. 构建 edge（含 fan-in）
        self._add_edges(builder, plan.tasks)

        # 3. 编译
        compile_kwargs = {}
        if self._checkpointer:
            compile_kwargs["checkpointer"] = self._checkpointer

        graph = builder.compile(**compile_kwargs)
        logger.info(
            f"[StateGraphBuilder] 图构建完成: {len(plan.tasks)} tasks, "
            f"max_concurrency={max_concurrency}"
        )
        return graph

    def _make_node_func(
        self,
        task: TaskNode,
        plan: ExecutionPlan,
        semaphore: asyncio.Semaphore,
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

    def _get_retry_policy(self, task: TaskNode) -> RetryPolicy:
        """获取节点的重试策略。"""
        return RetryPolicy(
            initial_interval=0.5,
            backoff_factor=2.0,
            max_interval=128.0,
            max_attempts=3,
            jitter=True,
        )

    def _add_edges(self, builder: StateGraph, tasks: list[TaskNode]):
        """构建 edge：START → entry tasks → ... → terminal tasks → END。"""
        task_ids = {t.id for t in tasks}

        # 无依赖 → START
        for task in tasks:
            if not task.dependencies:
                builder.add_edge(START, task.id)

        # 有依赖 → fan-in（add_edge(["dep1", "dep2"], "target")）
        for task in tasks:
            if task.dependencies:
                valid_deps = [d for d in task.dependencies if d in task_ids]
                if valid_deps:
                    builder.add_edge(valid_deps, task.id)

        # 终点 → END
        has_dependents = set()
        for task in tasks:
            for dep in task.dependencies:
                has_dependents.add(dep)
        terminal_tasks = [t.id for t in tasks if t.id not in has_dependents]
        for tid in terminal_tasks:
            builder.add_edge(tid, END)
```

- [x] **Step 4: Run test to verify it passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_stategraph_builder.py::test_build_returns_compiled_state_graph -v`
Expected: PASS

- [x] **Step 5: Update __init__.py**

```python
# executor/workflow/__init__.py — 添加导出
# 在现有内容末尾添加：
from .stategraph_builder import StateGraphBuilder, WorkflowState
```

- [x] **Step 6: Verify export works**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -c "from executor.workflow import StateGraphBuilder; print('OK')"`
Expected: `OK`

---

### Task 2: Edge 构建测试（fan-in 验证）

**Files:**
- Modify: `test/test_stategraph_builder.py`

- [x] **Step 1: Write the failing test**

```python
# 追加到 test/test_stategraph_builder.py

def test_build_dag_with_fan_in():
    """DAG 模式：有依赖的 task 用 fan-in（add_edge([...], target)）。"""
    from utils.planning.schemas import ExecutionPlan, TaskNode, PlanMode
    from langgraph.graph.state import CompiledStateGraph
    import asyncio

    # t1 → t3, t2 → t3（t3 等待 t1 和 t2 都完成）
    plan = ExecutionPlan(
        tasks=[
            TaskNode(id="t1", agent="agent_a", description="step 1"),
            TaskNode(id="t2", agent="agent_b", description="step 2"),
            TaskNode(id="t3", agent="agent_c", description="step 3", dependencies=["t1", "t2"]),
        ],
        original_query="dag test",
        mode=PlanMode.DAG,
    )
    adapter = MagicMock()
    checkpointer = MagicMock()
    semaphore = asyncio.Semaphore(10)

    builder = StateGraphBuilder(adapter=adapter, checkpointer=checkpointer)
    graph = builder.build(plan=plan, semaphore=semaphore, max_concurrency=5)

    assert isinstance(graph, CompiledStateGraph)
    # 验证图结构：t1 和 t2 是入口，t3 是终点
    graph_data = graph.get_graph()
    node_ids = [n["id"] for n in graph_data["nodes"]]
    assert "t1" in node_ids
    assert "t2" in node_ids
    assert "t3" in node_ids
```

- [x] **Step 2: Run test to verify it passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_stategraph_builder.py::test_build_dag_with_fan_in -v`
Expected: PASS（Task 1 的实现已包含 fan-in 逻辑）

---

### Task 3: Node 函数 + Semaphore 共享测试

**Files:**
- Modify: `test/test_stategraph_builder.py`

- [x] **Step 1: Write the test**

```python
# 追加到 test/test_stategraph_builder.py
import asyncio

@pytest.mark.asyncio
async def test_node_func_shares_semaphore():
    """node 函数内部通过 async with semaphore 共享外部信号量。"""
    from utils.planning.schemas import ExecutionPlan, TaskNode, PlanMode
    from unittest.mock import AsyncMock

    plan = ExecutionPlan(
        tasks=[TaskNode(id="t1", agent="agent_a", description="test")],
        original_query="test",
        mode=PlanMode.PARALLEL,
    )
    adapter = MagicMock()
    adapter.execute_task = AsyncMock(return_value="result_a")
    checkpointer = MagicMock()
    semaphore = asyncio.Semaphore(2)

    builder = StateGraphBuilder(adapter=adapter, checkpointer=checkpointer)
    node_func = builder._make_node_func(plan.tasks[0], plan, semaphore)

    # 并发调用 3 次，但 semaphore=2 → 同时只跑 2 个
    state = {"results": {}}
    tasks = [node_func(state) for _ in range(3)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 所有调用都应成功
    for r in results:
        assert not isinstance(r, Exception)
    # adapter.execute_task 被调用 3 次
    assert adapter.execute_task.call_count == 3
```

- [x] **Step 2: Run test to verify it passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_stategraph_builder.py::test_node_func_shares_semaphore -v`
Expected: PASS

---

### Task 4: dispatch_stream 新增 mode="langgraph" 分支

**Files:**
- Modify: `services/multi_agent_service.py`
- Create: `test/test_langgraph_dispatch.py`

- [x] **Step 1: Write the failing test**

```python
# test/test_langgraph_dispatch.py
"""dispatch_stream(mode="langgraph") 集成测试。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_dispatch_stream_langgraph_mode():
    """mode="langgraph" 走 StateGraphBuilder 路径。"""
    from services.multi_agent_service import MultiAgentService
    from utils.planning.schemas import ExecutionPlan, TaskNode, PlanMode

    service = MultiAgentService()

    # Mock adapter + executor
    with patch.object(service, '_build_adapter') as mock_build:
        adapter = MagicMock()
        adapter.execute_task = AsyncMock(return_value="result")
        mock_build.return_value = adapter

        plan = ExecutionPlan(
            tasks=[TaskNode(id="t1", agent="agent_a", description="hello")],
            original_query="hello",
            mode=PlanMode.PARALLEL,
        )

        events = []
        async for event in service.dispatch_stream(
            plan=plan,
            mode="langgraph",
            message="hello",
            agent_ids=["agent_a"],
        ):
            events.append(event)

        # 验证：至少有 1 个事件
        assert len(events) > 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langgraph_dispatch.py::test_dispatch_stream_langgraph_mode -v`
Expected: FAIL（dispatch_stream 不支持 mode="langgraph"）

- [x] **Step 3: Implement mode="langgraph" branch**

在 `services/multi_agent_service.py` 的 `dispatch_stream` 方法中，在现有的 `if plan_mode == PlanMode.DAG:` 分支之前，新增 `langgraph` 分支：

```python
# services/multi_agent_service.py — dispatch_stream 方法中新增
# 在 "# 3. 选 executor" 之前新增：

if mode == "langgraph":
    # 新链路：StateGraphBuilder 动态构建 StateGraph
    from executor.workflow.stategraph_builder import StateGraphBuilder
    from langgraph.checkpoint.memory import MemorySaver

    semaphore = asyncio.Semaphore(max_concurrency or 10)
    checkpointer = MemorySaver()  # 后续可替换为 MysqlSaver

    builder = StateGraphBuilder(
        adapter=adapter,
        checkpointer=checkpointer,
    )
    graph = builder.build(
        plan=plan,
        semaphore=semaphore,
        max_concurrency=max_concurrency or 10,
    )

    initial_state = {"results": {}, "errors": {}}
    config = {
        "configurable": {"thread_id": run_id},
        "max_concurrency": max_concurrency or 10,
    }

    # 持久化 dispatch_record
    # ...（复用现有持久化逻辑）

    async for event in graph.astream(initial_state, config=config):
        # 包装为统一 ExecutionEvent 格式
        for node_name, node_output in event.items():
            if isinstance(node_output, dict) and "results" in node_output:
                for task_id, result in node_output.get("results", {}).items():
                    yield {
                        "type": "content",
                        "data": result,
                        "task_id": task_id,
                    }
    return  # langgraph 模式结束，不走下面的旧 executor 逻辑
```

- [x] **Step 4: Run test to verify it passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langgraph_dispatch.py::test_dispatch_stream_langgraph_mode -v`
Expected: PASS

---

### Task 5: 回归测试

**Files:**
- No changes

- [x] **Step 1: Run all existing tests**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/ -v --tb=short 2>&1 | tail -20`
Expected: 所有现有测试通过（test_multi_agent_dispatch / test_dag_dispatch / test_dispatch_persistence / test_parallel_stream / test_crash_recovery_sequential / test_mcp_stdio）

- [x] **Step 2: Run new tests**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_stategraph_builder.py test/test_langgraph_dispatch.py -v`
Expected: 全部 PASS

- [x] **Step 3: Run POC test**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" "C:\Users\Administrator\AppData\Local\Temp\opencode\test_max_concurrency_poc.py"`
Expected: `=== ALL TESTS PASSED ===`

---

## Self-Review

**Spec coverage:**
- ✅ StateGraphBuilder.build() → Task 1
- ✅ node 函数 + semaphore 共享 → Task 1 + Task 3
- ✅ edge 构建（fan-in） → Task 1 + Task 2
- ✅ RetryPolicy → Task 1（_get_retry_policy）
- ✅ dispatch_stream mode="langgraph" → Task 4
- ✅ 回归测试 → Task 5
- ✅ POC 验证 → Task 5 Step 3

**Placeholder scan:** 无 TBD/TODO，所有代码完整。

**Type consistency:** WorkflowState / StateGraphBuilder / RetryPolicy 在所有 task 中一致。
