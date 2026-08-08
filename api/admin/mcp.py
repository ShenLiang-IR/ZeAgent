"""MCP 管理 API 路由。

路径前缀 /mcp（挂在 admin_router /api/admin 下 → /api/admin/mcp/*）。
请求/响应采用 smart-agent 风格（驼峰字段 + {code,message,data}）。
"""
from ._error_handler import handle_admin_errors_wrap
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, Query, Depends
from pydantic import BaseModel, Field
from services.mcp_service import McpService
from infrastructure.database.repositories.mcp_repository import McpIntfcRepository
from utils.common.auth_dependencies import get_workspace_id_from_auth_header, get_current_user_permissions
from utils.common.visibility import can_read_object, can_modify_object
from .common import verify_token

router = APIRouter(prefix="/mcp", tags=["mcp"], dependencies=[Depends(verify_token)])


def api_response(data: Any = None, message: str = "success", success: bool = True) -> Dict[str, Any]:
    return {
        "code": "0000000000000000" if success else "9999999999999999",
        "message": message,
        "data": data,
    }


def _extract_viewer(request: Request, authorization: str = None):
    """从 token 提取 (user_id, workspace_id, is_admin)；无 token 时 admin 视为 False。"""
    auth = authorization or request.headers.get("Authorization", "")
    is_admin = False
    uid = None
    try:
        perms = get_current_user_permissions(auth)
        is_admin = perms.has_role("admin")
        if str(perms.user_id).isdigit():
            uid = int(perms.user_id)
    except Exception:
        pass
    ws = get_workspace_id_from_auth_header(auth)
    return uid, ws, is_admin


class PageQuery(BaseModel):
    page_no: int = Field(1, alias="pageNo", ge=1)
    page_size: int = Field(10, alias="pageSize", ge=1, le=100)
    mcp_name: Optional[str] = Field(None, alias="mcpName")
    status: Optional[str] = None

    class Config:
        populate_by_name = True


class IdRequest(BaseModel):
    pr_key_id: str = Field(..., alias="prKeyId")

    class Config:
        populate_by_name = True


class RegisterRequest(BaseModel):
    mcp_name: str = Field(..., alias="mcpName")
    description: Optional[str] = ""
    category: Optional[str] = ""
    connection_type: str = Field("stdio", alias="connectionType")
    connection_url: Optional[str] = Field("", alias="connectionUrl")
    exec_cmd: Optional[str] = Field("", alias="execCmd")
    auth_info: Optional[str] = Field("", alias="authInfo")
    timeout: Optional[int] = 30000
    params: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = True
    visibility: Optional[str] = Field(None, description="可见性 private/workspace/public")

    class Config:
        populate_by_name = True


class UpdateRequest(BaseModel):
    pr_key_id: str = Field(..., alias="prKeyId")
    mcp_name: Optional[str] = Field(None, alias="mcpName")
    description: Optional[str] = None
    category: Optional[str] = None
    connection_type: Optional[str] = Field(None, alias="connectionType")
    connection_url: Optional[str] = Field(None, alias="connectionUrl")
    exec_cmd: Optional[str] = Field(None, alias="execCmd")
    auth_info: Optional[str] = Field(None, alias="authInfo")
    timeout: Optional[int] = None
    params: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    visibility: Optional[str] = Field(None, description="可见性 private/workspace/public")

    class Config:
        populate_by_name = True


class UpdateStatusRequest(BaseModel):
    pr_key_id: str = Field(..., alias="prKeyId")
    status: str

    class Config:
        populate_by_name = True


class TestConnectRequest(BaseModel):
    connection_type: str = Field("stdio", alias="connectionType")
    connection_url: Optional[str] = Field("", alias="connectionUrl")
    exec_cmd: Optional[str] = Field("", alias="execCmd")
    auth_info: Optional[str] = Field("", alias="authInfo")
    timeout: Optional[int] = 30000
    params: Optional[Dict[str, Any]] = None

    class Config:
        populate_by_name = True


class IntfcPageRequest(BaseModel):
    mcp_id: str = Field(..., alias="mcpId")
    page_no: int = Field(1, alias="pageNo", ge=1)
    page_size: int = Field(10, alias="pageSize", ge=1, le=100)

    class Config:
        populate_by_name = True


class IntfcSyncRequest(BaseModel):
    pr_key_id: str = Field(..., alias="prKeyId")

    class Config:
        populate_by_name = True


@router.post("/page")
@handle_admin_errors_wrap("[MCP] page 失败", message="查询失败: {e}", exc_info=True, response_func=api_response)
async def mcp_page(
    request: Request,
    req: PageQuery,
    workspace_id: int | None = Query(None, description="按工作空间筛选（仅 admin 有效，覆盖当前空间；None=全部空间）"),
):
    # admin 用 query 覆盖（None=全部空间，传值=该空间聚合）；非 admin 走三层可见性（防越权）
    is_admin = False
    perms = None
    try:
        perms = get_current_user_permissions(request.headers.get("Authorization", ""))
        is_admin = perms.has_role("admin")
    except Exception:
        pass
    service = McpService()
    if is_admin:
        result = service.page(
            page_no=req.page_no,
            page_size=req.page_size,
            mcp_name=req.mcp_name,
            status=req.status,
            workspace_id=workspace_id,
            is_admin=True,
        )
    else:
        ws = get_workspace_id_from_auth_header(request.headers.get("Authorization", ""))
        uid = int(perms.user_id) if perms and str(perms.user_id).isdigit() else None
        result = service.page(
            page_no=req.page_no,
            page_size=req.page_size,
            mcp_name=req.mcp_name,
            status=req.status,
            viewer_user_id=uid,
            viewer_workspace_id=ws,
            is_admin=False,
        )
    return api_response(result)


@router.post("/detail")
@handle_admin_errors_wrap("[MCP] detail 失败", message="查询失败: {e}", exc_info=True, response_func=api_response)
async def mcp_detail(request: Request, req: IdRequest):
    service = McpService()
    result = service.detail(req.pr_key_id)
    if result is None:
        return api_response(None, message="MCP 不存在", success=False)
    # 三层可见性读校验
    mcp = result.get("mcp", {})
    uid, ws, is_admin = _extract_viewer(request)
    if not can_read_object(
        mcp.get("visibility") or "", mcp.get("creator_id"), mcp.get("workspace_id"),
        uid, ws, is_admin,
    ):
        return api_response(None, message="无权访问该 MCP", success=False)
    return api_response(result)


@router.post("/register")
@handle_admin_errors_wrap("[MCP] register 失败", message="创建失败: {e}", exc_info=True, response_func=api_response)
async def mcp_register(request: Request, req: RegisterRequest):
    workspace_id = get_workspace_id_from_auth_header(request.headers.get("Authorization", ""))
    creator_id = None
    try:
        perms = get_current_user_permissions(request.headers.get("Authorization", ""))
        if str(perms.user_id).isdigit():
            creator_id = int(perms.user_id)
    except Exception:
        pass
    service = McpService()
    result = service.register(
        mcp_name=req.mcp_name,
        description=req.description or "",
        category=req.category or "",
        connection_type=req.connection_type,
        connection_url=req.connection_url or "",
        exec_cmd=req.exec_cmd or "",
        auth_info=req.auth_info or "",
        timeout=req.timeout or 30000,
        params=req.params,
        enabled=True if req.enabled is None else req.enabled,
        workspace_id=workspace_id,
        creator_id=creator_id,
        visibility=req.visibility,
    )
    return api_response(result, message="创建成功")


@router.post("/update")
@handle_admin_errors_wrap("[MCP] update 失败", message="更新失败: {e}", exc_info=True, response_func=api_response)
async def mcp_update(request: Request, req: UpdateRequest):
    service = McpService()
    # 三层可见性修改校验：先取对象，校验 can_modify_object
    existing = service.detail(req.pr_key_id)
    if not existing:
        return api_response(None, message="MCP 不存在或更新失败", success=False)
    mcp = existing.get("mcp", {})
    uid, ws, is_admin = _extract_viewer(request)
    if not can_modify_object(
        mcp.get("visibility") or "", mcp.get("creator_id"), mcp.get("workspace_id"),
        uid, ws, is_admin,
    ):
        return api_response(None, message="无权修改该 MCP", success=False)
    data = req.model_dump(exclude_none=True, by_alias=False)
    pr_key_id = data.pop("pr_key_id")
    ok = service.update(pr_key_id, **data)
    if not ok:
        return api_response(None, message="MCP 不存在或更新失败", success=False)
    return api_response(None, message="更新成功")


@router.post("/updateStatus")
@handle_admin_errors_wrap("[MCP] updateStatus 失败", message="状态更新失败: {e}", exc_info=True, response_func=api_response)
async def mcp_update_status(request: Request, req: UpdateStatusRequest):
    service = McpService()
    existing = service.detail(req.pr_key_id)
    if not existing:
        return api_response(None, message="MCP 不存在", success=False)
    mcp = existing.get("mcp", {})
    uid, ws, is_admin = _extract_viewer(request)
    if not can_modify_object(
        mcp.get("visibility") or "", mcp.get("creator_id"), mcp.get("workspace_id"),
        uid, ws, is_admin,
    ):
        return api_response(None, message="无权修改该 MCP", success=False)
    ok = service.update_status(req.pr_key_id, req.status)
    if not ok:
        return api_response(None, message="MCP 不存在", success=False)
    return api_response(None, message="状态更新成功")


@router.post("/delete")
@handle_admin_errors_wrap("[MCP] delete 失败", message="删除失败: {e}", exc_info=True, response_func=api_response)
async def mcp_delete(request: Request, req: IdRequest):
    service = McpService()
    existing = service.detail(req.pr_key_id)
    if not existing:
        return api_response(None, message="MCP 不存在", success=False)
    mcp = existing.get("mcp", {})
    uid, ws, is_admin = _extract_viewer(request)
    if not can_modify_object(
        mcp.get("visibility") or "", mcp.get("creator_id"), mcp.get("workspace_id"),
        uid, ws, is_admin,
    ):
        return api_response(None, message="无权删除该 MCP", success=False)
    ok = service.delete(req.pr_key_id)
    if not ok:
        return api_response(None, message="MCP 不存在", success=False)
    return api_response(None, message="删除成功")


@router.post("/testConnect")
@handle_admin_errors_wrap("[MCP] testConnect 失败", message="连接失败: {e}", exc_info=True, response_func=api_response)
async def mcp_test_connect(req: TestConnectRequest):
    service = McpService()
    tools = await service.test_connect(
        connection_type=req.connection_type,
        exec_cmd=req.exec_cmd or "",
        connection_url=req.connection_url or "",
        params=req.params,
        auth_info=req.auth_info or "",
        timeout=req.timeout or 30000,
    )
    return api_response({"tools": tools, "total": len(tools)})


@router.post("/intfc/page")
@handle_admin_errors_wrap("[MCP] intfc page 失败", message="查询失败: {e}", exc_info=True, response_func=api_response)
async def mcp_intfc_page(req: IntfcPageRequest):
    repo = McpIntfcRepository()
    all_items = repo.get_by_mcp_id(req.mcp_id) or []
    total = len(all_items)
    start = (req.page_no - 1) * req.page_size
    end = start + req.page_size
    return api_response({
        "list": all_items[start:end],
        "total": total,
        "pageNo": req.page_no,
        "pageSize": req.page_size,
    })


@router.post("/intfc/sync")
@handle_admin_errors_wrap("[MCP] intfc sync 失败", message="同步失败: {e}", exc_info=True, response_func=api_response)
async def mcp_intfc_sync(req: IntfcSyncRequest):
    service = McpService()
    result = await service.sync_interfaces(req.pr_key_id)
    return api_response(result, message=f"同步完成，共 {result['synced']} 个接口")
