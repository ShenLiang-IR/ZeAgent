import json
import uuid
from typing import List, Optional
from fastapi import HTTPException, Depends, UploadFile, File, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, ConfigDict
from utils.config import get_config_db
from utils.config.mode_helper import set_preview_context, clear_preview_context
from .common import ModeConfig
from .permissions import require_read, require_manage
from .base import create_crud_router, handle_import_files, handle_export_all, wrap_response
from utils.common.permissions import UserPermissions
from ._error_handler import handle_admin_errors
class ModePreviewRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    system_prompt_suffix: str
    recommended_agents: str = Field(default="", alias="recommendedAgents")
    priority_agent: str = Field(default="", alias="priorityAgent")
    test_text: str
def _check_system_mode_protection(id_value: str, operation: str = "") -> None:
    config_db = get_config_db()
    mode = config_db.modes.get_by_name(id_value)
    if not mode:
        mode = config_db.modes.get_by_id(id_value)
    if mode and mode.get('mode_type') == '':
        mode_name = mode.get('mode_name', mode.get('name', id_value))
        raise HTTPException(
            status_code=403,
            detail=f" '{mode_name}' {operation}"
        )
async def _update_mode_with_protection(id_value: str, data: ModeConfig) -> bool:
    """更新模式：先检查系统模式保护，再调用 save_mode 做真正更新。

    优先用 data.pr_key_id（前端编辑表单从 row 携带），
    避免 update_item 中 repository.delete 硬删除后 get_by_name 找不到记录。
    """
    _check_system_mode_protection(id_value, "")
    config_db = get_config_db()
    pr_key_id = data.pr_key_id
    if not pr_key_id:
        mode = config_db.modes.get_by_name(id_value) or config_db.modes.get_by_id(id_value, return_dict=True)
        if not mode:
            return False
        pr_key_id = mode.get('pr_key_id') if isinstance(mode, dict) else getattr(mode, 'pr_key_id', None)
    return config_db.modes.save_mode(
        pr_key_id=pr_key_id,
        mode_name=data.mode_name,
        en_name=data.en_name,
        mode_description=data.mode_description,
        system_prompt=data.system_prompt,
        recommended_agents=data.recommended_agents,
        priority_agent=data.priority_agent,
        enabled=data.enabled,
        mode_type=data.mode_type,
    )
async def _delete_mode_with_protection(id_value: str) -> bool:
    """删除模式：先检查系统模式保护，再调用 delete_mode 做软删除。

    id_value 可能是 mode_name 或 pr_key_id，需先查出 pr_key_id 再传给 delete_mode。
    """
    _check_system_mode_protection(id_value, "")
    config_db = get_config_db()
    mode = config_db.modes.get_by_name(id_value) or config_db.modes.get_by_id(id_value, return_dict=True)
    if not mode:
        return False
    pr_key_id = mode.get('pr_key_id') if isinstance(mode, dict) else getattr(mode, 'pr_key_id', None)
    return config_db.modes.delete_mode(pr_key_id)
router = create_crud_router(
    repository=get_config_db().modes,
    resource_name="mode",
    create_schema=ModeConfig,
    update_schema=ModeConfig,
    tags=["admin"],
    prefix="/modes",
    id_field="mode_name",
    update_func=_update_mode_with_protection,
    delete_func=_delete_mode_with_protection
)
# 移除 create_crud_router 注册的默认 GET list 路由（path=/modes），
# 让下方 list_agent_modes（自定义搜索逻辑，搜索 dclr_ptn_name 等数据库列名）生效。
# 之前条件 path=='' 不匹配（实际 path=/modes），导致默认路由覆盖 list_agent_modes，
# 搜索用 search_fields=["name","display_name","description"]（不存在于 _entity_to_dict）→ 静默失败。
if router.routes and hasattr(router.routes[0], 'path') and router.routes[0].path == '/modes':
    router.routes.pop(0)
@router.get("")
@handle_admin_errors("", detail_with_context=True)
async def list_agent_modes(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    search: str = Query(""),
    enabled: Optional[bool] = Query(None),
    user_permissions: UserPermissions = Depends(require_read("mode"))
):
    config_db = get_config_db()
    all_items = config_db.modes.get_by_type('Agent') or []
    if enabled is not None:
        target_val = 1 if enabled else 0
        all_items = [
            m for m in all_items
            if m.get("enabled") == target_val or m.get("enabled") is enabled
        ]
    if search:
        s = search.lower()
        all_items = [
            m for m in all_items
            if any(s in str(m.get(f, "")).lower() for f in ["dclr_ptn_name", "en_name", "thval_desc_desc"])
        ]
    total = len(all_items)
    paginated = all_items[skip : skip + limit]
    return wrap_response({
        "modes": paginated,
        "total": total,
        "count": len(paginated),
        "skip": skip,
        "limit": limit
    })
@router.post("/import")
async def import_modes(
    files: List[UploadFile] = File(...),
    user_permissions: UserPermissions = Depends(require_manage("mode"))
):
    config_db = get_config_db()
    def import_mode_func(data):
        mode_name = data.get('mode_name') or data.get('name')
        if not mode_name:
            raise ValueError("mode_name")
        from utils.id_generator import generate_uuid
        success = config_db.modes.save_mode(
            pr_key_id=generate_uuid(),
            mode_name=mode_name,
            en_name=data.get('en_name') or data.get('display_name', ''),
            mode_description=data.get('mode_description') or data.get('description', ''),
            system_prompt=data.get('system_prompt') or data.get('system_prompt_suffix', ''),
            recommended_agents=data.get('recommended_agents', ''),
            priority_agent=data.get('priority_agent', ''),
            enabled=data.get('enabled', True),
            mode_type=data.get('mode_type', 'Agent'),
        )
        return {"mode_name": mode_name, "action": "" if success else ""}
    return await handle_import_files(
        files=files,
        import_func=import_mode_func,
        resource_name="mode"
    )
@router.post("/{name}/export")
async def export_mode(name: str, user_permissions: UserPermissions = Depends(require_read("mode"))):
    mode = get_config_db().modes.get_by_name(name)
    if not mode:
        raise HTTPException(status_code=404, detail=f"模式不存在: {name}")
    export_data = {k: v for k, v in mode.items() if k not in ['id', 'created_at', 'updated_at', 'enabled', 'config_json']}
    return Response(
        content=json.dumps(export_data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}.json"'}
    )
@router.post("/export-all")
async def export_all_modes(user_permissions: UserPermissions = Depends(require_read("mode"))):
    modes = get_config_db().modes.get_all()
    return handle_export_all(modes, "mode", "agent_modes")
@router.post("/preview")
async def preview_mode_config(
    request: ModePreviewRequest,
    user_permissions: UserPermissions = Depends(require_read("mode"))
):
    from loguru import logger
    from api.schemas import ChatRequest, ChatMessage
    from api.chat.chat_routes import chat
    logger.info(f"用户 {user_permissions.user_id} 预览模式配置")
    if not request.system_prompt_suffix.strip():
        raise HTTPException(status_code=400, detail="系统提示词后缀不能为空")
    if not request.test_text.strip():
        raise HTTPException(status_code=400, detail="测试文本不能为空")
    set_preview_context(
        system_prompt_suffix=request.system_prompt_suffix,
        recommended_agents=request.recommended_agents,
        priority_agent=request.priority_agent
    )
    try:
        chat_request = ChatRequest(
            messages=[ChatMessage(role="user", content=request.test_text)],
            session_id=f"preview_{uuid.uuid4().hex[:8]}",
            response_mode="__preview__",
            agent="default",
            deep_thinking=False
        )
        result = await chat(chat_request, authorization=None)
        return wrap_response(data={
            "response": result.get("content", ""),
            "session_id": result.get("session_id", ""),
            "workflow_summary": result.get("workflow_summary", {})
        })
    finally:
        clear_preview_context()
@router.get("/system")
async def get_system_modes(user_permissions: UserPermissions = Depends(require_read("mode"))):
    config_db = get_config_db()
    system_modes = config_db.modes.get_system_modes()
    return wrap_response({
        "modes": system_modes,
        "total": len(system_modes)
    })