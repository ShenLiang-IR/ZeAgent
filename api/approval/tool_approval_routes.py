"""Tool 执行审批 API — Human-in-the-Loop。

POST /api/admin/tool-approval/{dispatch_id}/review  提交审批结果
GET  /api/admin/tool-approval/pending              查询待审批列表
"""
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Request, Depends
from pydantic import BaseModel, Field
from loguru import logger

from utils.review.registry import ReviewRegistry

router = APIRouter(prefix="/api/admin/tool-approval", tags=["tool-approval"])


class ToolReviewRequest(BaseModel):
    """工具审批结果。"""
    action: str = Field(..., description="approve | reject")
    reason: str = Field("", description="审批备注")


class ToolApprovalItem(BaseModel):
    """待审批项（用于 pending 列表）。"""
    dispatch_id: str
    tool_name: str
    risk_level: str
    agent_name: str = ""
    requested_at: str = ""


@router.post("/{dispatch_id}/review")
async def submit_tool_review(dispatch_id: str, req: ToolReviewRequest):
    """提交工具审批结果，唤醒阻塞等待的 ToolExecutionGuard。

    - approve: 执行 tool
    - reject: 返回拒绝信息给 LLM
    """
    if req.action not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="action must be 'approve' or 'reject'")

    ok = ReviewRegistry.put(dispatch_id, {
        "action": req.action,
        "reason": req.reason,
    })
    if not ok:
        raise HTTPException(status_code=404, detail=f"dispatch {dispatch_id} 未注册或已超时")

    logger.info(f"[ToolApproval] {dispatch_id} → {req.action} (reason={req.reason[:50] if req.reason else 'N/A'})")
    return {"status": "ok", "dispatch_id": dispatch_id, "action": req.action}


@router.get("/pending")
async def list_pending_tool_approvals():
    """查询当前待审批的 tool 调用列表。

    遍历 ReviewRegistry._queues，返回所有活跃的 dispatch。
    注意：这是同步快照，实际 pending 数量可能随时变化。
    """
    pending = []
    for dispatch_id, queue in ReviewRegistry._queues.items():
        if not queue.empty():
            continue  # 已被 put 但尚未 get，不算 pending
        pending.append({
            "dispatch_id": dispatch_id,
            "queue_size": queue.qsize(),
        })

    return {
        "success": True,
        "data": {
            "list": pending,
            "total": len(pending),
        },
    }
