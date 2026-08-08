"""插件市场 API 路由。

路径前缀 /plugin（挂在 admin_router /api/admin 下 → /api/admin/plugin/*）。
请求/响应采用 smart-agent 风格（驼峰字段 + {code,message,data}）。
P1 插件市场 MVP：市场浏览/详情/发布/安装/卸载/启停。
"""
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, Query, Depends
from pydantic import BaseModel, Field

from ._error_handler import handle_admin_errors_wrap
from services.plugin_marketplace_service import PluginMarketplaceService
from utils.common.auth_dependencies import (
    get_workspace_id_from_auth_header,
    get_current_user_permissions,
    get_user_id_from_auth_header,
)
from .common import verify_token

router = APIRouter(prefix="/plugin", tags=["plugin"], dependencies=[Depends(verify_token)])


def api_response(data: Any = None, message: str = "success", success: bool = True) -> Dict[str, Any]:
    return {
        "code": "0000000000000000" if success else "9999999999999999",
        "message": message,
        "data": data,
    }


def _effective_workspace(request: Request, workspace_id: Optional[int]) -> Optional[int]:
    """admin 用 query 覆盖；非 admin 用 token 的 workspace_id（防越权）。"""
    is_admin = False
    try:
        perms = get_current_user_permissions(request.headers.get("Authorization", ""))
        is_admin = perms.has_role("admin")
    except Exception:
        pass
    if workspace_id is not None and is_admin:
        return workspace_id
    return get_workspace_id_from_auth_header(request.headers.get("Authorization", ""))


def _user_id(request: Request) -> Optional[int]:
    try:
        uid = get_user_id_from_auth_header(request.headers.get("Authorization", ""))
        return int(uid) if uid and str(uid).isdigit() else None
    except Exception:
        return None


# ─────────────────── 请求模型 ───────────────────

class MarketplaceQuery(BaseModel):
    category: Optional[str] = None
    keyword: Optional[str] = None
    page_no: int = Field(1, alias="pageNo", ge=1)
    page_size: int = Field(20, alias="pageSize", ge=1, le=100)

    class Config:
        populate_by_name = True


class PluginIdRequest(BaseModel):
    plugin_id: str = Field(..., alias="pluginId")

    class Config:
        populate_by_name = True


class PublishRequest(BaseModel):
    name: str
    display_name: str = Field(..., alias="displayName")
    plugin_type: str = Field("mcp_server", alias="pluginType", description="mcp_server/skill_python/skill_nodejs/skill_go/tool")
    description: Optional[str] = ""
    icon: Optional[str] = ""
    category: Optional[str] = ""
    tags: Optional[List[str]] = None
    author: Optional[str] = ""
    version: Optional[str] = "1.0.0"
    mcp_config: Optional[Dict[str, Any]] = Field(None, alias="mcpConfig", description="MCP 连接配置（mcp_server 类型必填）")
    manifest: Optional[Dict[str, Any]] = Field(None, description="skill 配置或 tool 描述（非 mcp_server 类型使用）")
    status: Optional[str] = "1"

    class Config:
        populate_by_name = True


class InstallRequest(BaseModel):
    plugin_id: str = Field(..., alias="pluginId")
    config: Optional[Dict[str, Any]] = None

    class Config:
        populate_by_name = True


class UninstallRequest(BaseModel):
    install_id: str = Field(..., alias="installId")

    class Config:
        populate_by_name = True


class ToggleRequest(BaseModel):
    install_id: str = Field(..., alias="installId")
    enabled: bool = True

    class Config:
        populate_by_name = True


# ─────────────────── 路由 ───────────────────

@router.post("/marketplace")
@handle_admin_errors_wrap("[Plugin] marketplace 失败", message="查询失败: {e}", exc_info=True, response_func=api_response)
async def plugin_marketplace(
    request: Request,
    req: MarketplaceQuery,
    workspace_id: Optional[int] = Query(None, description="按工作空间筛选（仅 admin 有效）"),
):
    effective_ws = _effective_workspace(request, workspace_id)
    service = PluginMarketplaceService()
    result = service.list_marketplace(
        category=req.category,
        keyword=req.keyword,
        workspace_id=effective_ws,
        limit=req.page_size,
        offset=(req.page_no - 1) * req.page_size,
    )
    return api_response(result)


@router.post("/detail")
@handle_admin_errors_wrap("[Plugin] detail 失败", message="查询失败: {e}", exc_info=True, response_func=api_response)
async def plugin_detail(req: PluginIdRequest):
    service = PluginMarketplaceService()
    result = service.get_plugin_detail(req.plugin_id)
    if result is None:
        return api_response(None, message="插件不存在", success=False)
    return api_response(result)


@router.post("/publish")
@handle_admin_errors_wrap("[Plugin] publish 失败", message="发布失败: {e}", exc_info=True, response_func=api_response)
async def plugin_publish(request: Request, req: PublishRequest):
    workspace_id = get_workspace_id_from_auth_header(request.headers.get("Authorization", ""))
    service = PluginMarketplaceService()
    result = service.publish_plugin(
        name=req.name,
        display_name=req.display_name,
        plugin_type=req.plugin_type,
        description=req.description or "",
        icon=req.icon or "",
        category=req.category or "",
        tags=req.tags,
        author=req.author or "",
        version=req.version or "1.0.0",
        mcp_config=req.mcp_config,
        manifest=req.manifest,
        status=req.status or "1",
        workspace_id=workspace_id,
    )
    return api_response(result)


@router.post("/install")
@handle_admin_errors_wrap("[Plugin] install 失败", message="安装失败: {e}", exc_info=True, response_func=api_response)
async def plugin_install(request: Request, req: InstallRequest):
    workspace_id = get_workspace_id_from_auth_header(request.headers.get("Authorization", ""))
    user_id = _user_id(request)
    service = PluginMarketplaceService()
    result = await service.install_plugin(
        plugin_id=req.plugin_id,
        workspace_id=workspace_id,
        user_id=user_id,
        config=req.config,
    )
    return api_response(result)


@router.post("/uninstall")
@handle_admin_errors_wrap("[Plugin] uninstall 失败", message="卸载失败: {e}", exc_info=True, response_func=api_response)
async def plugin_uninstall(request: Request, req: UninstallRequest):
    workspace_id = get_workspace_id_from_auth_header(request.headers.get("Authorization", ""))
    user_id = _user_id(request)
    service = PluginMarketplaceService()
    ok = await service.uninstall_plugin(req.install_id, workspace_id=workspace_id, user_id=user_id)
    if not ok:
        return api_response(None, message="安装记录不存在", success=False)
    return api_response({"uninstalled": req.install_id})


@router.post("/installed")
@handle_admin_errors_wrap("[Plugin] installed 失败", message="查询失败: {e}", exc_info=True, response_func=api_response)
async def plugin_installed(
    request: Request,
    workspace_id: Optional[int] = Query(None, description="按工作空间筛选（仅 admin 有效）"),
):
    effective_ws = _effective_workspace(request, workspace_id)
    user_id = _user_id(request)
    service = PluginMarketplaceService()
    result = service.list_installed(workspace_id=effective_ws, user_id=user_id)
    return api_response({"list": result, "total": len(result)})


@router.post("/toggle")
@handle_admin_errors_wrap("[Plugin] toggle 失败", message="操作失败: {e}", exc_info=True, response_func=api_response)
async def plugin_toggle(req: ToggleRequest):
    service = PluginMarketplaceService()
    ok = service.set_enabled(req.install_id, req.enabled)
    if not ok:
        return api_response(None, message="安装记录不存在", success=False)
    return api_response({"install_id": req.install_id, "enabled": req.enabled})


# ─────────────────── Plugin Manager 统一入口 ───────────────────

@router.get("/stats")
@handle_admin_errors_wrap("[Plugin] stats 失败", message="统计失败: {e}", exc_info=True, response_func=api_response)
async def plugin_stats(
    request: Request,
    workspace_id: Optional[int] = Query(None, description="按工作空间筛选（仅 admin 有效）"),
):
    """全局插件统计（各类插件数量、运行时资源占用）。"""
    from services.plugin_manager import PluginManager
    effective_ws = _effective_workspace(request, workspace_id)
    user_id = _user_id(request)
    mgr = PluginManager.get_instance()
    result = mgr.stats(workspace_id=effective_ws, user_id=user_id)
    return api_response(result)


@router.get("/installed/detail")
@handle_admin_errors_wrap("[Plugin] installed detail 失败", message="查询失败: {e}", exc_info=True, response_func=api_response)
async def plugin_installed_detail(
    request: Request,
    workspace_id: Optional[int] = Query(None, description="按工作空间筛选（仅 admin 有效）"),
):
    """已安装列表（附带运行时状态：进程数 / venv 是否存在 / 工具是否加载）。"""
    from services.plugin_manager import PluginManager
    effective_ws = _effective_workspace(request, workspace_id)
    user_id = _user_id(request)
    mgr = PluginManager.get_instance()
    result = mgr.list_installed(workspace_id=effective_ws, user_id=user_id)
    return api_response({"list": result, "total": len(result)})


@router.post("/reload-all")
@handle_admin_errors_wrap("[Plugin] reload-all 失败", message="重载失败: {e}", exc_info=True, response_func=api_response)
async def plugin_reload_all():
    """热重载所有已安装插件（reload_config + MCP 进程池重置）。"""
    from services.plugin_manager import PluginManager
    mgr = PluginManager.get_instance()
    result = await mgr.reload_all()
    return api_response(result)
