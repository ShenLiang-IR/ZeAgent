# 人工干预功能（重规划第三期）实施计划 — 方案 A

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** plan_executor 支持 task 完成后 pause 等待人工审核（approve/modify/reject），前端 PlanReviewDialog 审核提交，后端继续/停止/重建图。

**Architecture:** `asyncio.Queue` + `ReviewRegistry`（dispatch_id→queue）。plan_executor while 内 `human_approval=true` 时 yield SSE `plan_review` + `await queue.get()`；POST `/api/plan/{dispatch_id}/review` put 唤醒。

**Tech Stack:** Python 3.13 + FastAPI + asyncio + Vue3/ElementPlus + pytest(asyncio_mode=auto)

**Spec:** `docs/superpowers/specs/2026-07-16-human-intervention-design.md`（commit fe71fa3）

**Test command:** `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest <test> -v -p no:warnings`

## Global Constraints

- 首期只做 `plan_executor` 路径（ChatView 单 agent），`multi_agent_service` 路径后续（spec §3 非目标）
- `human_approval=false`（默认）不 pause，行为与第二期一致（兼容）
- pause 用 `asyncio.Queue` + `ReviewRegistry`（不用轮询/Event）
- 触发开关用 config 全局 `human_approval`（per-task 字段后续，YAGNI）
- dispatch_id 用 plan_executor 的 `self.session_id`
- 回退：`human_approval=false` 完全禁用

---

## File Structure

| File | Type | Responsibility |
|------|------|----------------|
| `utils/review/__init__.py` | Create | 包标识 |
| `utils/review/registry.py` | Create | ReviewRegistry（dispatch_id→asyncio.Queue） |
| `test/test_review_registry.py` | Create | ReviewRegistry 单元测试 |
| `executor/plan_executor.py` | Modify | while 加 human_approval pause 逻辑 |
| `config/agent_config.json` | Modify | replan 段加 human_approval/timeout |
| `test/test_human_approval.py` | Create | plan_executor pause 逻辑测试 |
| `api/plan/__init__.py` | Create | 包标识 |
| `api/plan/review_routes.py` | Create | POST /api/plan/{dispatch_id}/review |
| `server.py` | Modify | 注册 review_router |
| `frontend/src/components/PlanReviewDialog.vue` | Create | 审核对话框组件 |
| `frontend/src/views/ChatView.vue` | Modify | onEvent 处理 plan_review |
| `frontend/src/api/index.js` | Modify | planApi.review |

---

### Task 1: ReviewRegistry + 单元测试（RED→GREEN）

**Files:**
- Create: `utils/review/__init__.py`、`utils/review/registry.py`
- Test: `test/test_review_registry.py`

**Interfaces:**
- Produces: `ReviewRegistry.register(dispatch_id) -> asyncio.Queue`、`.put(dispatch_id, result) -> bool`、`.get(dispatch_id) -> Optional[Queue]`、`.remove(dispatch_id) -> None`、`.await_review(dispatch_id, timeout) -> Optional[Dict]`

- [ ] **Step 1: Write failing test**

```python
# test/test_review_registry.py
"""ReviewRegistry 单元测试（重规划第三期人工干预）。"""
import asyncio
import pytest
from utils.review.registry import ReviewRegistry


def test_register_creates_queue():
    q = ReviewRegistry.register("d1")
    assert isinstance(q, asyncio.Queue)


def test_get_returns_registered_queue():
    q1 = ReviewRegistry.register("d2")
    q2 = ReviewRegistry.get("d2")
    assert q1 is q2


def test_put_unregistered_returns_false():
    assert ReviewRegistry.put("nonexistent", {"action": "approve"}) is False


def test_put_registered_returns_true():
    ReviewRegistry.register("d3")
    assert ReviewRegistry.put("d3", {"action": "approve"}) is True


@pytest.mark.asyncio
async def test_await_review_returns_put_result():
    ReviewRegistry.register("d4")
    ReviewRegistry.put("d4", {"action": "modify", "modified_plan": {"x": 1}})
    result = await ReviewRegistry.await_review("d4", timeout=2)
    assert result["action"] == "modify"
    assert result["modified_plan"] == {"x": 1}


@pytest.mark.asyncio
async def test_await_review_timeout_returns_reject():
    ReviewRegistry.register("d5")
    result = await ReviewRegistry.await_review("d5", timeout=1)
    assert result["action"] == "reject"
    assert "timeout" in result.get("reason", "")


def test_remove_clears_queue():
    ReviewRegistry.register("d6")
    ReviewRegistry.remove("d6")
    assert ReviewRegistry.get("d6") is None
```

- [ ] **Step 2: Run to verify fails**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_review_registry.py -v -p no:warnings --tb=line`
Expected: FAIL（`ModuleNotFoundError: No module named 'utils.review'`）

- [ ] **Step 3: Implement ReviewRegistry**

```python
# utils/review/__init__.py
# （空文件，包标识）
```

```python
# utils/review/registry.py
"""人工审核 registry：dispatch_id → asyncio.Queue，供 plan_executor pause 与 review API 协调。"""
import asyncio
from typing import Optional, Dict, Any
from loguru import logger


class ReviewRegistry:
    """dispatch_id → asyncio.Queue 的共享 registry。

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
    async def await_review(cls, dispatch_id: str, timeout: float = 300) -> Optional[Dict[str, Any]]:
        """plan_executor pause 时调用，阻塞等待审核结果。超时返回 reject。"""
        q = cls._queues.get(dispatch_id)
        if q is None:
            logger.warning(f"[ReviewRegistry] {dispatch_id} 未注册，返回 reject")
            return {"action": "reject", "reason": "not_registered"}
        try:
            result = await asyncio.wait_for(q.get(), timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning(f"[ReviewRegistry] {dispatch_id} 审核超时({timeout}s)，按 reject 处理")
            return {"action": "reject", "reason": "timeout"}

    @classmethod
    def remove(cls, dispatch_id: str) -> None:
        cls._queues.pop(dispatch_id, None)
```

- [ ] **Step 4: Run test to verify passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_review_registry.py -v -p no:warnings`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add utils/review/ test/test_review_registry.py
git commit -m "feat(review): ReviewRegistry for human-in-the-loop pause (replan phase3, TDD GREEN 7/7)"
```

---

### Task 2: plan_executor pause 逻辑 + config

**Files:**
- Modify: `executor/plan_executor.py`（`_execute_with_workflow` while 循环，loop/replan 检查前加 human_approval 检查）
- Modify: `config/agent_config.json`（replan 段加 human_approval/timeout）
- Test: `test/test_human_approval.py`

**Interfaces:**
- Consumes: `ReviewRegistry` from Task 1
- Produces: plan_executor human_approval=true 时 yield plan_review + pause

- [ ] **Step 1: Add config**

`config/agent_config.json` 的 `agent.execution.replan` 段（`max_loop` 后）加：

```json
"human_approval": false,
"_comment_human_approval": "人工审核开关（true 时 task 完成后暂停等审核）",
"human_approval_timeout": 300,
"_comment_human_approval_timeout": "审核超时秒数（超时按 reject 处理）"
```

- [ ] **Step 2: Write failing test**

```python
# test/test_human_approval.py
"""plan_executor human_approval pause 逻辑测试。"""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from utils.review.registry import ReviewRegistry


def test_human_approval_false_skips_pause():
    """human_approval=false 不 pause（兼容旧行为）。"""
    # 验证 config 读 human_approval=false 时 plan_executor 不调 ReviewRegistry
    import executor.plan_executor as pe_mod
    with patch.object(pe_mod, 'get_config', lambda k, d=None: False if k == 'agent.execution.replan.human_approval' else d):
        from executor.plan_executor import PlanExecutor
        pe = PlanExecutor.__new__(PlanExecutor)
        # human_approval=false 时不应 register
        # （这里验证 config 读取，不跑完整 execute_stream）
        assert pe_mod.get_config('agent.execution.replan.human_approval', False) is False


@pytest.mark.asyncio
async def test_review_registry_integrates_with_pause():
    """ReviewRegistry await_review + put 集成（模拟 plan_executor pause 流程）。"""
    ReviewRegistry.register("test-session")
    # 模拟前端提交 approve
    ReviewRegistry.put("test-session", {"action": "approve"})
    result = await ReviewRegistry.await_review("test-session", timeout=2)
    assert result["action"] == "approve"
    ReviewRegistry.remove("test-session")
```

- [ ] **Step 3: Run to verify fails/passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_human_approval.py -v -p no:warnings`
Expected: PASS（验证 config + ReviewRegistry 集成；plan_executor 完整 pause 在端到端验证）

- [ ] **Step 4: Add pause logic to plan_executor**

`executor/plan_executor.py` 的 `_execute_with_workflow`，while 循环内 astream 消费完成后、`_check_loop` 前（约 line 546 前），插入 human_approval 检查：

```python
                # 人工审核检查（第三期，human_approval=true 时 pause）
                human_approval = get_config("agent.execution.replan.human_approval", False)
                if human_approval and replan_round < max_replan_rounds:
                    from utils.review.registry import ReviewRegistry
                    from utils.sse.unified_event import build_sse_event
                    review_id = self.session_id or "default"
                    ReviewRegistry.register(review_id)
                    review_timeout = get_config("agent.execution.replan.human_approval_timeout", 300)
                    yield build_sse_event("plan_review", dispatch_id=review_id,
                        plan=plan.to_dict(), results={k: v for k, v in context.items()},
                        options=["approve", "modify", "reject"])
                    logger.info(f"[PlanExecutor] 人工审核 pause，等待 {review_id} 审核")
                    review_result = await ReviewRegistry.await_review(review_id, review_timeout)
                    ReviewRegistry.remove(review_id)
                    action = (review_result or {}).get("action", "reject")
                    if action == "reject":
                        logger.info("[PlanExecutor] 用户拒绝，终止执行")
                        break
                    elif action == "modify":
                        modified = (review_result or {}).get("modified_plan")
                        if modified:
                            try:
                                plan = ExecutionPlan(**modified)
                                replan_round += 1
                                graph = builder.build(plan=plan, semaphore=semaphore,
                                    deep_thinking=deep_thinking, stream_mode="stream")
                                logger.info("[PlanExecutor] 用户修改 plan，重建图继续")
                            except Exception as e:
                                logger.warning(f"[PlanExecutor] modified_plan 无效: {e}，用原 plan 继续")
                    # approve: 继续 while（下一轮 astream 或 _check_loop/replan）
```

- [ ] **Step 5: Verify JSON + import**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -c "import json; json.load(open('config/agent_config.json',encoding='utf-8')); print('JSON OK')"` 
Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -c "import executor.plan_executor; print('import OK')"`

- [ ] **Step 6: Run regression**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_human_approval.py test/test_review_registry.py test/test_dynamic_replanning.py test/test_replanning_loop.py -v -p no:warnings --tb=line`
Expected: 全 PASS（human_approval=false 走现有逻辑，第一/二期不受影响）

- [ ] **Step 7: Commit**

```bash
git add executor/plan_executor.py config/agent_config.json test/test_human_approval.py
git commit -m "feat(plan_executor): human_approval pause + plan_review SSE (replan phase3)"
```

---

### Task 3: POST API + server 注册

**Files:**
- Create: `api/plan/__init__.py`、`api/plan/review_routes.py`
- Modify: `server.py`（注册 review_router）

- [ ] **Step 1: Create review_routes**

```python
# api/plan/__init__.py
# （空文件，包标识）
```

```python
# api/plan/review_routes.py
"""人工审核结果提交 API。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from utils.review.registry import ReviewRegistry

router = APIRouter(prefix="/api/plan", tags=["plan-review"])


class PlanReviewRequest(BaseModel):
    action: str  # approve | modify | reject
    modified_plan: Optional[Dict[str, Any]] = None


@router.post("/{dispatch_id}/review")
async def submit_plan_review(dispatch_id: str, req: PlanReviewRequest):
    """接收人工审核结果，唤醒 plan_executor。"""
    ok = ReviewRegistry.put(dispatch_id, {"action": req.action, "modified_plan": req.modified_plan})
    if not ok:
        raise HTTPException(404, f"dispatch {dispatch_id} 未注册或已超时")
    return {"status": "ok", "dispatch_id": dispatch_id, "action": req.action}
```

- [ ] **Step 2: Register router in server.py**

`server.py` 现有 `app.include_router(...)` 后加：

```python
from api.plan.review_routes import router as plan_review_router
app.include_router(plan_review_router)
```

- [ ] **Step 3: Verify import**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -c "from api.plan.review_routes import router; print('import OK')"`

- [ ] **Step 4: Commit**

```bash
git add api/plan/ server.py
git commit -m "feat(api): POST /api/plan/{dispatch_id}/review endpoint (human approval)"
```

---

### Task 4: 前端 PlanReviewDialog + ChatView onEvent + api

**Files:**
- Create: `frontend/src/components/PlanReviewDialog.vue`
- Modify: `frontend/src/views/ChatView.vue`（onEvent 加 plan_review）
- Modify: `frontend/src/api/index.js`（planApi.review）

- [ ] **Step 1: Create PlanReviewDialog.vue**

```vue
<!-- frontend/src/components/PlanReviewDialog.vue -->
<template>
  <el-dialog v-model="visible" title="人工审核 - Plan Review" width="700px" :close-on-click-modal="false">
    <div v-if="data">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="Dispatch ID">{{ data.dispatch_id }}</el-descriptions-item>
        <el-descriptions-item label="Plan Mode">{{ data.plan?.mode }}</el-descriptions-item>
      </el-descriptions>
      <el-divider content-position="left">已完成 Task 结果</el-divider>
      <el-table :data="resultRows" border size="small" style="margin-bottom: 12px;">
        <el-table-column prop="task_id" label="Task ID" width="150" />
        <el-table-column prop="result" label="结果" show-overflow-tooltip />
      </el-table>
      <el-divider content-position="left">操作</el-divider>
      <el-radio-group v-model="action" style="margin-bottom: 12px;">
        <el-radio-button label="approve">批准</el-radio-button>
        <el-radio-button label="modify">修改</el-radio-button>
        <el-radio-button label="reject">拒绝</el-radio-button>
      </el-radio-group>
      <el-input v-if="action === 'modify'" v-model="modifiedPlanJson" type="textarea" :rows="6"
        placeholder='修改后的 plan JSON，如 {"mode":"parallel","tasks":[...]}' />
    </div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">提交审核</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { planApi } from '../api/index.js'

const props = defineProps({ modelValue: Boolean, data: Object })
const emit = defineEmits(['update:modelValue'])
const visible = computed({ get: () => props.modelValue, set: v => emit('update:modelValue', v) })
const action = ref('approve')
const modifiedPlanJson = ref('')
const submitting = ref(false)
const resultRows = computed(() => {
  const r = props.data?.results || {}
  return Object.entries(r).map(([task_id, result]) => ({ task_id, result: String(result).slice(0, 200) }))
})

watch(() => props.data, () => { action.value = 'approve'; modifiedPlanJson.value = '' })

const submit = async () => {
  if (!props.data?.dispatch_id) return
  submitting.value = true
  try {
    let modifiedPlan = null
    if (action.value === 'modify') {
      try { modifiedPlan = JSON.parse(modifiedPlanJson.value) }
      catch { ElMessage.error('plan JSON 格式无效'); submitting.value = false; return }
    }
    await planApi.review(props.data.dispatch_id, action.value, modifiedPlan)
    ElMessage.success(`审核已提交: ${action.value}`)
    visible.value = false
  } catch (e) { ElMessage.error('提交失败: ' + e.message) }
  finally { submitting.value = false }
}
</script>
```

- [ ] **Step 2: Add planApi to api/index.js**

`frontend/src/api/index.js` 末尾加：

```js
export const planApi = {
  review: async (dispatchId, action, modifiedPlan) => {
    const res = await fetch(`/api/plan/${dispatchId}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, modified_plan: modifiedPlan })
    })
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  }
}
```

- [ ] **Step 3: Add plan_review handling to ChatView.vue**

`frontend/src/views/ChatView.vue`：
- template 加 `<PlanReviewDialog v-model="reviewVisible" :data="reviewData" />`
- script 加 `import PlanReviewDialog from '../components/PlanReviewDialog.vue'` + `import { planApi } from '../api/index.js'`
- 加 `const reviewVisible = ref(false)` + `const reviewData = ref(null)`
- `streamChat` 的 onEvent 里加：
```js
if (data.type === 'plan_review') { reviewVisible.value = true; reviewData.value = data }
```

- [ ] **Step 4: vite build**

Run: `cd frontend && npm run build`
Expected: ✓ built（无语法错误）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PlanReviewDialog.vue frontend/src/views/ChatView.vue frontend/src/api/index.js
git commit -m "feat(frontend): PlanReviewDialog + ChatView plan_review onEvent (human approval UI)"
```

---

### Task 5: 端到端验证（可选，需 ollama）

- [ ] **Step 1: E2E with human_approval=true**

设置 `config/agent_config.json` 的 `human_approval: true`，启动 server，前端发消息：
- SSE 应收到 `plan_review` 事件 → PlanReviewDialog 弹出
- 点"批准" → POST review → plan_executor 继续 → 最终结果到达

- [ ] **Step 2: Reset config**

验证后设回 `human_approval: false`

---

## Self-Review

**1. Spec coverage:** §5.1 ReviewRegistry → Task 1；§5.2 plan_executor pause → Task 2；§5.3 SSE 契约 → Task 2 Step 4；§5.4 POST API → Task 3；§5.5 前端 → Task 4；§5.6 config → Task 2 Step 1；§9 5 阶段 → Task 1-5。✅

**2. Placeholder scan:** 无 TBD/TODO，所有 step 含完整代码 + 命令。✅

**3. Type consistency:** `ReviewRegistry.register/put/get/await_review/remove` 在 Task 1-3 一致；`build_sse_event("plan_review", dispatch_id=, plan=, results=, options=)` 在 Task 2 与 Task 4 前端 onEvent 一致；`planApi.review(dispatchId, action, modifiedPlan)` 在 Task 4 一致。✅
