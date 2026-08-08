# 人工干预功能设计 — 重规划第三期（方案 A）

> 日期：2026-07-16
> 方案：A（前后端协同：后端 pause 机制 + 前端审核 UI + SSE 契约 + 端到端验证）
> 前置：重规划第一/二期已实施（condition/replan_on + loop，`schemas:19/21` + `plan_executor:446/546`）
> 触及模块：`executor/plan_executor.py`、`api/chat/chat_routes.py`、`frontend/src/views/{ChatView,AgentList}.vue`、`frontend/src/api/index.js`

---

## 1. 背景

### 1.1 现状

重规划第一/二期已完成：
- 第一期：`condition`（条件分支）+ `replan_on`（动态插入）——事后检查 → `_replan`（调 LLM）→ 新 plan → 重跑
- 第二期：`loop`（task 级条件循环）——`_check_loop` + while 扩展

两期都是**自动**决策（LLM 重规划或条件循环），**无人工干预/审核机制**（explore 确认：grep human/approval/pause/intervene 仅命中 `HumanMessage`，与审核无关）。

### 1.2 需求

plan 执行中途，人工审核中间结果，决定继续/修改/终止。金融研究场景需人工把关规划质量（executoranalyse 缺点1："无人工干预/审核机制"）。

## 2. 目标

- **后端 pause 机制**：plan_executor while 循环，task 完成后若 `human_approval=true`，yield SSE `plan_review` 事件，暂停等待审核结果
- **SSE 契约**：`plan_review` 事件 schema + 审核结果 POST schema
- **前端审核 UI**：ChatView/AgentList 收到 `plan_review` → 弹审核对话框 → 用户批准/修改/拒绝 → POST 提交
- **后端 API**：`POST /api/plan/{dispatch_id}/review` 接收审核结果，唤醒 plan_executor
- **端到端验证**：mock LLM + human_approval=true → SSE plan_review → 提交 → 后端继续

## 3. 非目标

- per-task `pause_for_review` 字段（首期只用 config 全局开关，per-task 后续扩展，YAGNI）
- multi_agent_service 路径（AgentList multiDispatch）的 plan_review 处理（首期只做 plan_executor 路径 ChatView，multi_agent_service 路径后续扩展）
- 多人协同审核（单用户审核）
- 审核历史持久化（首期内存 queue，不写 DB）
- RAG（用户说后面重点开发，当前不涉及）

---

## 4. 架构

```
plan_executor._execute_with_workflow while 循环（扩展）:
  astream 完成 → 检查 human_approval config
    → 若 true 且非最后轮：yield SSE plan_review 事件 + await ReviewRegistry.get(dispatch_id).get()
    → 暂停，等待 POST /api/plan/{dispatch_id}/review
  POST review → ReviewRegistry.put(dispatch_id, result) → queue 唤醒
  plan_executor 按结果：
    approve → 继续 while（下一轮 / 结束）
    modify → 用 modified_plan 替换 plan，重建图，继续
    reject → break，用已有结果 + 标记"用户拒绝"
```

**pause 等待机制：asyncio.Queue + ReviewRegistry**
- `ReviewRegistry`（新，`utils/review/registry.py`）：dispatch_id → `asyncio.Queue`，`register/get/put/remove`
- plan_executor `await queue.get()` 阻塞等待，POST API `queue.put(result)` 唤醒
- 优于轮询（无延迟）和 asyncio.Event（queue 能携带 review_result）

---

## 5. 组件设计

### 5.1 ReviewRegistry（新）

**文件**：`utils/review/registry.py`

```python
import asyncio
from typing import Optional, Dict, Any
from loguru import logger


class ReviewRegistry:
    """dispatch_id → asyncio.Queue 的审核等待注册表。

    plan_executor pause 时 register + await get；
    POST /api/plan/review 时 put 唤醒。
    """

    _queues: Dict[str, asyncio.Queue] = {}

    @classmethod
    def register(cls, dispatch_id: str) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=1)
        cls._queues[dispatch_id] = q
        return q

    @classmethod
    def get(cls, dispatch_id: str) -> Optional[asyncio.Queue]:
        return cls._queues.get(dispatch_id)

    @classmethod
    def put(cls, dispatch_id: str, result: Dict[str, Any]) -> bool:
        q = cls._queues.get(dispatch_id)
        if q is None:
            logger.warning(f"[ReviewRegistry] dispatch {dispatch_id} 未注册")
            return False
        q.put_nowait(result)
        return True

    @classmethod
    def remove(cls, dispatch_id: str) -> None:
        cls._queues.pop(dispatch_id, None)
```

### 5.2 plan_executor pause 逻辑（扩展）

**文件**：`executor/plan_executor.py`（`_execute_with_workflow` while 循环）

while 循环内，astream 完成 + loop/replan 检查后，加 human_approval 检查：

```python
# 人工审核检查（第三期）
human_approval = get_config("agent.execution.replan.human_approval", False)
if human_approval and replan_round < max_replan_rounds:
    review_id = self.session_id or "default"
    from utils.review.registry import ReviewRegistry
    review_queue = ReviewRegistry.register(review_id)
    # yield plan_review SSE 事件
    yield build_sse_event("plan_review", dispatch_id=review_id,
        plan=plan.to_dict(), results=context, options=["approve", "modify", "reject"])
    # 暂停等待审核结果
    review_result = await asyncio.wait_for(review_queue.get(),
        timeout=get_config("agent.execution.replan.human_approval_timeout", 300))
    ReviewRegistry.remove(review_id)
    action = review_result.get("action", "approve")
    if action == "reject":
        logger.info("[PlanExecutor] 用户拒绝，终止执行")
        break
    elif action == "modify":
        plan = ExecutionPlan(**review_result.get("modified_plan", plan.to_dict()))
        replan_round += 1
        graph = builder.build(plan=plan, semaphore=semaphore,
            deep_thinking=deep_thinking, stream_mode="stream")
    # approve: 继续 while（下一轮 astream 或结束）
```

### 5.3 SSE 契约

**plan_review 事件**（plan_executor yield）：
```json
{
  "type": "plan_review",
  "dispatch_id": "session-xxx",
  "plan": {"mode": "parallel", "tasks": [{"id":"t1","agent":"a","description":"..."}]},
  "results": {"t1": "task 结果文本"},
  "options": ["approve", "modify", "reject"]
}
```

**审核结果 POST**（前端提交）：
```json
{
  "action": "approve" | "modify" | "reject",
  "modified_plan": {"mode": "parallel", "tasks": [...]}  // 仅 modify 时
}
```

### 5.4 后端 API（新）

**文件**：`api/chat/chat_routes.py` 或 `api/admin/agent_dispatch.py`

```python
@router.post("/api/plan/{dispatch_id}/review")
async def submit_plan_review(dispatch_id: str, body: PlanReviewRequest):
    """接收人工审核结果，唤醒 plan_executor。"""
    from utils.review.registry import ReviewRegistry
    ok = ReviewRegistry.put(dispatch_id, body.dict())
    if not ok:
        raise HTTPException(404, f"dispatch {dispatch_id} 未注册或已超时")
    return {"status": "ok", "action": body.action}
```

`PlanReviewRequest`（`api/schemas/`）：
```python
class PlanReviewRequest(BaseModel):
    action: str  # approve | modify | reject
    modified_plan: Optional[Dict[str, Any]] = None
```

### 5.5 前端审核 UI

**PlanReviewDialog 组件**（新，`frontend/src/components/PlanReviewDialog.vue`）：
- props: `plan`, `results`, `dispatchId`
- 显示：plan mode + tasks 列表 + 各 task 结果
- 操作：批准（approve）/ 修改（textarea 编辑 plan JSON）/ 拒绝（reject）
- 提交：调 `planApi.review(dispatchId, action, modifiedPlan)`

**ChatView.vue**（streamChat onEvent）：
```js
if (data.type === 'plan_review') {
  planReviewVisible.value = true
  planReviewData.value = data
}
```

**AgentList.vue multiDispatch**（同 onEvent 处理）

**api/index.js**：
```js
planApi: {
  review: (dispatchId, action, modifiedPlan) =>
    fetch(`/api/plan/${dispatchId}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, modified_plan: modifiedPlan })
    })
}
```

### 5.6 config

`config/agent_config.json` 的 `agent.execution.replan` 段加：
```json
"human_approval": false,
"_comment_human_approval": "人工审核开关（true 时 task 完成后暂停等审核）",
"human_approval_timeout": 300,
"_comment_human_approval_timeout": "审核超时秒数（超时按 reject 处理）"
```

---

## 6. 数据流

```
用户发送消息 → plan_executor.execute_stream
  → LLM 规划 plan → while 循环：
    第 1 轮：build → astream → task 执行 → context 填充
    → human_approval=true → yield plan_review SSE + await ReviewRegistry.get().get()
    → 暂停
前端 SSE onEvent 收到 plan_review
  → PlanReviewDialog 弹出（plan + results + 操作按钮）
  → 用户点"批准" → POST /api/plan/{dispatch_id}/review {action:"approve"}
后端 API → ReviewRegistry.put(dispatch_id, {action:"approve"})
  → queue 唤醒 → plan_executor 继续 while
  → 第 2 轮 / 结束 → yield 最终结果
```

---

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| approve | plan_executor 继续 while（下一轮 astream / 结束） |
| modify | 用 modified_plan 替换 plan，重建图，继续 |
| reject | plan_executor break，用已有结果 + log "用户拒绝" |
| 超时（human_approval_timeout） | `asyncio.wait_for` 超时 → 按 reject 处理 + warning |
| 前端断开 | queue.get() 超时 → reject（同上） |
| dispatch_id 未注册 | POST 返回 404 |
| modified_plan 无效 | plan_executor 重建图失败 → except 捕获 + 用原 plan + warning |

---

## 8. 测试策略

### 8.1 后端单元测试

**文件**：`test/test_human_approval.py`（新建，不依赖 MySQL/ollama）

| 测试 | 验证 |
|---|---|
| ReviewRegistry register/get/put/remove | queue 创建、put 唤醒 get、remove 清理 |
| ReviewRegistry put 未注册 dispatch | 返回 False |
| plan_executor human_approval=false | 不 pause，正常执行（兼容） |
| plan_executor human_approval=true approve | yield plan_review → mock put approve → 继续 |
| plan_executor human_approval=true reject | yield plan_review → mock put reject → break |
| plan_executor human_approval=true modify | yield plan_review → mock put modify → 用新 plan |
| plan_executor 超时 | mock queue 不 put → wait_for 超时 → reject |

### 8.2 前端验证

- `vite build` 通过（PlanReviewDialog 语法正确）
- ChatView/AgentList 的 onEvent plan_review 处理逻辑（无前端测试框架，用 build 验证）

### 8.3 端到端（可选，需 ollama）

- human_approval=true → SSE plan_review 到达 → POST approve → plan_executor 继续 → 最终结果

---

## 9. 分阶段实施

| 阶段 | 内容 | 验证 |
|---|---|---|
| 1 | ReviewRegistry + 单元测试 | test_human_approval Registry 部分 PASS |
| 2 | plan_executor pause 逻辑 + config | test_human_approval pause 逻辑 PASS |
| 3 | 后端 API /api/plan/review | curl 测试 |
| 4 | 前端 PlanReviewDialog + ChatView/AgentList onEvent + api | vite build |
| 5 | 端到端（可选） | SSE plan_review → approve → 继续 |

---

## 10. 文件变更清单

| 文件 | 变更类型 | 阶段 |
|---|---|---|
| `utils/review/__init__.py` | 新建 | 1 |
| `utils/review/registry.py` | 新建（ReviewRegistry） | 1 |
| `executor/plan_executor.py` | 改（while 加 human_approval 检查） | 2 |
| `config/agent_config.json` | 改（replan 段加 human_approval/timeout） | 2 |
| `api/schemas/` | 改/新（PlanReviewRequest） | 3 |
| `api/chat/chat_routes.py` 或 `api/admin/agent_dispatch.py` | 改（POST review endpoint） | 3 |
| `frontend/src/components/PlanReviewDialog.vue` | 新建 | 4 |
| `frontend/src/views/ChatView.vue` | 改（onEvent plan_review） | 4 |
| `frontend/src/views/AgentList.vue` | 改（multiDispatch onEvent plan_review） | 4 |
| `frontend/src/api/index.js` | 改（planApi.review） | 4 |
| `test/test_human_approval.py` | 新建 | 1-2 |

---

## 11. 风险与回退

| 风险 | 等级 | 缓解 |
|---|---|---|
| asyncio.Queue 跨 request 生命周期 | 中 | ReviewRegistry 类级 dict，dispatch_id 映射，plan_executor 结束时 remove |
| plan_executor 是 async generator，pause 阻塞 yield | 中 | await queue.get() 在 yield plan_review 后，generator 自然挂起，不阻塞 SSE 流 |
| 审核超时前端未提交 | 低 | asyncio.wait_for timeout → reject |
| 前端 plan JSON 编辑易错 | 中 | textarea + JSON 解析校验，失败提示 |
| ReviewRegistry 内存泄漏 | 低 | plan_executor finally remove + 超时自动清理 |

**回退**：`agent.execution.replan.human_approval=false` 即禁用，plan_executor 不 pause，行为与第二期一致。

---

## 12. 后续（非本期）

- per-task `pause_for_review` 字段（TaskNode 加，精细控制哪些 task 需审核）
- 审核历史持久化（写 DB，跨重启追溯）
- 多人协同审核
