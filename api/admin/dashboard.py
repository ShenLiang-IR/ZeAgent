"""用户工作台快捷方式 API（所有登录用户可用，非 adminOnly）。"""
from typing import Optional
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from utils.common.auth_dependencies import (
    verify_admin_token as verify_token,
    get_user_id_from_auth_header,
    get_workspace_id_from_auth_header,
)
from .base import wrap_response

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(verify_token)])


def _get_repo():
    from infrastructure.database.repositories.dashboard_repository import DashboardRepository
    return DashboardRepository()


class ShortcutCreate(BaseModel):
    menu_path: str
    menu_label: str
    menu_icon: Optional[str] = None


@router.get("/shortcuts")
async def list_shortcuts(authorization: Optional[str] = Header(None)):
    """获取当前用户的工作台快捷方式列表。"""
    user_id = int(get_user_id_from_auth_header(authorization))
    workspace_id = get_workspace_id_from_auth_header(authorization)
    repo = _get_repo()
    items = repo.get_by_user(user_id, workspace_id)
    return wrap_response(data={"list": items, "total": len(items)})


@router.post("/shortcuts")
async def add_shortcut(body: ShortcutCreate, authorization: Optional[str] = Header(None)):
    """添加快捷方式（同 user+path 不重复）。"""
    user_id = int(get_user_id_from_auth_header(authorization))
    workspace_id = get_workspace_id_from_auth_header(authorization)
    repo = _get_repo()
    item = repo.add_shortcut(
        user_id=user_id,
        menu_path=body.menu_path,
        menu_label=body.menu_label,
        menu_icon=body.menu_icon,
        workspace_id=workspace_id,
    )
    return wrap_response(data=item)


@router.delete("/shortcuts/{shortcut_id}")
async def remove_shortcut(shortcut_id: int, authorization: Optional[str] = Header(None)):
    """删除快捷方式（仅限本人）。"""
    user_id = int(get_user_id_from_auth_header(authorization))
    repo = _get_repo()
    ok = repo.remove_shortcut(shortcut_id, user_id)
    if not ok:
        return wrap_response(code=404, message="快捷方式不存在或无权删除")
    return wrap_response(data={"deleted": shortcut_id})
