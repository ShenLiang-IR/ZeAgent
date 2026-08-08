"""出站事件订阅 API：subscribe / list / unsubscribe / notify。

设计参见 当前文档分析.md §3.13。

路径前缀 /api/admin/subscriptions/*：
- POST   /subscriptions                       创建订阅
- GET    /subscriptions                       列出订阅
- DELETE /subscriptions/{subscription_id}    取消订阅
- POST   /subscriptions/notify                手动触发通知（测试用）
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from utils.common.permissions import UserPermissions

from .base import wrap_response
from .permissions import require_read, require_write

router = APIRouter(prefix="/subscriptions", tags=["event-subscriptions"])


class SubscribeRequest(BaseModel):
    name: str
    event_type: str  # dispatch_completed / dispatch_failed / quota_exceeded / agent_error / all
    callback_url: str
    secret: str = ""
    workspace_id: int | None = None


class NotifyRequest(BaseModel):
    event_type: str
    payload: dict = {}
    workspace_id: int | None = None


@router.post("")
async def subscribe(
    req: SubscribeRequest,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """创建事件订阅（外部系统注册 webhook 接收 dispatch 事件）。"""
    from services.event_subscription_service import EventSubscriptionService
    result = EventSubscriptionService().subscribe(
        name=req.name, event_type=req.event_type, callback_url=req.callback_url,
        secret=req.secret, workspace_id=req.workspace_id,
    )
    if not result:
        raise HTTPException(status_code=500, detail="创建订阅失败")
    return wrap_response(result)


@router.get("")
async def list_subscriptions(
    workspace_id: int | None = Query(None),
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """列出订阅（可选 workspace 过滤）。"""
    from services.event_subscription_service import EventSubscriptionService
    subs = EventSubscriptionService().list_subscriptions(workspace_id)
    return wrap_response({"subscriptions": subs, "total": len(subs)})


@router.delete("/{subscription_id}")
async def unsubscribe(
    subscription_id: str,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """取消订阅。"""
    from services.event_subscription_service import EventSubscriptionService
    if not EventSubscriptionService().unsubscribe(subscription_id):
        raise HTTPException(status_code=404, detail=f"订阅 {subscription_id} 不存在")
    return wrap_response({"success": True, "message": f"订阅 {subscription_id} 已取消"})


@router.post("/notify")
async def notify(
    req: NotifyRequest,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """手动触发事件通知（测试用，验证 webhook 是否可达）。"""
    from services.event_subscription_service import EventSubscriptionService
    success = await EventSubscriptionService().notify(req.event_type, req.payload, req.workspace_id)
    return wrap_response({"success_count": success, "event_type": req.event_type})
