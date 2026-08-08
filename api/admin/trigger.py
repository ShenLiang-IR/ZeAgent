"""触发器管理路由（admin）+ Webhook 入站路由。

设计参见 docs/specs/2026-07-19-trigger-registry-design.md §7.1。

要点：
- router（管理端）：prefix=/triggers，走 verify_token 鉴权
- webhook_router（入站）：prefix=/triggers，**不**走 verify_token，
  用 WebhookTrigger.verify 做 HMAC-SHA256 验签
- 响应统一用 wrap_response（与 subagent.py 等现有路由风格一致）
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field

from utils.common.permissions import UserPermissions

from .base import wrap_response
from .common import verify_token
from .permissions import require_delete, require_read, require_write


class TriggerConfig(BaseModel):
    """触发器创建/更新请求体。"""
    trigger_id: str = Field(..., description="业务ID，建议 TRG_ 前缀")
    trigger_name: str
    trigger_type: str = Field(..., description="cron|webhook|file_watch")
    config: str = Field(..., description="JSON string：类型相关配置")
    target_agent_ids: str = Field(..., description="逗号分隔 agent_id 列表")
    target_mode: str = "parallel"
    message_template: str
    workspace_id: int
    enabled: str = "0"  # 默认禁用，创建后显式 enable
    creator_id: int | None = None


# ─────────────────── 管理端 router（走 verify_token） ───────────────────

router = APIRouter(prefix="/triggers", tags=["admin"], dependencies=[Depends(verify_token)])


def _get_repo():
    """懒加载仓储，避免模块顶部循环 import。"""
    from infrastructure.database.repositories.trigger_repository import TriggerRepository
    return TriggerRepository()


def _get_registry():
    """懒加载 Registry。"""
    from services.trigger.registry import TriggerRegistry
    return TriggerRegistry.get_instance()


@router.post("")
async def create_trigger(
    data: TriggerConfig,
    user_permissions: UserPermissions = Depends(require_write("trigger"))
):
    """创建触发器（不自动启用，需显式 POST /{id}/enable）。"""
    repo = _get_repo()
    if repo.get_by_trigger_id(data.trigger_id):
        raise HTTPException(status_code=400, detail=f"trigger_id 已存在: {data.trigger_id}")
    row = repo.create(
        trigger_id=data.trigger_id,
        trigger_name=data.trigger_name,
        trigger_type=data.trigger_type,
        config=data.config,
        target_agent_ids=data.target_agent_ids,
        target_mode=data.target_mode,
        message_template=data.message_template,
        workspace_id=data.workspace_id,
        enabled=data.enabled,
        creator_id=data.creator_id,
        del_flag="0",
    )
    if not row:
        raise HTTPException(status_code=500, detail="创建触发器失败")
    logger.info(f"[trigger] created {data.trigger_id} by user={user_permissions.user_id}")
    return wrap_response(row, message="创建成功")


@router.get("")
async def list_triggers(
    workspace_id: int = Query(..., description="workspace_id 过滤"),
    enabled_only: bool = Query(False, description="仅返回启用的"),
    user_permissions: UserPermissions = Depends(require_read("trigger"))
):
    """列出 workspace 下的触发器。"""
    repo = _get_repo()
    rows = repo.list_by_workspace(workspace_id, enabled_only=enabled_only)
    return wrap_response({"triggers": rows, "total": len(rows), "count": len(rows)})


@router.get("/{trigger_id}")
async def get_trigger(
    trigger_id: str,
    user_permissions: UserPermissions = Depends(require_read("trigger"))
):
    """触发器详情。"""
    repo = _get_repo()
    row = repo.get_by_trigger_id(trigger_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"trigger 不存在: {trigger_id}")
    return wrap_response(row)


@router.put("/{trigger_id}")
async def update_trigger(
    trigger_id: str,
    data: TriggerConfig,
    user_permissions: UserPermissions = Depends(require_write("trigger"))
):
    """更新触发器配置 + 自动 reload（若已启用）。"""
    repo = _get_repo()
    existing = repo.get_by_trigger_id(trigger_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"trigger 不存在: {trigger_id}")
    # 通过 pr_key_id 更新
    pr_key_id = existing.get("pr_key_id")
    repo.update(pr_key_id, **{
        "trigger_name": data.trigger_name,
        "trigger_type": data.trigger_type,
        "config": data.config,
        "target_agent_ids": data.target_agent_ids,
        "target_mode": data.target_mode,
        "message_template": data.message_template,
    })
    # 始终调 reload：reload 内部会处理 disabled 情况（仅 unregister 不 register）
    try:
        registry = _get_registry()
        await registry.reload(trigger_id)
        logger.info(f"[trigger] reloaded {trigger_id}")
    except Exception as e:
        logger.warning(f"[trigger] reload {trigger_id} failed: {e}")
    return wrap_response({"trigger_id": trigger_id}, message="更新成功")


@router.delete("/{trigger_id}")
async def delete_trigger(
    trigger_id: str,
    user_permissions: UserPermissions = Depends(require_delete("trigger"))
):
    """软删触发器 + 注销运行时实例。"""
    repo = _get_repo()
    ok = repo.soft_delete(trigger_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"trigger 不存在: {trigger_id}")
    # 注销运行时
    try:
        registry = _get_registry()
        await registry.unregister(trigger_id)
    except Exception as e:
        logger.warning(f"[trigger] unregister {trigger_id} failed: {e}")
    logger.info(f"[trigger] deleted {trigger_id} by user={user_permissions.user_id}")
    return wrap_response({"trigger_id": trigger_id}, message="删除成功")


@router.post("/{trigger_id}/enable")
async def enable_trigger(
    trigger_id: str,
    user_permissions: UserPermissions = Depends(require_write("trigger"))
):
    """启用触发器：DB 标记 enabled=1 + Registry.register。"""
    repo = _get_repo()
    row = repo.get_by_trigger_id(trigger_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"trigger 不存在: {trigger_id}")
    repo.update(row.get("pr_key_id"), enabled="1")
    try:
        registry = _get_registry()
        await registry.register(row)
    except Exception as e:
        logger.error(f"[trigger] enable register {trigger_id} failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启用失败: {e}")
    return wrap_response({"trigger_id": trigger_id, "enabled": True}, message="启用成功")


@router.post("/{trigger_id}/disable")
async def disable_trigger(
    trigger_id: str,
    user_permissions: UserPermissions = Depends(require_write("trigger"))
):
    """禁用触发器：DB 标记 enabled=0 + Registry.unregister。"""
    repo = _get_repo()
    row = repo.get_by_trigger_id(trigger_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"trigger 不存在: {trigger_id}")
    repo.update(row.get("pr_key_id"), enabled="0")
    try:
        registry = _get_registry()
        await registry.unregister(trigger_id)
    except Exception as e:
        logger.warning(f"[trigger] disable unregister {trigger_id} failed: {e}")
    return wrap_response({"trigger_id": trigger_id, "enabled": False}, message="禁用成功")


@router.post("/{trigger_id}/test")
async def test_trigger(
    trigger_id: str,
    user_permissions: UserPermissions = Depends(require_write("trigger"))
):
    """手动触发一次（用空 event 调 handle）。"""
    registry = _get_registry()
    trigger = await registry.get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail=f"trigger 未注册或未启用: {trigger_id}")
    # 用空 event 调 handle
    log_id = await trigger.handle({"triggered_at": "manual_test", "manual": True})
    return wrap_response({"log_id": log_id}, message="手动触发成功")


@router.get("/{trigger_id}/logs")
async def get_trigger_logs(
    trigger_id: str,
    limit: int = Query(50, ge=1, le=500),
    user_permissions: UserPermissions = Depends(require_read("trigger"))
):
    """查询触发器执行历史。"""
    from infrastructure.database.repositories.trigger_repository import TriggerLogRepository
    logs = TriggerLogRepository().list_by_trigger(trigger_id, limit=limit)
    return wrap_response({"logs": logs, "total": len(logs), "count": len(logs)})


# ─────────────────── Webhook 入站 router（不走 verify_token） ───────────────────

webhook_router = APIRouter(prefix="/triggers", tags=["webhook"])


@webhook_router.post("/{trigger_id}/webhook")
async def webhook_inbound(trigger_id: str, request: Request):
    """Webhook 入站端点：HMAC-SHA256 验签 + 调度。

    **不走 verify_token**，由 WebhookTrigger.verify 校验签名。
    """
    registry = _get_registry()
    trigger = await registry.get_webhook_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail=f"webhook trigger 不存在或未启用: {trigger_id}")
    # 从 Request 提取参数调 verify（verify 是纯函数式签名，便于测试）
    body = await request.body()
    headers = {k: v for k, v in request.headers.items()}
    client_ip = request.client.host if request.client else ""
    event = await trigger.verify(body=body, headers=headers, client_ip=client_ip)
    # 验签通过，调 handle
    log_id = await trigger.handle(event)
    return wrap_response(data={"log_id": log_id, "status": "triggered"})
