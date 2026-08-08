# 动态重规划第二期 — task 级条件循环（方案 A）

> 日期：2026-07-16
> 方案：A（TaskNode 加 `loop` 配置，复用第一期 while 循环 + `_match_replan_on` 表达式）
> 前置：第一期 condition/replan_on 已实施（`schemas:19/21` + `plan_executor:341/384/446`）
> 触及模块：`utils/planning/schemas.py`、`executor/plan_executor.py`

---

## 1. 背景

### 1.1 第一期现状

- `TaskNode.condition`（条件分支）+ `replan_on`（动态插入）：事后检查 → `_replan`（调 LLM）→ 新 plan → 重跑（`plan_executor:384/528-542`）
- `_execute_with_workflow` while 循环（`plan_executor:446`）：`while replan_round <= max_replan_rounds`，每轮 astream → `_check_replan` → 若触发重规划 → 重建图 → 重跑
- 语义：**事后重规划**（执行完→检查→调 LLM 生成新 plan→重跑整图）

### 1.2 第二期需求

支持**迭代式工作流**：task 重复执行直到质量达标。第一期 condition/replan_on 是"调 LLM 生成新 plan"，不适合"同一 task 反复跑直到满足"的循环场景（每次都调 LLM 重规划开销大且 plan 会变）。

需要：**无 LLM 的 task 级循环**——task 完成后检查 `loop.until` 条件，未满足则重跑同 plan（不调 LLM），用上轮结果作 context。

## 2. 目标

- TaskNode 加 `loop` 配置（`max_iterations` + `until`）
- `_check_loop`：检查 task 的 `loop.until`，未满足则触发循环重跑（不调 LLM）
- while 循环扩展：先查 loop（task 级循环，不调 LLM），再查 condition/replan_on（plan 级重规划，调 LLM）
- `max_iterations` 防无限循环（默认 3）
- 复用第一期 `_match_replan_on` 的 `contains(...)` 表达式解析 `until`

## 3. 非目标

- plan 级循环（方案 B，整个 plan 重复——本期不做）
- 新 PlanMode.LOOP（方案 C——不做，LLM 需懂新模式）
- 循环时调 LLM 重新规划（那是 condition/replan_on 的职责，loop 是"重跑同 plan"）
- 改 StateGraphBuilder（loop 在 plan_executor 层）

## 4. 架构

```
_execute_with_workflow while 循环（扩展）：
  每轮：
    1. build graph → astream → 执行 + 消费事件
    2. astream 完成后：
       a. _check_loop(plan, context) → 检查 task.loop.until
          ├─ 有 loop 且 until 未满足 且 loop_round < max_iterations
          │   → loop_round++; 重建图（plan 不变，context 保留上轮结果）; continue（重跑同 plan）
          └─ 无 loop 或 until 已满足 或 超限
              → 进入 b
       b. _check_replan(plan, context) → 检查 condition/replan_on（第一期）
          ├─ 触发 → _replan（调 LLM）→ 新 plan; replan_round++; 重建图; continue
          └─ 未触发 → break
```

**语义区分**：
- `loop`：**无 LLM**，重跑同 plan（task 级循环，until 驱动）
- `condition`/`replan_on`：**调 LLM**，生成新 plan（plan 级重规划）

## 5. 组件设计

### 5.1 TaskNode 加 loop 字段（schemas.py）

```python
# utils/planning/schemas.py，TaskNode 类，replan_on 后加：
loop: Optional[Dict[str, Any]] = Field(default=None,
    description="循环配置 {max_iterations: 3, until: \"result.contains('质量达标')\"}。until 未满足时重跑同 plan，max_iterations 防无限")
```

`until` 复用 `_match_replan_on` 的 `contains('keyword')` 语法。

### 5.2 `_check_loop`（plan_executor.py，新增）

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
        # until 未满足 → 需循环（_match_replan_on 返回 False 表示未匹配=未满足）
        if until and not self._match_replan_on(until, result_str):
            logger.info(f"[PlanExecutor] task {task.id} loop until 未满足，触发循环重跑")
            return True
    return False
```

### 5.3 while 循环扩展（plan_executor.py:446-542）

现有 while（528-542）：
```python
# 动态重规划检查
if max_replan_rounds > 0:
    new_plan = await self._check_replan(plan, context, context_health)
    if new_plan is None:
        break
    plan = new_plan
    replan_round += 1
    ...重建图...
else:
    break
```

扩展为（先查 loop，再查 replan）：
```python
# task 级循环检查（无 LLM，重跑同 plan）
max_loop = get_config("agent.execution.loop.max_iterations", 3)
if max_loop > 0 and self._check_loop(plan, context):
    if loop_round < max_loop:
        loop_round += 1
        logger.info(f"[PlanExecutor] 循环第 {loop_round} 轮（task loop）")
        graph = builder.build(
            plan=plan, semaphore=semaphore,
            deep_thinking=deep_thinking, stream_mode="stream",
        )
        continue  # 重跑同 plan（context 保留上轮结果）
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
    ...重建图...
else:
    break
```

while 循环条件改为 `while replan_round <= max_replan_rounds or loop_round <= max_loop`（loop 和 replan 任一未超限都可继续）。

新增变量（while 前）：
```python
max_loop = get_config("agent.execution.loop.max_iterations", 3)
loop_round = 0
```

### 5.4 config

`config/agent_config.json` 的 `agent.execution` 段加：
```json
"loop": {
    "max_iterations": 3,
    "_comment_max_iterations": "task 级循环最大迭代次数（0=禁用循环，默认 3）"
}
```

## 6. 数据流

```
plan 含 task A（loop: {max_iterations:3, until:"result.contains(质量达标)"}）
  第 1 轮：build → astream → A 执行，result="部分完成"
    → _check_loop: A.loop.until="result.contains(质量达标)"，result 不含"质量达标" → True（需循环）
    → loop_round=1; 重建图（plan 不变，context[A]="部分完成"）; continue
  第 2 轮：astream → A 执行（context 含上轮"部分完成"），result="质量达标 完成"
    → _check_loop: result 含"质量达标" → until 满足 → False（无需循环）
    → _check_replan: 无 condition/replan_on → None → break
```

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| `loop` 为 None | 不循环（兼容旧行为） |
| `loop.until` 为空 | 不循环 |
| `loop.max_iterations` 未设 | 用 config `agent.execution.loop.max_iterations`（默认 3） |
| 循环超 max_iterations | 停止（用最后一轮结果） |
| 循环 + 重规划都触发 | 先 loop（无 LLM），loop 满足后再 replan |
| config `max_iterations=0` | 禁用循环（零影响） |

## 8. 测试策略

### 8.1 单元测试 `test/test_replanning_loop.py`（新建）

| 测试 | 验证 |
|---|---|
| TaskNode 有 loop 字段 | `TaskNode(loop={...})` 不报错，默认 None |
| `_check_loop` until 未满足 | result 不含 keyword → 返回 True |
| `_check_loop` until 已满足 | result 含 keyword → 返回 False |
| `_check_loop` 无 loop | task 无 loop → 返回 False |
| `_check_loop` until 为空 | loop.until="" → 返回 False |
| `_check_loop` 超限 | loop_round >= max → 不循环 |

### 8.2 回归

- `test_dynamic_replanning.py`（第一期 13/13）必须仍通过（loop 是新增，不改第一期 condition/replan_on 逻辑）
- `test_multi_agent_stream.py` + `test_context_truncation.py` + `test_thinking_cleanup.py`

**测试命令**：
```
"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_replanning_loop.py test/test_dynamic_replanning.py test/test_context_truncation.py test/test_thinking_cleanup.py test/test_multi_agent_stream.py -v -p no:warnings
```

## 9. 分阶段

| 阶段 | 内容 | 验证 |
|---|---|---|
| 1 | TaskNode 加 loop 字段 + 写测试（RED） | `_check_loop` 不存在 |
| 2 | 实现 `_check_loop`（GREEN） | 单元测试 PASS |
| 3 | while 循环扩展（先查 loop 再查 replan）+ config | 回归 PASS |
| 4 | 回归 | 全部 PASS |

## 10. 文件变更清单

| 文件 | 变更类型 | 阶段 |
|---|---|---|
| `utils/planning/schemas.py` | 改（TaskNode 加 loop 字段） | 1 |
| `executor/plan_executor.py` | 改（加 `_check_loop` + while 扩展） | 2-3 |
| `config/agent_config.json` | 改（加 loop.max_iterations） | 3 |
| `test/test_replanning_loop.py` | 新建 | 1 |

## 11. 风险与回退

| 风险 | 等级 | 缓解 |
|---|---|---|
| 循环无限 | 低 | max_iterations 防无限（默认 3，0 禁用） |
| 循环 + 重规划语义混淆 | 低 | 先 loop（无 LLM）再 replan（调 LLM），分支清晰 |
| 循环时 context 累积 | 中 | 上轮 result 作 context（与第一期重规划同理）；项3 截断已控 prompt 体积 |
| while 条件改错 | 中 | `replan_round <= max_replan OR loop_round <= max_loop`，任一未超限可继续 |

**回退**：`agent.execution.loop.max_iterations=0` 禁用循环；TaskNode.loop=None 不循环（兼容旧行为）。

## 12. 后续（非本期）

- 第三期：人工干预（loop/replan 触发时人工审核）
- plan 级循环（方案 B）若 task 级循环不够
- loop 时 context 累积的进一步压缩（项3 已部分解决）
