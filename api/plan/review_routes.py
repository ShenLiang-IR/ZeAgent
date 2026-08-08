# api/plan/review_routes.py
# 人工审核结果提交 API（spec §5.4）
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from utils.review.registry import ReviewRegistry

router = APIRouter(prefix="/api/plan", tags=["plan-review"])


class PlanReviewRequest(BaseModel):
    """人工审核结果（spec §5.4）。"""
    action: str  # approve | modify | reject
    modified_plan: Optional[Dict[str, Any]] = None


@router.post("/{dispatch_id}/review")
async def submit_plan_review(dispatch_id: str, req: PlanReviewRequest):
    """接收人工审核结果，唤醒 plan_executor（spec §5.4）。"""
    ok = ReviewRegistry.put(dispatch_id, {"action": req.action, "modified_plan": req.modified_plan})
    if not ok:
        raise HTTPException(status_code=404, detail=f"dispatch {dispatch_id} 未注册或已超时")
    return {"status": "ok", "dispatch_id": dispatch_id, "action": req.action}
