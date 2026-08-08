# 中心汇总（Fan-out+Collect）+ 辩论对抗（Debate）设计文档

创建时间：2026-08-02
状态：设计待审查
关联：A2A 远程适配层（已完成）

## 一、背景与目标

### 现状
- PLANNING 模式支持 Planner 自动选择 PARALLEL/SEQUENTIAL 等多 Agent 协作模式
- 任务执行结果通过 `context` dict 传递（`context[task_id] = result`）
- 最终汇总由 `_summarize_results` 用**系统 LLM** 生成，不能指定汇总 Agent
- DYNAMIC 模式支持迭代规划（执行→观察→再规划），但无专门的辩论支持

### 目标
1. **中心汇总**：支持指定一个"汇总 Agent"负责合成多个并行 Agent 的结果
2. **辩论对抗**：支持多 Agent 对同一问题给出不同观点→互相批判→达成共识

### 非目标（YAGNI）
- 不做多轮投票机制
- 不做 Agent 间实时消息传递（已有 Mailbox，不在此次范围）
- 不做辩论的实时流式展示（前端时间轴已覆盖）

---

## 二、中心汇总（Fan-out + Collect）

### 2.1 触发条件

Plan 中最后一个 task 的 `dependencies` 包含所有前序 task → 自动识别为"汇总 Agent"。

```json
{
  "mode": "parallel",
  "tasks": [
    {"id": "t1", "agent": "研究员", "description": "研究A", "dependencies": []},
    {"id": "t2", "agent": "分析师", "description": "研究B", "dependencies": []},
    {"id": "t3", "agent": "汇总专家", "description": "综合t1和t2结果",
     "dependencies": ["t1", "t2"]}   ← 识别为汇总 Agent
  ]
}
```

### 2.2 执行流程

```
parallel execute: t1, t2 同时跑
    ↓
context = {"t1": "研究A结果", "t2": "研究B结果"}
    ↓
sequential execute: t3 执行（已有 t1, t2 结果作为上下文）
    ↓
_synthesize_results 检测到 t3 依赖所有前序 task
    ↓
跳过系统 LLM 汇总 → 直接用 t3 的 output 作为最终答案
```

### 2.3 代码改动

**`executor/plan_executor.py`**：

```python
def _is_synthesizer_task(self, plan: ExecutionPlan, context: dict) -> bool:
    """检测 plan 最后一个 task 是否为汇总 Agent。"""
    if not plan.tasks:
        return False
    last = plan.tasks[-1]
    if not last.dependencies:
        return False
    # 汇总 task 的依赖应覆盖所有前序 task
    other_ids = {t.id for t in plan.tasks[:-1] if t.id != last.id}
    return other_ids and other_ids.issubset(set(last.dependencies))

async def _summarize_results(self, plan, context, context_health):
    # 汇总 Agent 检测
    if self._is_synthesizer_task(plan, context):
        last = plan.tasks[-1]
        if last.id in context and not is_error_result(context[last.id]):
            return context[last.id]
    # 回退：系统 LLM 汇总（现有逻辑，不变）
```

**`utils/planning/prompts.py`**：增加 Planner 提示：

```
- 汇总模式：如用户要求综合/总结多个分析结果，最后一个 task 应是"汇总" agent，
  其 dependencies 包含所有前序 task id。系统自动用该 agent 的输出作为最终答案。
```

---

## 三、辩论对抗（Debate）

### 3.1 新增 PlanMode

```python
class PlanMode(str, Enum):
    ...
    DEBATE = "debate"  # 多 Agent 辩论对抗
```

### 3.2 辩论流程

```
第1轮：
  Planner 生成 debate plan:
    task_pro（正方）, task_con（反方） → PARALLEL 执行
    task_judge（裁判，依赖 pro+con） → 待 pro+con 完成后执行
  
  裁判输出：论点对比 + 分歧点 + 建议下一轮聚焦的议题

第2轮（replan）：
  Planner 看到裁判输出 + 分歧点 → 生成轮2 plan:
    task_pro_rebuttal, task_con_rebuttal → PARALLEL
    task_judge_final（依赖 rebuttal 两个 + 第1轮历史）

  终裁输出：共识点 + 分歧点 + 最终建议
```

本质是 DYNAMIC 模式的**特化**：debate 有固定的角色分工（正方/反方/裁判），replan 时自动保持角色一致性。

### 3.3 与 DYNAMIC 模式的关系

DYNAMIC 的迭代框架已支持 `execute → observe → replan`。DEBATE 复用这个框架，新增：

| 新增 | 说明 |
|---|---|
| 角色约定 | 正方/反方/裁判的命名规范（Planner prompt 指导） |
| 辩论历史 | replan 时注入前一轮的完整输出（`_build_debate_history`） |
| 收敛条件 | 裁判判定分歧已充分、或达到 max_rounds |

### 3.4 代码改动

**`utils/planning/prompts.py`**：新增 `_get_debate_planning_prompt`

```
## 辩论模式规则
当用户要求分析某个问题的正反两面、利弊权衡、多方观点对比时，用 debate 模式。

### 任务结构
- 第1轮：{正反方 task} × 2（PARALLEL）+ {裁判 task} × 1（依赖前两个）
- 裁判输出格式：
  ```
  【正方论点】...
  【反方论点】...
  【共识点】...
  【核心分歧】...
  【建议下一轮聚焦】...
  ```

### 多轮辩论
- 裁判指出分歧后，自动触发 replan（第2轮）
- 第2轮：针对分歧补充论证 → 终裁裁定
- max_rounds=2（默认 2 轮辩论）
```

**`executor/plan_executor.py`**：DEBATE 模式执行逻辑

```python
# 在 _prepare_plan 的 mode 分发中添加：
if plan.mode == PlanMode.DEBATE:
    async for event in self._execute_debate(plan, context, event_sender, ...):
        yield event

async def _execute_debate(self, plan, context, event_sender, ...):
    """辩论模式：复用 DYNAMIC 迭代框架，max_rounds 由 config 控制。"""
    max_rounds = get_config("agent.execution.debate.max_rounds", 2)
    for round_num in range(1, max_rounds + 1):
        # 1. 执行本轮 plan
        async for event in self._execute_with_workflow(plan, context, ...):
            yield event
        
        # 2. 检查是否需要继续
        judge_id = plan.tasks[-1].id
        if judge_id in context and self._debate_converged(context[judge_id]):
            break
        
        # 3. replan：把本轮结果注入 prompt
        if round_num < max_rounds:
            plan = await self._replan_debate(plan, context, round_num)
```

### 3.5 Planner 识别辩论场景

Planner prompt 中增加辩论场景的关键词触发：

```
- 当用户问题包含"正方/反方""利弊权衡""多角度分析""辩论""对抗"等关键词时，
  使用 debate 模式
```

---

## 四、改动清单

| 文件 | 改动 | 模式 |
|---|---|---|
| `utils/planning/schemas.py` | `PlanMode` 新增 `DEBATE` | 两者 |
| `utils/planning/prompts.py` | 新增汇总 Agent 提示 + 辩论模式 prompt | 两者 |
| `executor/plan_executor.py` | `_is_synthesizer_task` + `_summarize_results` 改造 | 中心汇总 |
| `executor/plan_executor.py` | `_execute_debate` + `_replan_debate` + `_debate_converged` | 辩论 |
| `config/agent_config.json` | 新增 `agent.execution.debate.max_rounds` | 辩论 |

---

## 五、测试策略

### 中心汇总
- 单元测试：`_is_synthesizer_task` 各种 plan 形状
- 集成测试：PARALLEL 模式下指定汇总 Agent 的场景

### 辩论
- 单元测试：`_debate_converged` 收敛判断
- 集成测试：辩论关键词触发 Planner 选 DEBATE 模式
- 集成测试：2 轮辩论完整流程

---

## 六、兼容性

- `_summarize_results` 改造是纯增强：无汇总 Agent 时回退系统 LLM
- `PlanMode.DEBATE` 新增，不影响已有模式
- Planner prompt 增量添加，不删除现有规则
