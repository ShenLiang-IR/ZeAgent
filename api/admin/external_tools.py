import json
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
from loguru import logger
from utils.config import get_config_db
from ._error_handler import handle_admin_errors
from .common import verify_token
from .permissions import require_read, require_write
from utils.common.permissions import UserPermissions
from utils.common.auth_dependencies import get_workspace_id_from_auth_header, get_current_user_permissions
from utils.common.visibility import can_read_object, can_modify_object
router = APIRouter(tags=["admin"])


def _extract_viewer(request: Request, user_permissions: UserPermissions = None):
    """从 token/permissions 提取 (user_id, workspace_id, is_admin)。"""
    auth = request.headers.get("Authorization", "")
    if user_permissions:
        is_admin = user_permissions.has_role("admin")
        uid = int(user_permissions.user_id) if str(user_permissions.user_id).isdigit() else None
    else:
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
def _validate_tool_config(config_db, api_base_url, http_config_name):
    api_base_url = api_base_url or ""
    http_config_name = http_config_name or ""
    if not api_base_url and not http_config_name:
        raise HTTPException(status_code=400, detail="api_base_urlhttp_config_name")
    if not api_base_url and http_config_name:
        http_config = config_db.http_configs.get_by_name(http_config_name)
        if not http_config:
            raise HTTPException(status_code=400, detail=f"HTTP: {http_config_name}")
class ExternalToolParameter(BaseModel):
    param_name: str
    param_type: str = "string"
    required: bool = False
    default_value: Optional[str] = None
    description: str = ""
    param_location: str = "body"
    validation_rules: Optional[Dict[str, Any]] = {}
    param_order: int = 0
class ExternalToolConfig(BaseModel):
    name: str
    display_name: Optional[str] = ""
    description: Optional[str] = ""
    parameter_descriptions: Optional[Dict[str, str]] = {}
    return_description: Optional[str] = ""
    examples: Optional[List[str]] = []
    api_base_url: Optional[str] = ""
    api_endpoint: str
    method: Optional[str] = "POST"
    headers: Optional[Dict[str, str]] = {}
    http_config_name: Optional[str] = ""
    enabled: Optional[bool] = True
    visibility: Optional[str] = "private"
    parameter_list: Optional[List[ExternalToolParameter]] = []
@router.get("/external-tools")
@handle_admin_errors("ExternalTools", detail_with_context=False, exc_info=True)
async def get_external_tools(
    request: Request,
    user_permissions: UserPermissions = Depends(require_read("external_tool")),
    skip: int = Query(0, ge=0, description=""),
    limit: int = Query(10, ge=1, le=100, description=""),
    search: str = Query("", description=""),
    enabled: bool = Query(True, description="")
):
    is_admin = user_permissions.has_role("admin")
    config_db = get_config_db()
    if is_admin:
        all_tools = config_db.external_tools.get_all(is_admin=True) or []
    else:
        workspace_id = get_workspace_id_from_auth_header(request.headers.get("Authorization", ""))
        uid = int(user_permissions.user_id) if str(user_permissions.user_id).isdigit() else None
        all_tools = config_db.external_tools.get_all(
            viewer_user_id=uid, viewer_workspace_id=workspace_id, is_admin=False,
        ) or []
    filtered_tools = [
        t for t in all_tools
        if t.get('enabled', True) == enabled
    ]
    if search:
        search_lower = search.lower()
        filtered_tools = [
            t for t in filtered_tools
            if (
                search_lower in str(t.get('name', '')).lower() or
                search_lower in str(t.get('display_name', '')).lower() or
                search_lower in str(t.get('description', '')).lower()
            )
        ]
    total = len(filtered_tools)
    paginated = filtered_tools[skip : skip + limit]
    return {
        "success": True,
        "tools": paginated,
        "total": total,
        "count": len(paginated),
        "skip": skip,
        "limit": limit,
        "enabled": enabled
    }
@router.get("/external-tools/{name}")
@handle_admin_errors("ExternalTools", detail_with_context=False, exc_info=True)
async def get_external_tool(
    name: str,
    request: Request,
    user_permissions: UserPermissions = Depends(require_read("external_tool")),
):
    config_db = get_config_db()
    tool_config = config_db.external_tools.get_by_name(name, return_format='external_tool')
    if not tool_config:
        raise HTTPException(status_code=404, detail=f"外部工具不存在: {name}")
    # 三层可见性读校验
    uid, ws, is_admin = _extract_viewer(request, user_permissions)
    if not can_read_object(
        tool_config.get("visibility") or "", tool_config.get("creator_id"),
        tool_config.get("workspace_id"), uid, ws, is_admin,
    ):
        raise HTTPException(status_code=403, detail="无权访问该外部工具")
    return {
        "success": True,
        "tool": tool_config
    }
@router.post("/external-tools")
@handle_admin_errors("ExternalTools", detail_with_context=False, exc_info=True)
async def create_external_tool(
    request: Request,
    config: ExternalToolConfig,
    user_permissions: UserPermissions = Depends(require_write("external_tool")),
):
    config_db = get_config_db()
    existing = config_db.external_tools.get_by_name(config.name)
    if existing:
        raise HTTPException(status_code=400, detail=f"外部工具已存在: {config.name}")
    _validate_tool_config(config_db, config.api_base_url, config.http_config_name)
    workspace_id = get_workspace_id_from_auth_header(request.headers.get("Authorization", ""))
    creator_id = int(user_permissions.user_id) if str(user_permissions.user_id).isdigit() else None
    config_dict = config.model_dump()
    config_db.external_tools.save_external_tool_config(
        name=config.name,
        display_name=config.display_name,
        description=config.description,
        parameter_descriptions=config.parameter_descriptions or {},
        return_description=config.return_description or "",
        examples=config.examples or [],
        api_base_url=config.api_base_url or "",
        api_endpoint=config.api_endpoint,
        method=config.method,
        headers=config.headers,
        enabled=config.enabled,
        config_json=json.dumps(config_dict, ensure_ascii=False),
        http_config_name=config.http_config_name or "",
        workspace_id=workspace_id,
        creator_id=creator_id,
        visibility=config.visibility or "private",
    )
    return {
        "success": True,
        "message": f": {config.name}"
    }
@router.put("/external-tools/{name}")
@handle_admin_errors("ExternalTools", detail_with_context=False, exc_info=True)
async def update_external_tool(
    name: str,
    config: ExternalToolConfig,
    request: Request,
    user_permissions: UserPermissions = Depends(require_write("external_tool")),
):
    config_db = get_config_db()
    existing = config_db.external_tools.get_by_name(name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"外部工具不存在: {name}")
    # 三层可见性修改校验
    uid, ws, is_admin = _extract_viewer(request, user_permissions)
    if not can_modify_object(
        existing.get("visibility") or "", existing.get("creator_id"),
        existing.get("workspace_id"), uid, ws, is_admin,
    ):
        raise HTTPException(status_code=403, detail="无权修改该外部工具")
    if name != config.name:
        existing_new = config_db.external_tools.get_by_name(config.name)
        if existing_new:
            raise HTTPException(status_code=400, detail=f"外部工具已存在: {config.name}")
        config_db.external_tools.delete_api_by_name(name)
    _validate_tool_config(config_db, config.api_base_url, config.http_config_name)
    config_dict = config.model_dump()
    config_db.external_tools.save_external_tool_config(
        name=config.name,
        display_name=config.display_name,
        description=config.description,
        parameter_descriptions=config.parameter_descriptions or {},
        return_description=config.return_description or "",
        examples=config.examples or [],
        api_base_url=config.api_base_url or "",
        api_endpoint=config.api_endpoint,
        method=config.method,
        headers=config.headers,
        enabled=config.enabled,
        config_json=json.dumps(config_dict, ensure_ascii=False),
        http_config_name=config.http_config_name or "",
        # B3：保留原归属（workspace/creator），visibility 用前端传入值
        workspace_id=existing.get("workspace_id"),
        creator_id=existing.get("creator_id"),
        visibility=config.visibility or "private",
    )
    return {
        "success": True,
        "message": f": {config.name}"
    }
@router.delete("/external-tools/{name}")
@handle_admin_errors("ExternalTools", detail_with_context=False, exc_info=True)
async def delete_external_tool(
    name: str,
    request: Request,
    token: str = Depends(verify_token)
):
    config_db = get_config_db()
    existing = config_db.external_tools.get_by_name(name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"外部工具不存在: {name}")
    # 三层可见性删除校验
    uid, ws, is_admin = _extract_viewer(request)
    if not can_modify_object(
        existing.get("visibility") or "", existing.get("creator_id"),
        existing.get("workspace_id"), uid, ws, is_admin,
    ):
        raise HTTPException(status_code=403, detail="无权删除该外部工具")
    deleted = config_db.external_tools.delete_api_by_name(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"外部工具不存在: {name}")
    return {
        "success": True,
        "message": f": {name}"
    }
@router.post("/external-tools/import")
async def import_external_tools(
    files: List[UploadFile] = File(...),
    token: str = Depends(verify_token)
):
    try:
        if not files:
            raise HTTPException(status_code=400, detail="未提供导入文件")
        config_db = get_config_db()
        imported = []
        failed = []
        file_errors = []
        for file in files:
            if not file.filename:
                file_errors.append("")
                continue
            try:
                content = await file.read()
                data = json.loads(content.decode('utf-8'))
                external_tools = data.get('external_tools', [])
                if not external_tools:
                    file_errors.append(f"{file.filename}: JSON")
                    continue
                for tool_config in external_tools:
                    try:
                        tool_name = tool_config.get('name')
                        if not tool_name:
                            failed.append({
                                "name": "",
                                "error": "",
                                "file": file.filename
                            })
                            continue
                        config_db.external_tools.save_external_tool_config(
                            name=tool_name,
                            display_name=tool_config.get('display_name', ''),
                            description=tool_config.get('description', ''),
                            parameter_descriptions=tool_config.get('parameter_descriptions', {}),
                            return_description=tool_config.get('return_description', ''),
                            examples=tool_config.get('examples', []),
                            api_base_url=tool_config.get('api_base_url', ''),
                            api_endpoint=tool_config.get('api_endpoint', ''),
                            method=tool_config.get('method', 'POST'),
                            headers=tool_config.get('headers', {}),
                            enabled=tool_config.get('enabled', True),
                            config_json=json.dumps(tool_config, ensure_ascii=False),
                            http_config_name=tool_config.get('http_config_name', '')
                        )
                        parameter_list = tool_config.get('parameter_list', [])
                        if parameter_list:
                            config_db.external_tools.delete_all_tool_parameters(tool_name)
                            for param in parameter_list:
                                try:
                                    config_db.external_tools.save_tool_parameter(
                                        tool_name=tool_name,
                                        param_name=param.get('param_name', ''),
                                        param_type=param.get('param_type', 'string'),
                                        required=param.get('required', False),
                                        default_value=param.get('default_value'),
                                        description=param.get('description', ''),
                                        param_location=param.get('param_location', 'body'),
                                        validation_rules=param.get('validation_rules', {}),
                                        param_order=param.get('param_order', 0)
                                    )
                                except Exception as param_error:
                                    logger.warning(f"导入工具 {tool_name} 参数 {param.get('param_name')} 失败: {param_error}")
                        imported.append(tool_name)
                    except Exception as e:
                        failed.append({
                            "name": tool_config.get('name', ''),
                            "error": str(e),
                            "file": file.filename
                        })
            except json.JSONDecodeError as e:
                file_errors.append(f"{file.filename}: JSON - {str(e)}")
            except Exception as e:
                file_errors.append(f"{file.filename}:  - {str(e)}")
        if file_errors:
            for error in file_errors:
                failed.append({
                    "name": "",
                    "error": error,
                    "file": "N/A"
                })
        message = f"成功导入 {len(imported)} 个"
        if file_errors:
            message += f"，文件错误 {len(file_errors)} 个"
        if failed:
            message += f"{len([f for f in failed if f.get('name') != ''])} "
        return {
            "success": True,
            "message": message,
            "imported": imported,
            "failed": failed,
            "count": len(imported)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"外部工具导入失败: {str(e)}")
@router.post("/external-tools/export")
@handle_admin_errors("ExternalTools", detail_with_context=False, exc_info=True)
async def export_external_tools(token: str = Depends(verify_token)):
    config_db = get_config_db()
    all_tools = config_db.external_tools.get_all()
    if not all_tools:
        raise HTTPException(status_code=404, detail="无可导出的外部工具")
    export_data = {"external_tools": all_tools}
    json_string = json.dumps(export_data, ensure_ascii=False, indent=2)
    return Response(
        content=json_string,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=external_tools.json"}
    )
@router.get("/external-tools/{name}/parameters")
@handle_admin_errors("ExternalTools", detail_with_context=False, exc_info=True)
async def get_tool_parameters(name: str, token: str = Depends(verify_token)):
    config_db = get_config_db()
    tool_config = config_db.external_tools.get_by_name(name)
    if not tool_config:
        raise HTTPException(status_code=404, detail=f"外部工具不存在: {name}")
    parameters = config_db.external_tools.get_tool_parameters(name)
    return {
        "success": True,
        "parameters": parameters,
        "count": len(parameters)
    }
@router.post("/external-tools/{name}/parameters")
@handle_admin_errors("ExternalTools", detail_with_context=False, exc_info=True)
async def create_tool_parameter(
    name: str,
    parameter: ExternalToolParameter,
    token: str = Depends(verify_token)
):
    config_db = get_config_db()
    tool_config = config_db.external_tools.get_by_name(name)
    if not tool_config:
        raise HTTPException(status_code=404, detail=f"外部工具不存在: {name}")
    config_db.external_tools.save_tool_parameter(
        tool_name=name,
        param_name=parameter.param_name,
        param_type=parameter.param_type,
        required=parameter.required,
        default_value=parameter.default_value,
        description=parameter.description,
        param_location=parameter.param_location,
        validation_rules=parameter.validation_rules or {},
        param_order=parameter.param_order
    )
    return {
        "success": True,
        "message": f": {parameter.param_name}"
    }
@router.put("/external-tools/{name}/parameters/{param_name}")
@handle_admin_errors("ExternalTools", detail_with_context=False, exc_info=True)
async def update_tool_parameter(
    name: str,
    param_name: str,
    parameter: ExternalToolParameter,
    token: str = Depends(verify_token)
):
    config_db = get_config_db()
    tool_config = config_db.external_tools.get_by_name(name)
    if not tool_config:
        raise HTTPException(status_code=404, detail=f"外部工具不存在: {name}")
    if param_name != parameter.param_name:
        config_db.external_tools.delete_tool_parameter(name, param_name)
    config_db.external_tools.save_tool_parameter(
        tool_name=name,
        param_name=parameter.param_name,
        param_type=parameter.param_type,
        required=parameter.required,
        default_value=parameter.default_value,
        description=parameter.description,
        param_location=parameter.param_location,
        validation_rules=parameter.validation_rules or {},
        param_order=parameter.param_order
    )
    return {
        "success": True,
        "message": f": {parameter.param_name}"
    }
@router.delete("/external-tools/{name}/parameters/{param_name}")
@handle_admin_errors("ExternalTools", detail_with_context=False, exc_info=True)
async def delete_tool_parameter(
    name: str,
    param_name: str,
    token: str = Depends(verify_token)
):
    config_db = get_config_db()
    deleted = config_db.external_tools.delete_tool_parameter(name, param_name)
    if not deleted:
        raise HTTPException(status_code=404,                     detail=f"外部工具参数不存在: {name}/{param_name}")
    return {
        "success": True,
        "message": f": {param_name}"
    }