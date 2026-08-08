# 动态重规划 实施计划 — 条件分支 + 动态插入（方案 B）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** plan_executor 层重规划——TaskNode 加 condition/replan_on，plan 执行完 → 检查结果 → LLM 重规划 → 重新执行

**Architecture:** 方案 B（StateGraphBuilder 不改，纯 DAG）；plan_executor._execute_with_workflow 加 while 循环（max_replan_rounds）+ _check_replan/_match_condition/_match_replan_on/_replan

**Tech Stack:** LangGraph StateGraph（不改）+ pydantic + Python 3.13

**Spec:** `docs/specs/2026-07-15-dynamic-replanning-design.md`（方案 B）

**Environment:** conda env `D:\ProgramData\miniconda3\envs\install_deb_refactor`，git repo，Python 3.13，pytest（asyncio_mode=auto, testpaths=test）

**Test command:** `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest <test_file> -v`

## Global Constraints

- TaskNode 是 pydantic BaseModel（schemas.py），加字段用 `Optional[Dict]/Optional[str] = None`
- StateGraphBuilder 不改（方案 B 核心决策）
- plan_executor._execute_with_workflow 是 async generator（yield SSE）
- 重规划在 plan_executor 层（不中断 astream，事后重规划：执行完一轮 → 检查 → 重规划 → 重跑）
- max_replan_rounds 默认 3（防无限循环），= 0 时不重规划

---

## File Structure

| File | Type | Responsibility |
|------|------|----------------|
| `utils/planning/schemas.py` | Modify | TaskNode 加 condition/replan_on |
| `executor/plan_executor.py` | Modify | _execute_with_workflow while 循环 + _check_replan/_match_*/_replan |
| `config/agent_config.json` | Modify | 加 agent.execution.replan.max_rounds |
| `test/test_dynamic_replanning.py` | Create | 重规划逻辑测试 |

---

### Task 1: TaskNode 加 condition/replan_on 字段

**Files:**
- Modify: `utils/planning/schemas.py`（TaskNode 类，约 L10-17）
- Test: `test/test_dynamic_replanning.py`

**Interfaces:**
- Produces: `TaskNode.condition: Optional[Dict] = None`、`TaskNode.replan_on: Optional[str] = None`

- [ ] **Step 1: Write the failing test**

```python
# test/test_dynamic_replanning.py
"""动态重规划测试（方案 B：plan_executor 层重规划）。"""
import pytest
from utils.planning.schemas import TaskNode, ExecutionPlan, PlanMode


def test_task_node_has_condition_and_replan_on_fields():
    """TaskNode 有 condition + replan_on 字段（默认 None）。"""
    task = TaskNode(id="t1", agent="a", description="test")
    assert hasattr(task, "condition"), "TaskNode 应有 condition 字段"
    assert hasattr(task, "replan_on"), "TaskNode 应有 replan_on 字段"
    assert task.condition is None
    assert task.replan_on is None


def test_task_node_condition_can_be_set():
    """condition 可设置为 {when/replan} dict。"""
    task = TaskNode(
        id="t1", agent="a", description="test",
        condition={"when": "failed", "replan": True},
    )
    assert task.condition["when"] == "failed"


def test_task_node_replan_on_can_be_set():
    """replan_on 可设置为表达式字符串。"""
    task = TaskNode(
        id="t1", agent="a", description="test",
        replan_on="result.contains('need_more_data')",
    )
    assert "need_more_data" in task.replan_on
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_dynamic_replanning.py -v -p no:warnings`
Expected: FAIL（TaskNode 无 condition/replan_on 字段）

- [ ] **Step 3: Add fields to TaskNode**

在 `utils/planning/schemas.py` 的 `TaskNode` 类，`on_failure` 后加：

```python
    on_failure: str = Field(default="stop", description="stop(), continue(), retry()")
    # 动态重规划：条件分支触发
    condition: Optional[Dict[str, Any]] = Field(default=None, description="条件分支 {when: 'failed', replan: true}")
    # 动态重规划：动态插入触发
    replan_on: Optional[str] = Field(default=None, description="重规划触发表达式，如 result.contains('keyword')")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_dynamic_replanning.py -v -p no:warnings`
Expected: 3 PASS

---

### Task 2: _match_condition + _match_replan_on（条件评估逻辑）

**Files:**
- Modify: `executor/plan_executor.py`（PlanExecutor 类，加方法）
- Test: `test/test_dynamic_replanning.py`（追加）

**Interfaces:**
- Consumes: `TaskNode.condition`/`TaskNode.replan_on` from Task 1
- Produces: `PlanExecutor._match_condition(condition, result) -> bool`、`PlanExecutor._match_replan_on(expr, result) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 test/test_dynamic_replanning.py
from unittest.mock import MagicMock


def _make_executor():
    from executor.plan_executor import PlanExecutor
    pe = PlanExecutor.__new__(PlanExecutor)
    return pe


def test_match_condition_failed():
    """condition when=failed → result 以 error: 开头时触发。"""
    pe = _make_executor()
    assert pe._match_condition({"when": "failed"}, "error: boom") is True
    assert pe._match_condition({"when": "failed"}, "success result") is False


def test_match_condition_contains():
    """condition when=contains + keyword → result 含 keyword 时触发。"""
    pe = _make_executor()
    assert pe._match_condition({"when": "contains", "keyword": "need_more"}, "result need_more data") is True
    assert pe._match_condition({"when": "contains", "keyword": "need_more"}, "all good") is False


def test_match_condition_no_when():
    """condition 无 when → 不触发。"""
    pe = _make_executor()
    assert pe._match_condition({}, "anything") is False


def test_match_replan_on_contains():
    """replan_on 表达式 result.contains('keyword') → result 含 keyword 时触发。"""
    pe = _make_executor()
    assert pe._match_replan_on("result.contains('need_data')", "need_data here") is True
    assert pe._match_replan_on("result.contains('need_data')", "all good") is False


def test_match_replan_on_no_contains():
    """replan_on 无 contains → 不触发。"""
    pe = _make_executor()
    assert pe._match_replan_on("some_other_expr", "anything") is False


def test_match_replan_on_none():
    """replan_on 为 None → 不触发。"""
    pe = _make_executor()
    assert pe._match_replan_on(None, "anything") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_dynamic_replanning.py -v -p no:warnings --tb=line`
Expected: FAIL（PlanExecutor 无 _match_condition/_match_replan_on 方法）

- [ ] **Step 3: Implement _match_condition + _match_replan_on**

在 `executor/plan_executor.py` 的 `PlanExecutor` 类中加：

```python
    def _match_condition(self, condition: dict, result: str) -> bool:
        """检查 result 是否匹配 condition 触发条件。"""
        if not condition:
            return False
        when = condition.get("when", "")
        if when == "failed" and result.startswith("error:"):
            return True
        if when == "contains":
            keyword = condition.get("keyword", "")
            return keyword in result if keyword else False
        return False

    def _match_replan_on(self, expr: str, result: str) -> bool:
        """检查 result 是否匹配 replan_on 表达式。"""
        if not expr:
            return False
        if "contains" in expr:
            import re
            match = re.search(r"contains\(['\"](.+?)['\"]\)", expr)
            if match:
                return match.group(1) in result
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_dynamic_replanning.py -v -p no:warnings`
Expected: 9 PASS（Task 1 的 3 + Task 2 的 6）

---

### Task 3: _replan + _check_replan（重规划逻辑）

**Files:**
- Modify: `executor/plan_executor.py`（加 _replan + _check_replan）
- Test: `test/test_dynamic_replanning.py`（追加）

**Interfaces:**
- Consumes: `_match_condition`/`_match_replan_on` from Task 2
- Produces: `PlanExecutor._replan(task, result, plan, context) -> Optional[ExecutionPlan]`、`PlanExecutor._check_replan(plan, context, context_health) -> Optional[ExecutionPlan]`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 test/test_dynamic_replanning.py
import asyncio


def test_check_replan_returns_none_when_no_trigger():
    """无 condition/replan_on 的 task → 不重规划。"""
    pe = _make_executor()
    pe.llm_model = None
    plan = ExecutionPlan(
        tasks=[TaskNode(id="t1", agent="a", description="test")],
        original_query="q", mode=PlanMode.SEQUENTIAL,
    )
    result = pe._check_replan(plan, {"t1": "success result"}, {})
    assert result is None, "无 condition/replan_on 应返回 None"


def test_check_replan_returns_none_when_condition_not_matched():
    """condition 未匹配 → 不重规划。"""
    pe = _make_executor()
    pe.llm_model = None
    plan = ExecutionPlan(
        tasks=[TaskNode(id="t1", agent="a", description="test", condition={"when": "failed"})],
        original_query="q", mode=PlanMode.SEQUENTIAL,
    )
    result = pe._check_replan(plan, {"t1": "success result"}, {})
    assert result is None, "condition 未匹配应返回 None"


def test_check_replan_triggers_on_condition_failed():
    """condition when=failed + result 以 error: 开头 → 触发重规划。"""
    pe = _make_executor()
    pe.llm_model = MagicMock()
    # mock _replan 返回新 plan
    new_plan = ExecutionPlan(
        tasks=[TaskNode(id="t2", agent="b", description="recovery")],
        original_query="q", mode=PlanMode.AGENT,
    )
    pe._replan = MagicMock(return_value=asyncio.coroutine(lambda: new_plan)())

    plan = ExecutionPlan(
        tasks=[TaskNode(id="t1", agent="a", description="test", condition={"when": "failed"})],
        original_query="q", mode=PlanMode.SEQUENTIAL,
    )
    result = asyncio.new_event_loop().run_until_complete(
        pe._check_replan(plan, {"t1": "error: boom"}, {})
    )
    assert result is not None, "condition 匹配应触发重规划"


def test_replan_returns_none_on_llm_failure():
    """_replan LLM 失败 → 返回 None（降级）。"""
    pe = _make_executor()
    pe.llm_model = None  # 无 LLM → _replan 降级
    plan = ExecutionPlan(
        tasks=[TaskNode(id="t1", agent="a", description="test")],
        original_query="q", mode=PlanMode.AGENT,
    )
    result = asyncio.new_event_loop().run_until_complete(
        pe._replan(plan.tasks[0], "error: boom", plan, {})
    )
    assert result is None, "LLM 失败应返回 None（降级）"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_dynamic_replanning.py -v -p no:warnings --tb=line`
Expected: FAIL（PlanExecutor 无 _replan/_check_replan 方法）

- [ ] **Step 3: Implement _replan + _check_replan**

在 `executor/plan_executor.py` 的 `PlanExecutor` 类中加（在 _match_replan_on 后）：

```python
    async def _replan(self, trigger_task, trigger_result: str, plan: ExecutionPlan, context: dict) -> Optional[ExecutionPlan]:
        """调 LLM 重规划，生成新 ExecutionPlan。降级返回 None。"""
        try:
            from utils.planning.generator import generate_execution_plan
            from utils.config import get_config_db
            if not self.llm_model:
                logger.warning("[PlanExecutor] 无 LLM，重规划降级")
                return None
            subagents = get_config_db().subagents.get_all(enabled_only=True) or []
            new_plan = await generate_execution_plan(
                user_input=f"上游 task '{trigger_task.id}' 结果：'{trigger_result[:500]}'。基于此结果，需要追加什么 agent 或走什么路径？",
                subagents=subagents,
                llm_model=self.llm_model,
            )
            logger.info(f"[PlanExecutor] 重规划成功：{len(new_plan.tasks)} tasks, mode={new_plan.mode}")
            return new_plan
        except Exception as e:
            logger.warning(f"[PlanExecutor] 重规划失败: {e}，继续用原结果")
            return None

    async def _check_replan(self, plan: ExecutionPlan, context: dict, context_health: dict) -> Optional[ExecutionPlan]:
        """检查 task 结果，若 condition/replan_on 触发，调 LLM 重规划。

        返回新 ExecutionPlan（需重规划）或 None（无需重规划）。
        """
        for task in plan.tasks:
            result = context.get(task.id, "")
            result_str = result if isinstance(result, str) else str(result)

            if task.condition and self._match_condition(task.condition, result_str):
                logger.info(f"[PlanExecutor] task {task.id} condition 触发重规划")
                return await self._replan(task, result_str, plan, context)

            if task.replan_on and self._match_replan_on(task.replan_on, result_str):
                logger.info(f"[PlanExecutor] task {task.id} replan_on 触发重规划")
                return await self._replan(task, result_str, plan, context)

        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_dynamic_replanning.py -v -p no:warnings`
Expected: 13 PASS（Task 1-3 全部）

---

### Task 4: _execute_with_workflow while 循环 + max_rounds 配置

**Files:**
- Modify: `executor/plan_executor.py`（_execute_with_workflow 加 while 循环）
- Modify: `config/agent_config.json`（加 replan.max_rounds）

**Interfaces:**
- Consumes: `_check_replan` from Task 3
- Produces: _execute_with_workflow 支持多轮重规划

- [ ] **Step 1: Add replan config to agent_config.json**

在 `config/agent_config.json` 的 `agent` 段加（或 `agent.execution` 子段）：

```json
        "replan": {
            "max_rounds": 3,
            "_comment_max_rounds": "动态重规划最大轮次（0=禁用重规划，默认 3）"
        },
```

- [ ] **Step 2: Add while loop to _execute_with_workflow**

在 `executor/plan_executor.py` 的 `_execute_with_workflow` 方法中，把现有的 `graph.astream` 逻辑包进 while 循环：

在 `config = attach_callbacks(...)` 后、`try:` 前加：

```python
        from utils.config import get_config as _get_config
        max_replan_rounds = _get_config("agent.execution.replan.max_rounds", 3)
        replan_round = 0

        while replan_round <= max_replan_rounds:
```

把现有的 `try: async for event in graph.astream(...)` 缩进进 while 循环。在 while 循环末尾（astream 消费完 + updates 兜底后）加：

```python
            # 动态重规划检查
            if max_replan_rounds > 0:
                new_plan = await self._check_replan(plan, context, context_health)
                if new_plan is None:
                    break  # 无需重规划
                plan = new_plan
                replan_round += 1
                logger.info(f"[PlanExecutor] 重规划第 {replan_round} 轮")
                # 重建图（新 plan）
                graph = builder.build(
                    plan=plan, semaphore=semaphore,
                    deep_thinking=deep_thinking, stream_mode="stream",
                )
            else:
                break
```

- [ ] **Step 3: Run regression**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/ -v -p no:warnings --tb=line`
Expected: 全部 PASS（含 test_dynamic_replanning + 现有测试）。max_rounds=0 或无 condition → 不重规划（现有逻辑）。

---

### Task 5: 回归测试

**Files:**
- No changes

- [ ] **Step 1: Run test/ full regression**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/ -v -p no:warnings --tb=line`
Expected: 全部 PASS

- [ ] **Step 2: Verify config JSON valid**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -c "import json; json.load(open('config/agent_config.json', encoding='utf-8')); print('JSON OK')"`
Expected: `JSON OK`

---

## Self-Review

**Spec coverage（方案 B §5.1/§5.2/§5.3/§9）：**
- ✅ TaskNode 加 condition/replan_on（§5.1）→ Task 1
- ✅ _match_condition + _match_replan_on（§5.2）→ Task 2
- ✅ _replan + _check_replan（§5.2）→ Task 3
- ✅ _execute_with_workflow while 循环 + max_rounds（§5.3）→ Task 4
- ✅ 回归（§8）→ Task 5

**Placeholder scan:** 无 TBD/TODO，所有步骤含完整测试代码 + 实现代码 + 确切命令。

**Type consistency:** `TaskNode.condition: Optional[Dict]`、`TaskNode.replan_on: Optional[str]`、`_match_condition(condition: dict, result: str) -> bool`、`_match_replan_on(expr: str, result: str) -> bool`、`_replan(...) -> Optional[ExecutionPlan]`、`_check_replan(...) -> Optional[ExecutionPlan]` 在所有 task 一致。
