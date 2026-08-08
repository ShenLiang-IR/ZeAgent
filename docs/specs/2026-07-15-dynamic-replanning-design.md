# 动态重规划设计 — 条件分支 + 动态插入（第一期）

> 日期：2026-07-15
> 方案：B（plan_executor 层重规划，StateGraphBuilder 不改）
> 第一期 scope：条件分支 + 动态插入（循环/人工干预后续期）

## 1. 背景

当前调度链路：LLM 规划 → ExecutionPlan（一次性 JSON）→ StateGraphBuilder.build（DAG）→ graph.astream。plan 一旦生成，执行中无法调整。

无法支持：①动态插入 task（执行后发现需追加 agent）②条件分支（task 失败走不同路径）③循环/迭代 ④人工干预。

## 2. 目标（第一期）

- **条件分支**：TaskNode 加 `condition` 字段；plan 执行完 → 检查 condition → 若触发，LLM 重规划走不同路径
- **动态插入**：TaskNode 加 `replan_on` 字段；plan 执行完 → 检查 replan_on → 若触发，LLM 重规划追加 task
- **降级安全**：condition/replan_on 未触发或 LLM 失败 → 不重规划
- **不破坏**：StateGraphBuilder 不改（纯 DAG）；无 condition/replan_on 的 plan 走现有逻辑

## 3. 非目标

- 循环/迭代 → 第二期
- 人工干预 → 第三期
- 不改 StateGraphBuilder（重规划在 plan_executor 层）

## 4. 架构（方案 B）

```
plan_executor._execute_with_workflow（扩展重规划）
  ├── 第 1 轮：StateGraphBuilder.build(plan) → graph.astream → 执行 + 消费事件
  ├── astream 完成 → _check_replan(plan, context)
  │   → 遍历 task 结果 → 检查 condition/replan_on
  │   → 若触发 → _replan（调 LLM 重规划）→ 生成新 plan
  ├── 第 2 轮：StateGraphBuilder.build(new_plan) → graph.astream → 执行 + 消费事件
  └── 最多 max_replan_rounds 轮（防无限循环）
      │
StateGraphBuilder（不改，纯 DAG）
```

**语义**：事后重规划（plan 执行完 → 检查结果 → 重规划 → 重新执行）。不中断当前 astream，而是"执行完一轮 → 根据结果决定是否重规划 + 重跑"。

**优势**：StateGraphBuilder 保持简单；重规划集中在 plan_executor。
**限制**：重规划轮次间重新 build（每轮新图）；条件分支是"事后走不同路径"而非"失败时立即切路径"。

## 5. 组件

### 5.1 TaskNode 加 condition/replan_on（schemas.py）

```python
condition: Optional[Dict[str, Any]] = Field(default=None,
    description="条件分支触发 {when: 'failed', replan: true}")
replan_on: Optional[str] = Field(default=None,
    description="重规划触发条件表达式，如 'result.contains(need_more_data)'")
```

### 5.2 plan_executor 加 _check_replan + _match_condition + _match_replan_on + _replan

- `_check_replan(plan, context)` → Optional[ExecutionPlan]：遍历 task 结果，检查 condition/replan_on，若触发调 `_replan`
- `_match_condition(condition, result)` → bool：检查 result 是否匹配（如 `when="failed"` → `result.startswith("error:")`）
- `_match_replan_on(expr, result)` → bool：解析表达式（如 `contains("keyword")` → `keyword in result`）
- `_replan(trigger_task, result, plan, context)` → Optional[ExecutionPlan]：调 `generate_execution_plan` 重规划，降级返回 None

### 5.3 _execute_with_workflow while 循环

```python
max_replan_rounds = get_config("agent.execution.replan.max_rounds", 3)
replan_round = 0
while replan_round < max_replan_rounds:
    graph = builder.build(plan, ...)
    async for event in graph.astream(...):
        yield ...  # 现有消费逻辑
    new_plan = await self._check_replan(plan, context, context_health)
    if new_plan is None:
        break
    plan = new_plan
    replan_round += 1
```

### 5.4 prompt 扩展

`utils/planning/prompts.py` 加 condition/replan_on 的规划指导。

## 6. 数据流

```
用户请求 → LLM 规划（含 condition/replan_on）
  → plan_executor._execute_with_workflow：
      第 1 轮：build(plan) → astream → 执行 + 消费
      → _check_replan → 若触发 → _replan（LLM 重规划）→ 新 plan
      → 第 2 轮：build(new_plan) → astream → 执行 + 消费
      → 最多 max_replan_rounds 轮
```

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| condition/replan_on 无匹配 | 不重规划 |
| LLM 重规划失败 | 降级（返回 None，用原结果） |
| max_replan_rounds 超限 | 停止（用最后一轮结果） |
| 新 plan task 失败 | on_failure（现有机制） |

## 8. 测试

| 测试 | 验证 |
|---|---|
| condition 触发重规划 | _check_replan 返回新 plan |
| replan_on 触发重规划 | _check_replan 返回新 plan |
| 无触发不重规划 | _check_replan 返回 None |
| LLM 失败降级 | _replan 返回 None |
| max_rounds 限制 | 超限停止 |
| 回归（无 condition/replan_on） | 走现有逻辑 |

## 9. 分阶段

| 阶段 | 内容 |
|---|---|
| 1 | TaskNode 加 condition/replan_on |
| 2 | _check_replan + _match_condition + _match_replan_on + _replan |
| 3 | _execute_with_workflow while 循环 + max_rounds |
| 4 | prompt 扩展 |

## 10. 文件变更

| 文件 | 类型 | 阶段 |
|---|---|---|
| `utils/planning/schemas.py` | 改 | 1 |
| `executor/plan_executor.py` | 改 | 2-3 |
| `utils/planning/prompts.py` | 改 | 4 |
| `test/test_dynamic_replanning.py` | 新建 | 2-3 |
| `config/agent_config.json` | 改（replan.max_rounds） | 3 |

## 11. 后续期

| 期 | 内容 |
|---|---|
| 第二期 | 循环/迭代 |
| 第三期 | 人工干预 |

## 12. 风险

- 重规划轮次间重新 build（丢弃执行状态，上游 context 通过 _replan 保留）
- LLM 质量差 → 降级安全
- max_replan_rounds=0 → 不重规划（零影响）
