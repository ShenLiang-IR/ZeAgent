"""审计日志查询路由（admin）。

设计参见 docs/specs/2026-07-19-audit-log-design.md §5。
提供查询 API（admin 专属），写日志由 middleware 自动完成。
支持组合筛选（username + resource_type + workspace_name）+ 用户名/空间名联想补全。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from utils.common.permissions import UserPermissions

from .base import wrap_response
from .common import verify_token
from .permissions import require_read

router = APIRouter(prefix="/audit", tags=["admin"], dependencies=[Depends(verify_token)])


def _get_repo():
    """懒加载仓储，避免模块顶部循环 import。"""
    from infrastructure.database.repositories.audit_repository import AuditRepository
    return AuditRepository()


def _resolve_workspace_id(name: str) -> int | None:
    """工作空间名 → workspace_id（精确匹配 tb_workspace.name）。"""
    try:
        from sqlalchemy import select
        from infrastructure.database.models.workspace import Workspace
        from infrastructure.database.sessions import get_config_session
        with get_config_session() as session:
            ws = session.scalar(select(Workspace).where(Workspace.name == name))
            return ws.workspace_id if ws else None
    except Exception as e:
        logger.warning(f"[Audit] resolve workspace_id ({name}) failed: {e}")
        return None


@router.get("/logs")
async def list_audit_logs(
    username: str | None = Query(None, description="按用户名过滤（联想补全选择）"),
    resource_type: str | None = Query(None, description="按资源类型过滤"),
    action: str | None = Query(None, description="按操作类型过滤"),
    workspace_name: str | None = Query(None, description="按工作空间名过滤（联想补全选择）"),
    start_date: str | None = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1, description="页码从1开始"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数"),
    user_permissions: UserPermissions = Depends(require_read("audit")),
):
    """审计日志明细分页查询（admin 专属）。组合筛选 + 日期范围 + 分页。"""
    repo = _get_repo()
    workspace_id = None
    if workspace_name:
        workspace_id = _resolve_workspace_id(workspace_name)
        if workspace_id is None:
            return wrap_response({"logs": [], "total": 0, "page": page, "page_size": page_size, "error": f"工作空间不存在: {workspace_name}"})
    logs, total = repo.list_by_filters(
        username=username, resource_type=resource_type, action=action, workspace_id=workspace_id,
        start_date=start_date, end_date=end_date, page=page, page_size=page_size,
    )
    return wrap_response({"logs": logs, "total": total, "page": page, "page_size": page_size, "count": len(logs)})


@router.get("/summary")
async def audit_summary(
    start_date: str | None = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD"),
    user_permissions: UserPermissions = Depends(require_read("audit")),
):
    """审计日志报表汇总（5 维度聚合：资源类型/操作类型/用户/日期趋势/状态码）。"""
    repo = _get_repo()
    return wrap_response(repo.summary(start_date=start_date, end_date=end_date))


@router.get("/usernames")
async def list_usernames(
    q: str | None = Query(None, description="模糊匹配用户名"),
    user_permissions: UserPermissions = Depends(require_read("audit")),
):
    """用户名联想补全（distinct from tb_audit_log.username）。"""
    repo = _get_repo()
    return wrap_response({"usernames": repo.list_usernames(q, limit=10)})


@router.get("/workspaces")
async def list_workspaces(
    q: str | None = Query(None, description="模糊匹配工作空间名"),
    user_permissions: UserPermissions = Depends(require_read("audit")),
):
    """工作空间名联想补全（from tb_workspace.name）。"""
    try:
        from sqlalchemy import select
        from infrastructure.database.models.workspace import Workspace
        from infrastructure.database.sessions import get_config_session
        with get_config_session() as session:
            stmt = select(Workspace.workspace_id, Workspace.name)
            if q:
                stmt = stmt.where(Workspace.name.like(f"%{q}%"))
            stmt = stmt.limit(10)
            rows = session.execute(stmt).fetchall()
            return wrap_response({"workspaces": [{"workspace_id": r[0], "name": r[1]} for r in rows]})
    except Exception as e:
        logger.warning(f"[Audit] list_workspaces failed: {e}")
        return wrap_response({"workspaces": []})


@router.get("/logs/{audit_id}")
async def get_audit_detail(
    audit_id: str,
    user_permissions: UserPermissions = Depends(require_read("audit")),
):
    """审计日志详情（含 before/after_data）。"""
    repo = _get_repo()
    row = repo.get_by_audit_id(audit_id)  # 按 audit_id 字段查（非主键 pr_key_id，前端传 AUDIT_xxx）
    if not row:
        raise HTTPException(status_code=404, detail=f"audit 不存在: {audit_id}")
    return wrap_response(row)
