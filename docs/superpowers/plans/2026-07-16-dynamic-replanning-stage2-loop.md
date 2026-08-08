# 动态重规划第二期 — task 级条件循环 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** TaskNode 加 loop 配置，task 级条件循环（until 满足或 max_iterations 超限停止），复用第一期 while + _match_replan_on。

**Spec:** `docs/superpowers/specs/2026-07-16-dynamic-replanning-stage2-loop-design.md`

**Test command:** `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest <test> -v -p no:warnings`

## Global Constraints
- 第一期 condition/replan_on 逻辑不改（loop 是新增分支）
- `until` 复用 `_match_replan_on` 的 `contains('keyword')` 语法
- `loop=None` 不循环（兼容旧行为）
- `max_iterations=0` 禁用循环（回退开关）
- 先查 loop（无 LLM）再查 replan（调 LLM）

---

### Task 1: TaskNode 加 loop 字段 + 单元测试

**Files:** `utils/planning/schemas.py`, `test/test_replanning_loop.py`

- [ ] **Step 1: Write failing test**

```python
# test/test_replanning_loop.py
"""动态重规划第二期：task 级条件循环测试（方案 A）。"""
from utils.planning.schemas import TaskNode, ExecutionPlan, PlanMode
from executor.plan_executor import PlanExecutor


def _make_executor():
    return PlanExecutor.__new__(PlanExecutor)


def test_task_node_has_loop_field():
    """TaskNode 有 loop 字段，默认 None。"""
    task = TaskNode(id="t1", agent="a", description="test")
    assert hasattr(task, "loop")
    assert task.loop is None


def test_task_node_loop_can_be_set():
    """loop 可设置为 {max_iterations, until}。"""
    task = TaskNode(id="t1", agent="a", description="test",
                    loop={"max_iterations": 3, "until": "result.contains('done')"})
    assert task.loop["max_iterations"] == 3
    assert "done" in task.loop["until"]


def test_check_loop_until_not_satisfied():
    """until 未满足（result 不含 keyword）→ 返回 True（需循环）。"""
    pe = _make_executor()
    plan = ExecutionPlan(
        tasks=[TaskNode(id="t1", agent="a", description="test",
                        loop={"max_iterations": 3, "until": "result.contains('done')"})],
        original_query="q", mode=PlanMode.AGENT,
    )
    assert pe._check_loop(plan, {"t1": "not done yet"}) is True


def test_check_loop_until_satisfied():
    """until 已满足（result 含 keyword）→ 返回 False。"""
    pe = _make_executor()
    plan = ExecutionPlan(
        tasks=[TaskNode(id="t1", agent="a", description="test",
                        loop={"max_iterations": 3, "until": "result.contains('done')"})],
        original_query="q", mode=PlanMode.AGENT,
    )
    assert pe._check_loop(plan, {"t1": "work done"}) is False


def test_check_loop_no_loop():
    """task 无 loop → 返回 False。"""
    pe = _make_executor()
    plan = ExecutionPlan(
        tasks=[TaskNode(id="t1", agent="a", description="test")],
        original_query="q", mode=PlanMode.AGENT,
    )
    assert pe._check_loop(plan, {"t1": "result"}) is False


def test_check_loop_empty_until():
    """loop.until 为空 → 返回 False（不循环）。"""
    pe = _make_executor()
    plan = ExecutionPlan(
        tasks=[TaskNode(id="t1", agent="a", description="test",
                        loop={"max_iterations": 3, "until": ""})],
        original_query="q", mode=PlanMode.AGENT,
    )
    assert pe._check_loop(plan, {"t1": "result"}) is False
```

- [ ] **Step 2: Run to verify RED**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_replanning_loop.py -v -p no:warnings --tb=line`
Expected: FAIL（TaskNode 无 loop 字段 / PlanExecutor 无 _check_loop）

- [ ] **Step 3: Add loop field to TaskNode**

`utils/planning/schemas.py`，TaskNode 类，`replan_on` 后加：

```python
    replan_on: Optional[str] = Field(default=None, description="重规划触发表达式，如 result.contains('keyword')")
    # 动态重规划第二期：task 级条件循环
    loop: Optional[Dict[str, Any]] = Field(default=None, description="循环配置 {max_iterations: 3, until: \"result.contains('keyword')\"}")
```

- [ ] **Step 4: Implement _check_loop**

`executor/plan_executor.py`，PlanExecutor 类，`_check_replan` 前加：

```python
    def _check_loop(self, plan: ExecutionPlan, context: dict) -> bool:
        """检查是否有 task 的 loop.until 未满足，需循环重跑。

        Returns: True 若需循环（重跑同 plan），False 若无需循环。
        """
        for task in plan.tasks:
            if not task.loop:
                continue
            until = task.loop.get("until", "")
            result = context.get(task.id, "")
            result_str = result if isinstance(result, str) else str(result)
            if until and not self._match_replan_on(until, result_str):
                logger.info(f"[PlanExecutor] task {task.id} loop until 未满足，触发循环重跑")
                return True
        return False
```

- [ ] **Step 5: Run test to verify GREEN**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_replanning_loop.py -v -p no:warnings`
Expected: 6 PASS

- [ ] **Step 6: Commit**

```bash
git add utils/planning/schemas.py executor/plan_executor.py test/test_replanning_loop.py
git commit -m "feat(replanning): TaskNode loop field + _check_loop (stage2, TDD GREEN)"
```

---

### Task 2: while 循环扩展 + config

**Files:** `executor/plan_executor.py:442-542`, `config/agent_config.json`

- [ ] **Step 1: Add loop config**

`config/agent_config.json` 的 `agent.execution` 段（replan 后）加：

```json
        "loop": {
            "max_iterations": 3,
            "_comment_max_iterations": "task 级循环最大迭代次数（0=禁用循环，默认 3）"
        },
```

- [ ] **Step 2: Extend while loop**

`executor/plan_executor.py`，`_execute_with_workflow`，while 前（444 附近）加 loop 变量：

```python
        max_replan_rounds = get_config("agent.execution.replan.max_rounds", 3)
        replan_round = 0
        max_loop = get_config("agent.execution.loop.max_iterations", 3)
        loop_round = 0
```

while 条件改为：
```python
        while replan_round <= max_replan_rounds or loop_round < max_loop:
```

while 内，astream 消费后（528 附近），现有 `_check_replan` 前插入 loop 检查：

```python
                # task 级循环检查（无 LLM，重跑同 plan）
                if max_loop > 0 and self._check_loop(plan, context):
                    if loop_round < max_loop:
                        loop_round += 1
                        logger.info(f"[PlanExecutor] 循环第 {loop_round} 轮（task loop）")
                        graph = builder.build(
                            plan=plan, semaphore=semaphore,
                            deep_thinking=deep_thinking, stream_mode="stream",
                        )
                        continue
                    else:
                        logger.warning(f"[PlanExecutor] 循环超 max_iterations={max_loop}，停止")
                        break
                # plan 级重规划检查（调 LLM，第一期）
                if max_replan_rounds > 0:
                    new_plan = await self._check_replan(plan, context, context_health)
                    if new_plan is None:
                        break
                    plan = new_plan
                    replan_round += 1
                    ...重建图（现有）...
                else:
                    break
```

- [ ] **Step 3: Verify JSON valid + import**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -c "import json; c=json.load(open('config/agent_config.json',encoding='utf-8')); print('JSON OK', c['agent']['execution']['loop'])"`
Expected: `JSON OK {'max_iterations': 3, ...}`

- [ ] **Step 4: Run regression**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_replanning_loop.py test/test_dynamic_replanning.py test/test_context_truncation.py test/test_thinking_cleanup.py test/test_multi_agent_stream.py -v -p no:warnings --tb=line`
Expected: 全 PASS（loop 是新增，不改第一期 condition/replan_on）

- [ ] **Step 5: Commit**

```bash
git add executor/plan_executor.py config/agent_config.json
git commit -m "feat(replanning): while loop extension - check loop before replan (stage2)"
```

---

## Self-Review

**Spec coverage:** §5.1 loop 字段 → Task 1 Step 3；§5.2 _check_loop → Task 1 Step 4；§5.3 while 扩展 → Task 2 Step 2；§5.4 config → Task 2 Step 1。✅
**Placeholder scan:** 无 TBD，所有 step 含完整代码 + 命令。✅
**Type consistency:** `loop: Optional[Dict]`、`_check_loop(plan, context) -> bool`、`_match_replan_on(expr, result) -> bool` 一致。✅
