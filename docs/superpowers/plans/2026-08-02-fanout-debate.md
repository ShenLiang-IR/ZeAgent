# 中心汇总 + 辩论对抗 实现计划

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task.

**Goal:** 支持指定汇总 Agent 合成并行结果 + DEBATE 模式实现多 Agent 辩论对抗。

**Architecture:** 中心汇总在 `_summarize_results` 中检测最后 task 是否为汇总角色；辩论复用 DYNAMIC 的迭代框架，新增 DEBATE PlanMode。

**Tech Stack:** Python 3.13+ / FastAPI / LangGraph / Pydantic v2

## Global Constraints

- 不改 Planner 缓存逻辑
- 不影响现有 SEQUENTIAL/PARALLEL/DAG/DYNAMIC 行为
- 汇总 Agent 检测为纯增强，失败回退系统 LLM

---

### Task 1: PlanMode.DEBATE + _is_synthesizer_task

**Files:**
- Modify: `utils/planning/schemas.py:4-10`
- Modify: `executor/plan_executor.py:797-835`（在 `_summarize_results` 方法内加检测）
- Create: `test/test_fanout_debate.py`

**Interfaces:**
- Produces: `PlanMode.DEBATE = "debate"`
- Produces: `plan_executor._is_synthesizer_task(plan, context) -> bool`
- Produces: `_summarize_results` 增加汇总 Agent 检测分支

- [ ] **Step 1: 写测试**

```python
# test/test_fanout_debate.py
from utils.planning.schemas import ExecutionPlan, TaskNode, PlanMode

def test_is_synthesizer_last_task_deps_all_others():
    """最后一个 task 依赖所有前序 task → 是汇总 Agent。"""
    plan = ExecutionPlan(
        mode=PlanMode.PARALLEL,
        tasks=[
            TaskNode(id="t1", agent="a", description="x"),
            TaskNode(id="t2", agent="b", description="y"),
            TaskNode(id="t3", agent="sum", description="汇总", dependencies=["t1", "t2"]),
        ],
        original_query="q"
    )
    from executor.plan_executor import PlanExecutor
    pe = PlanExecutor(session_id="test")
    assert pe._is_synthesizer_task(plan, {"t1": "a", "t2": "b", "t3": "c"}) is True

def test_is_synthesizer_not_all_deps():
    """最后 task 只依赖部分前序 → 不是汇总。"""
    plan = ExecutionPlan(
        mode=PlanMode.PARALLEL,
        tasks=[
            TaskNode(id="t1", agent="a", description="x"),
            TaskNode(id="t2", agent="b", description="y", dependencies=["t1"]),
        ],
        original_query="q"
    )
    from executor.plan_executor import PlanExecutor
    pe = PlanExecutor(session_id="test")
    assert pe._is_synthesizer_task(plan, {"t1": "a", "t2": "b"}) is False

def test_is_synthesizer_no_deps():
    """无依赖 → 不是汇总。"""
    plan = ExecutionPlan(
        mode=PlanMode.PARALLEL,
        tasks=[TaskNode(id="t1", agent="a", description="x")],
        original_query="q"
    )
    from executor.plan_executor import PlanExecutor
    pe = PlanExecutor(session_id="test")
    assert pe._is_synthesizer_task(plan, {"t1": "a"}) is False
```

- [ ] **Step 2: 验证测试失败**

```bash
pytest test/test_fanout_debate.py -v
```
Expected: FAIL with `AttributeError: 'PlanExecutor' object has no attribute '_is_synthesizer_task'`

- [ ] **Step 3: 添加 PlanMode.DEBATE + _is_synthesizer_task**

```python
# utils/planning/schemas.py — 在 PlanMode 中加一行
class PlanMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    DAG = "dag"
    DIRECT = "direct"
    AGENT = "agent"
    DYNAMIC = "dynamic"
    DEBATE = "debate"  # 多 Agent 辩论对抗
```

```python
# executor/plan_executor.py — 在 _summarize_results 之前插入
def _is_synthesizer_task(self, plan: ExecutionPlan, context: dict) -> bool:
    """检测 plan 最后一个 task 是否为汇总 Agent。
    条件：最后 task 的 dependencies 覆盖所有前序 task id。
    """
    if not plan.tasks or len(plan.tasks) < 2:
        return False
    last = plan.tasks[-1]
    if not last.dependencies:
        return False
    other_ids = {t.id for t in plan.tasks[:-1]}
    return other_ids and other_ids.issubset(set(last.dependencies))
```

```python
# executor/plan_executor.py — 在 _summarize_results 开头（L800 前）插入
# 在 "if plan.mode == PlanMode.DIRECT:" 之前插入：
# 汇总 Agent 检测：最后 task 依赖全量前序 → 直接返回其输出
if (plan.mode in (PlanMode.PARALLEL, PlanMode.SEQUENTIAL, PlanMode.DAG)
        and self._is_synthesizer_task(plan, context)):
    last = plan.tasks[-1]
    if last.id in context and not is_error_result(context[last.id]):
        logger.info(f"[_summarize_results] 汇总 Agent: {last.agent} → 直接用其输出")
        return context[last.id]
```

- [ ] **Step 4: 验证测试通过**

```bash
pytest test/test_fanout_debate.py -v
```
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add test/test_fanout_debate.py utils/planning/schemas.py executor/plan_executor.py
git commit -m "feat: add PlanMode.DEBATE + _is_synthesizer_task for fanout-collect"
```

---

### Task 2: Planner prompt 增强（汇总 + 辩论）

**Files:**
- Modify: `utils/planning/prompts.py:52-97`（`_get_base_planning_prompt`）

- [ ] **Step 1: 增强 Planner prompt**

在 `_get_base_planning_prompt` 的 mode 选择规则后追加：

```python
# 在 "## 执行模式（mode）选择规则" 段末尾、## 任务分解 段之前追加：

- debate：当用户明确要求正反方观点、利弊权衡、多方视角对抗分析时使用。首轮至少 2 个论证 task（PARALLEL）+ 1 个裁判 task（依赖所有论证 task）。裁判输出含共识点/分歧点/建议下一轮聚焦后，系统自动 replan 进入第 2 轮（最多 2 轮）。详见辩论模式规则。

## 汇总规则
- 如用户要求"综合""汇总""总结"多个分析结果，最后一个 task 应是专门的汇总 agent
- 汇总 agent 的 dependencies 必须包含所有前序 task id
- 系统自动用该 agent 的输出作为最终答案，无需额外标注
```

- [ ] **Step 2: 验证编译**

```bash
"D:/ProgramData/miniconda3/envs/install_deb_refactor/python.exe" -c "from utils.planning.prompts import get_planning_system_prompt; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add utils/planning/prompts.py
git commit -m "feat: add synthesizer and debate rules to Planner prompt"
```

---

### Task 3: DEBATE 模式执行逻辑

**Files:**
- Modify: `executor/plan_executor.py:151-181`（`_prepare_plan` 的模式分发）
- Modify: `executor/plan_executor.py:293-301`（thinking 文本的 mode 映射）

- [ ] **Step 1: 在 execute 和 mode 显示中添加 DEBATE**

```python
# executor/plan_executor.py — 在 _prepare_plan 中（约 L151），AGENT 模式之前：
# 辩论模式：系统自动生成正反方+裁判 plan，非 Planner 路由。
# 当前先由 Planner prompt 路由到 DEBATE，后续可加自动检测。
pass  # DEBATE 由 Planner 直接输出 JSON plan，无需 special handling
```

```python
# executor/plan_executor.py — L293-301，mode 友好名称映射：
PlanMode.DEBATE: "辩论对抗",
```

```python
# executor/plan_executor.py — 在 execute() 和 execute_stream() 的 mode 分发中：
# L376-402 之间，添加 DEBATE 分支（复用 DYNAMIC 的 _execute_dynamic）：
if plan.mode == PlanMode.DEBATE:
    logger.info(f"[PlanExecutor] DEBATE 模式，复用 DYNAMIC 迭代框架（max_rounds=2）")
    async for event in self._execute_dynamic(plan, context, event_sender, deep_thinking, context_health):
        yield event
```

**注意**：`_execute_dynamic` 已实现执行→观察→replan 的迭代逻辑，DEBATE 完全复用。Planner prompt 通过 `_get_base_planning_prompt` 中的辩论规则指导 Planner 生成合适的 plan。

- [ ] **Step 2: 验证编译 + 导入**

```bash
"D:/ProgramData/miniconda3/envs/install_deb_refactor/python.exe" -c "
from utils.planning.schemas import PlanMode
assert hasattr(PlanMode, 'DEBATE')
print('OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add executor/plan_executor.py
git commit -m "feat: add DEBATE mode support via DYNAMIC iteration framework"
```

---

### Task 4: Config + 端到端验证

**Files:**
- Modify: `config/agent_config.json`（`agent.execution` 段）

- [ ] **Step 1: 添加 debate 配置**

```json
# 在 "agent.execution.replan" 段附近添加：
"debate": {
    "max_rounds": 2,
    "_comment_max_rounds": "辩论最大轮数（正反方各一轮 + 裁判裁定）"
},
```

- [ ] **Step 2: 全量测试**

```bash
pytest test/test_fanout_debate.py test/test_remote_a2a_sdk.py -v
```

Expected: 19 PASS（3 fanout + 16 a2a-sdk）

- [ ] **Step 3: Commit**

```bash
git add config/agent_config.json test/test_fanout_debate.py
git commit -m "chore: add debate config + full test verification"
```
