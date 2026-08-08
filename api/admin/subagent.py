"""SubAgent 管理路由（已废弃，保留向后兼容）。

Agent 管理已迁移到 agent_manage.py（/api/admin/agents/*），
本路由通过 config_db.subagents = self.agents alias 桥接到 tb_agent 表。
前端路由已将 /subagents 重定向到 /agents，旧接口仍可用但不再维护。
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Query, Header
from fastapi.responses import Response
from loguru import logger
from utils.config import get_config_db
from .common import reload_config, SubAgentConfig, AgentConfigNew, verify_token
from .validators import validate_and_raise_tools
from ._error_handler import handle_admin_errors
from .permissions import require_read, require_write, require_delete, require_manage
from .base import handle_import_files, handle_export_all, wrap_response
from utils.common.permissions import UserPermissions
from utils.common.auth_dependencies import get_workspace_id_from_auth_header
def _check_tools_in_config_files(missing_tools: List[str]) -> Dict[str, List[str]]:
    agent_dir = Path(__file__).parent.parent.parent
    config_dir = agent_dir / "config"
    external_tool_files = [config_dir / "external_tools.json", config_dir / "bond_research_tools.json"]  # 这些文件已删除，仅保留兼容检查（exists() 返回 False 时自动跳过）
    result = {}
    for config_file in external_tool_files:
        if not config_file.exists():
            continue
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            external_tools = data.get('external_tools', [])
            tool_names = [tool.get('name') for tool in external_tools if isinstance(tool, dict) and tool.get('name')]
            found_tools = [tool for tool in missing_tools if tool in tool_names]
            if found_tools:
                result[str(config_file.relative_to(agent_dir))] = found_tools
        except Exception:
            continue
    return result
def agent_to_legacy_response(agent_dict: dict) -> dict:
    pr_key_id = agent_dict.get('pr_key_id', '')
    name = pr_key_id.replace('AGT_', '', 1) if pr_key_id.startswith('AGT_') else pr_key_id
    return {
        'name': name,
        'display_name': agent_dict.get('agent_name', ''),
        'description': agent_dict.get('agent_description', ''),
        'system_prompt': agent_dict.get('system_prompt', ''),
        'model': agent_dict.get('model_id'),
        'enabled': agent_dict.get('status') == '1',
        'tools': agent_dict.get('tools', []),
        'external_tools': agent_dict.get('external_tools', []),
        'mcp_tools': agent_dict.get('mcp_tools', []),
        'created_at': agent_dict.get('created_at'),
        'updated_at': agent_dict.get('updated_at')
    }
def legacy_to_agent_config(config: SubAgentConfig) -> AgentConfigNew:
    pr_key_id = config.name
    if not pr_key_id.startswith('AGT_'):
        pr_key_id = f'AGT_{config.name}'
    return AgentConfigNew(
        pr_key_id=pr_key_id,
        agent_name=config.display_name or config.name,
        agent_description=config.description or "",
        model_id=config.model,
        system_prompt=config.system_prompt,
        tools=config.tools or [],
        external_tools=config.external_tools or [],
        mcp_tools=config.mcp_tools or [],
        status='1' if config.enabled else '0'
    )
async def create_agent_logic(data: SubAgentConfig, creator_id: int | None = None,
                             workspace_id: int | None = None):
    validate_and_raise_tools(data.tools, data.external_tools)
    config_db = get_config_db()
    agent_config = legacy_to_agent_config(data)
    return config_db.subagents.save_agent(
        pr_key_id=agent_config.pr_key_id,
        agent_name=agent_config.agent_name,
        system_prompt=agent_config.system_prompt,
        tools=agent_config.tools,
        external_tools=agent_config.external_tools,
        mcp_tools=agent_config.mcp_tools,
        agent_description=agent_config.agent_description,
        model_id=agent_config.model_id,
        enabled=True,
        visibility=data.visibility,
        creator_id=creator_id,
        workspace_id=workspace_id,
    )
async def update_agent_logic(id_value: str, data: SubAgentConfig, workspace_id: int | None = None):
    validate_and_raise_tools(data.tools, data.external_tools)
    config_db = get_config_db()
    agent_config = legacy_to_agent_config(data)
    old_pr_key_id = f'AGT_{id_value}' if not id_value.startswith('AGT_') else id_value
    if old_pr_key_id != agent_config.pr_key_id:
        config_db.subagents.delete_agent(old_pr_key_id)
    return config_db.subagents.save_agent(
        pr_key_id=agent_config.pr_key_id,
        agent_name=agent_config.agent_name,
        system_prompt=agent_config.system_prompt,
        tools=agent_config.tools,
        external_tools=agent_config.external_tools,
        mcp_tools=agent_config.mcp_tools,
        agent_description=agent_config.agent_description,
        model_id=agent_config.model_id,
        enabled=True,
        visibility=data.visibility,
        workspace_id=workspace_id,
    )
router = APIRouter(prefix="/subagents", tags=["admin"], dependencies=[Depends(verify_token)])
config_db = get_config_db()


def _ensure_can_modify_agent(agent_id: str, authorization: Optional[str],
                             user_permissions: UserPermissions) -> None:
    """对象级写权限校验（三层可见性）：admin 全可改；创建者可改自己的；
    workspace 对象空间 owner 可改；否则 403。普通空间成员对 workspace 对象只读。
    """
    from utils.common.visibility import can_modify_object
    if user_permissions.has_role("admin"):
        return
    item = config_db.subagents.get_by_id(agent_id, return_dict=True)
    if not item:
        return  # 不存在交由后续 404 处理
    cur_uid = int(user_permissions.user_id) if str(user_permissions.user_id).isdigit() else None
    cur_ws = get_workspace_id_from_auth_header(authorization)
    # 简化：空间 owner 判定用 UserWorkspace.is_owner（此处暂以 creator 匹配 + admin 为主）
    allowed = can_modify_object(
        item.get("visibility") or "workspace",
        item.get("creator_id"),
        item.get("workspace_id"),
        cur_uid, cur_ws,
        is_admin=False, is_workspace_owner=False,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail=f"无权修改该 subagent: {agent_id}")
@router.get("")
@handle_admin_errors(" subagent ", detail_with_context=False)
async def list_items(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    search: str = Query(""),
    enabled: Optional[bool] = Query(None),
    authorization: Optional[str] = Header(None),
    user_permissions: UserPermissions = Depends(require_read("subagent"))
):
    from utils.common.visibility import can_read_object
    all_items = config_db.subagents.get_all() or []
    # 三层可见性过滤：admin 全可见；否则按 visibility + 创建者 + 空间成员过滤
    is_admin = user_permissions.has_role("admin")
    if not is_admin:
        cur_uid = int(user_permissions.user_id) if str(user_permissions.user_id).isdigit() else None
        cur_ws = get_workspace_id_from_auth_header(authorization)
        all_items = [
            item for item in all_items
            if can_read_object(
                item.get("visibility") or "workspace",
                item.get("creator_id"),
                item.get("workspace_id"),
                cur_uid, cur_ws, is_admin=False,
            )
        ]
    filtered_items = all_items
    if enabled is not None:
        filtered_items = [
            item for item in filtered_items
            if item.get("enabled") == enabled or item.get("status") == ('1' if enabled else '0')
        ]
    if search:
        s = search.lower()
        filtered_items = [
            item for item in filtered_items
            if any(
                s in str(item.get(field, "")).lower()
                for field in ["agent_name", "agent_description", "agent_id"]
            )
        ]
    total = len(filtered_items)
    paginated = filtered_items[skip:skip + limit]
    subagents = [agent_to_legacy_response(item) for item in paginated]
    return wrap_response({
        "subagents": subagents,
        "total": total,
        "count": len(subagents),
        "skip": skip,
        "limit": limit
    })
@router.get("/{id_value}")
@handle_admin_errors(" subagent  ({id_value})", detail_with_context=False)
async def get_item(
    id_value: str,
    user_permissions: UserPermissions = Depends(require_read("subagent"))
):
    agent_id = f'AGT_{id_value}' if not id_value.startswith('AGT_') else id_value
    item = config_db.subagents.get_by_id(agent_id, return_dict=True)
    if not item:
        all_items = config_db.subagents.get_all()
        for agent in all_items:
            name = agent.get('agent_id', '').replace('AGT_', '', 1)
            if name == id_value:
                item = agent
                break
    if not item:
        raise HTTPException(status_code=404, detail=f"subagent : {id_value}")
    return wrap_response(agent_to_legacy_response(item))
@router.post("")
@handle_admin_errors(" subagent ", detail_with_context=False)
async def create_item(
    data: SubAgentConfig,
    authorization: Optional[str] = Header(None),
    user_permissions: UserPermissions = Depends(require_write("subagent"))
):
    logger.info(f" {user_permissions.user_id}  subagent: {data.name}")
    id_value = data.name
    agent_id = f'AGT_{id_value}' if not id_value.startswith('AGT_') else id_value
    if config_db.subagents.get_by_id(agent_id):
        raise HTTPException(status_code=400, detail=f"subagent : {id_value}")
    # 三层可见性：记录创建者 + 工作空间，visibility 由 data.visibility 提供（默认 private）
    creator_id = int(user_permissions.user_id) if str(user_permissions.user_id).isdigit() else None
    workspace_id = get_workspace_id_from_auth_header(authorization)
    result = await create_agent_logic(data, creator_id=creator_id, workspace_id=workspace_id)
    if not result:
        raise HTTPException(status_code=500, detail=f" subagent ")
    reload_config()
    return wrap_response(message=f"subagent ")
@router.put("/{id_value}")
@handle_admin_errors(" subagent  ({id_value})", detail_with_context=False)
async def update_item(
    id_value: str,
    data: SubAgentConfig,
    authorization: Optional[str] = Header(None),
    user_permissions: UserPermissions = Depends(require_write("subagent"))
):
    logger.info(f" {user_permissions.user_id}  subagent: {id_value}")
    old_agent_id = f'AGT_{id_value}' if not id_value.startswith('AGT_') else id_value
    if not config_db.subagents.get_by_id(old_agent_id):
        raise HTTPException(status_code=404, detail=f"subagent : {id_value}")
    _ensure_can_modify_agent(old_agent_id, authorization, user_permissions)
    new_id = data.name
    new_agent_id = f'AGT_{new_id}' if not new_id.startswith('AGT_') else new_id
    if new_agent_id != old_agent_id:
        if config_db.subagents.get_by_id(new_agent_id):
            raise HTTPException(status_code=400, detail=f" subagent : {new_id}")
    workspace_id = get_workspace_id_from_auth_header(authorization)
    result = await update_agent_logic(id_value, data, workspace_id=workspace_id)
    if not result:
        raise HTTPException(status_code=500, detail=f" subagent ")
    reload_config()
    return wrap_response(message=f"subagent ")
@router.delete("/{id_value}")
@handle_admin_errors(" subagent  ({id_value})", detail_with_context=False)
async def delete_item(
    id_value: str,
    authorization: Optional[str] = Header(None),
    user_permissions: UserPermissions = Depends(require_delete("subagent"))
):
    logger.info(f" {user_permissions.user_id}  subagent: {id_value}")
    agent_id = f'AGT_{id_value}' if not id_value.startswith('AGT_') else id_value
    if not config_db.subagents.get_by_id(agent_id):
        raise HTTPException(status_code=404, detail=f"subagent : {id_value}")
    _ensure_can_modify_agent(agent_id, authorization, user_permissions)
    success = config_db.subagents.delete_agent(agent_id)
    if not success:
        raise HTTPException(status_code=500, detail=f" subagent ")
    reload_config()
    return wrap_response(message=f"subagent ")
@router.patch("/{id_value}/toggle")
@handle_admin_errors(" subagent ", detail_with_context=False)
async def toggle_item(
    id_value: str,
    enabled: bool = Query(...),
    user_permissions: UserPermissions = Depends(require_write("subagent"))
):
    logger.info(f" {user_permissions.user_id}  subagent : {id_value} -> {enabled}")
    agent_id = f'AGT_{id_value}' if not id_value.startswith('AGT_') else id_value
    agent = config_db.subagents.get_by_id(agent_id, return_dict=True)
    if not agent:
        raise HTTPException(status_code=404, detail=f"subagent : {id_value}")
    agent['status'] = '1' if enabled else '0'
    result = config_db.subagents.save_agent(
        agent_id=agent_id,
        agent_name=agent.get('agent_name', ''),
        system_prompt=agent.get('system_prompt', ''),
        tools=agent.get('tools', []),
        external_tools=agent.get('external_tools', []),
        mcp_tools=agent.get('mcp_tools', []),
        agent_description=agent.get('agent_description', ''),
        model_id=agent.get('model_id'),
        enabled=enabled
    )
    if not result:
        raise HTTPException(status_code=500, detail="更新子Agent启用状态失败")
    reload_config()
    return wrap_response(data={"enabled": enabled}, message=f"子Agent启用状态已更新为 {enabled}")
@router.post("/import")
async def import_subagents(
    files: List[UploadFile] = File(...),
    auto_import_tools: bool = Query(False),
    user_permissions: UserPermissions = Depends(require_manage("subagent"))
):
    def import_sub_func(config):
        name = config.get('name')
        if not name:
            raise ValueError("name")
        tools = config.get('tools', [])
        ext_tools = config.get('external_tools', [])
        validate_and_raise_tools(tools, ext_tools)
        agent_id = f"AGT_{name}"
        config_db.subagents.save_agent(
            agent_id=agent_id,
            agent_name=config.get('display_name') or name,
            system_prompt=config.get('system_prompt', ''),
            tools=tools,
            external_tools=ext_tools,
            mcp_tools=config.get('mcp_tools', []),
            agent_description=config.get('description', ''),
            model_id=config.get('model'),
            enabled=True
        )
        return {"name": name, "action": ""}
    return await handle_import_files(files, import_sub_func, "subagent")
@router.post("/export-all")
async def export_all_subagents(user_permissions: UserPermissions = Depends(require_read("subagent"))):
    agents = config_db.subagents.get_all()
    legacy_subagents = [agent_to_legacy_response(agent) for agent in agents]
    return handle_export_all(legacy_subagents, "subagent", "subagents")
@router.post("/{name}/export")
async def export_subagent_config(name: str, user_permissions: UserPermissions = Depends(require_read("subagent"))):
    agent_id = f'AGT_{name}' if not name.startswith('AGT_') else name
    agent = config_db.subagents.get_by_id(agent_id)
    if not agent:
        raise HTTPException(404, detail="SubAgent")
    export_data = agent_to_legacy_response(agent)
    export_data = {k: v for k, v in export_data.items() if k not in ['id', 'created_at', 'updated_at']}
    json_string = json.dumps(export_data, ensure_ascii=False, indent=2)
    return Response(
        content=json_string,
        media_type='application/json',
        headers={'Content-Disposition': f'attachment; filename="{name}.json"'}
    )
@router.post("/preview")
async def preview_subagent_config(subagent_config: SubAgentConfig, user_permissions: UserPermissions = Depends(require_read("subagent"))):
    combined_tools = subagent_config.tools.copy()
    combined_external_tools = subagent_config.external_tools.copy()
    multi_server_tools = {}
    if subagent_config.mcp_tools:
        for item in subagent_config.mcp_tools:
            if isinstance(item, str) and ":" in item:
                parts = item.split(":")
                if len(parts) == 3:
                    s, ts, t = parts
                    if (s, ts) not in multi_server_tools:
                        multi_server_tools[(s, ts)] = []
                    if multi_server_tools[(s, ts)] is not None:
                        multi_server_tools[(s, ts)].append(t)
                elif len(parts) == 2:
                    s, ts = parts
                    multi_server_tools[(s, ts)] = None
    for (s_name, ts_name), selected_mcp_tools in multi_server_tools.items():
        mcp_config = config_db.mcps.get_by_name(s_name)
        if not mcp_config:
            continue
        target_tool_set = next(
            (ts for ts in mcp_config.get("tool_sets", []) if ts.get("name") == ts_name), None
        )
        if not target_tool_set:
            continue
        tool_set_tools = target_tool_set.get("tools", {})
        if selected_mcp_tools is not None:
            selected_set = set(selected_mcp_tools)
            if "local" in tool_set_tools:
                combined_tools.extend([t for t in tool_set_tools["local"] if t in selected_set])
            if "external" in tool_set_tools:
                combined_external_tools.extend([t for t in tool_set_tools["external"] if t in selected_set])
            if isinstance(tool_set_tools, list):
                combined_external_tools.extend(
                    [t.get("name") if isinstance(t, dict) else t for t in tool_set_tools if
                     (t.get("name") if isinstance(t, dict) else t) in selected_set]
                )
        else:
            if isinstance(tool_set_tools, dict):
                combined_tools.extend(tool_set_tools.get("local", []))
                combined_external_tools.extend(tool_set_tools.get("external", []))
            elif isinstance(tool_set_tools, list):
                combined_external_tools.extend(
                    [t.get("name") if isinstance(t, dict) else t for t in tool_set_tools]
                )
    validation_errors = {}
    try:
        validate_and_raise_tools(combined_tools, combined_external_tools)
    except Exception as e:
        validation_errors["tool_validation"] = str(e)
    result = {
        "subagent": subagent_config.model_dump(),
        "tools": {
            "original": {"local": subagent_config.tools, "external": subagent_config.external_tools},
            "combined": {"local": combined_tools, "external": combined_external_tools}
        },
        "validation": {"errors": validation_errors, "valid": len(validation_errors) == 0}
    }
    return wrap_response(result)
@router.post("/test-config")
async def test_subagent_config(subagent_config: SubAgentConfig, user_permissions: UserPermissions = Depends(require_write("subagent"))):
    preview_res = await preview_subagent_config(subagent_config, user_permissions)
    preview_data = preview_res["data"]
    if not preview_data["validation"]["valid"]:
        return wrap_response(preview_data, message="子Agent配置校验未通过", success=False)
    return wrap_response(preview_data, message="SubAgent")