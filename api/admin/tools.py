import json
import io
from loguru import logger
import zipfile
from pathlib import Path
from typing import Set, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import Response
from utils.config import get_config_db
from utils.common.tool_parser import extract_tool_info
from tools.registry import get_tool_registry
from ._error_handler import handle_admin_errors
from .base import wrap_response
from .common import verify_token, reload_config, ToolConfigUpdate
from .permissions import require_read
from utils.common.permissions import UserPermissions
router = APIRouter(tags=["admin"])
def _get_tool_name(tool: Any) -> str:
    if hasattr(tool, 'name'):
        return tool.name
    elif hasattr(tool, '__name__'):
        return tool.__name__
    else:
        return str(tool)
def _merge_tool_config(tool_info: Dict[str, Any], 
                       file_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if file_config:
        if file_config.get('display_name'):
            tool_info['display_name'] = file_config['display_name']
        if file_config.get('description'):
            tool_info['description'] = file_config['description']
        if file_config.get('parameter_descriptions'):
            tool_info['parameter_descriptions'] = file_config['parameter_descriptions']
        if file_config.get('return_description'):
            tool_info['return_description'] = file_config['return_description']
        if file_config.get('examples'):
            tool_info['examples'] = file_config['examples']
    return tool_info
@router.get("/tools")
@handle_admin_errors("", detail_with_context=True)
async def get_tools(
    user_permissions: UserPermissions = Depends(require_read("tool")),
    skip: int = Query(0, ge=0, description=""),
    limit: int = Query(10, ge=1, le=100, description=""),
    search: str = Query("", description="")
):
    tool_registry = get_tool_registry()
    tools = tool_registry.get_all()
    config_db = get_config_db()
    external_tool_configs = config_db.external_tools.get_all() or []
    external_tool_names: Set[str] = {cfg['name'] for cfg in external_tool_configs}
    agent_dir = Path(__file__).parent.parent.parent
    tools_config_dir = agent_dir / "config" / "tools"
    tool_configs_from_files: Dict[str, Dict[str, Any]] = {}
    if tools_config_dir.exists():
        for config_file in tools_config_dir.glob("*.json"):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    file_config = json.load(f)
                tool_name = file_config.get('name')
                if tool_name:
                    tool_configs_from_files[tool_name] = file_config
            except Exception as e:
                logger.warning(f"加载工具配置失败 {config_file}: {e}")
    tool_list = []
    for tool in tools:
        tool_name = _get_tool_name(tool)
        if tool_name in external_tool_names:
            continue
        try:
            tool_info = extract_tool_info(tool)
            file_config = tool_configs_from_files.get(tool_info['name'])
            tool_info = _merge_tool_config(tool_info, file_config)
            tool_list.append(tool_info)
        except Exception as e:
            logger.warning(f"加载工具 {tool_name} 失败: {e}")
            if tool_name in external_tool_names:
                continue
            tool_desc = ""
            if hasattr(tool, 'description') and tool.description:
                tool_desc = tool.description
            elif hasattr(tool, '__doc__') and tool.__doc__:
                tool_desc = tool.__doc__.strip().split('\n')[0]
            tool_list.append({
                "name": tool_name,
                "display_name": "",
                "description": tool_desc,
                "parameters": [],
                "return_type": "str",
                "return_description": "",
                "examples": [],
                "parameter_descriptions": {}
            })
    filtered_tools = tool_list
    if search:
        search_lower = search.lower()
        filtered_tools = [
            t for t in tool_list
            if (
                search_lower in str(t.get('name', '')).lower() or
                search_lower in str(t.get('display_name', '')).lower() or
                search_lower in str(t.get('description', '')).lower()
            )
        ]
    total = len(filtered_tools)
    paginated = filtered_tools[skip : skip + limit]
    logger.info(f"工具列表查询: search='{search}', total={total}, range=[{skip}:{skip+limit}]")
    return {
        "tools": paginated,
        "total": total,
        "count": len(paginated),
        "skip": skip,
        "limit": limit
    }


@router.get("/tools/stats")
@handle_admin_errors("", detail_with_context=True)
async def get_tool_stats(
    request: Request,
    user_permissions: UserPermissions = Depends(require_read("tool")),
    workspace_id: int | None = Query(None, description="按工作空间筛选（仅 admin 有效，覆盖当前空间；None=全部空间）"),
):
    """工具数量统计（统计概览用）。

    按 T-A 方案：统计 Agent 通过 tb_agent_relation(relation_flag=RELATION_API='1')
    绑定的去重外部工具数量。
    - admin + workspace_id=None（全部用户）：全部 Agent（不分空间）绑定的去重外部工具数
    - admin + workspace_id=X：该空间 Agent（workspace_id==X 或 is_public==1）绑定的去重外部工具数
    - 非 admin：用 token 的 workspace_id（防越权）
    """
    from utils.common.auth_dependencies import get_workspace_id_from_auth_header
    from infrastructure.database.repositories.agent_relation_repository import AgentRelationRepository
    from infrastructure.database.models.agent import AgentRelation

    is_admin = user_permissions.has_role("admin")
    if is_admin:
        effective_ws = workspace_id  # None=全部空间，传值=该空间
    else:
        effective_ws = get_workspace_id_from_auth_header(request.headers.get("Authorization", ""))

    repo = AgentRelationRepository()
    total = repo.count_distinct_related(AgentRelation.RELATION_API, workspace_id=effective_ws)
    return {"success": True, "data": {"total": total}}


@router.get("/tools/{name}")
async def get_tool_config(name: str, user_permissions: UserPermissions = Depends(require_read("tool"))):
    try:
        tool_registry = get_tool_registry()
        tool = tool_registry.get(name)
        if not tool:
            raise HTTPException(status_code=404, detail=f"工具不存在: {name}")
        tool_info = extract_tool_info(tool)
        agent_dir = Path(__file__).parent.parent.parent
        tools_config_dir = agent_dir / "config" / "tools"
        tool_config_file = tools_config_dir / f"{name}.json"
        if tool_config_file.exists():
            try:
                with open(tool_config_file, 'r', encoding='utf-8') as f:
                    file_config = json.load(f)
                if file_config.get('display_name'):
                    tool_info['display_name'] = file_config['display_name']
                if file_config.get('description'):
                    tool_info['description'] = file_config['description']
                if file_config.get('parameter_descriptions'):
                    tool_info['parameter_descriptions'] = file_config['parameter_descriptions']
                    for param in tool_info['parameters']:
                        param_name = param['name']
                        if param_name in file_config['parameter_descriptions']:
                            param['description'] = file_config['parameter_descriptions'][param_name]
                if file_config.get('return_description'):
                    tool_info['return_description'] = file_config['return_description']
                if file_config.get('examples'):
                    tool_info['examples'] = file_config['examples']
            except Exception as e:
                logger.warning(f"读取工具配置文件失败 {tool_config_file}: {e}")
        return tool_info
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.put("/tools/{name}")
async def update_tool_config(
    name: str,
    config_update: ToolConfigUpdate,
    token: str = Depends(verify_token)
):
    try:
        tool_registry = get_tool_registry()
        tool = tool_registry.get(name)
        if not tool:
            raise HTTPException(status_code=404, detail=f"工具不存在: {name}")
        tool_info = extract_tool_info(tool)
        param_names = {p['name'] for p in tool_info['parameters']}
        if config_update.parameter_descriptions:
            invalid_params = set(config_update.parameter_descriptions.keys()) - param_names
            if invalid_params:
                raise HTTPException(
                    status_code=400,
                    detail=f"无效的工具参数: {', '.join(invalid_params)}"
                )
        tool_config = {
            "name": name,
            "display_name": config_update.display_name or tool_info.get('display_name', ''),
            "description": config_update.description or tool_info['description'],
            "parameter_descriptions": config_update.parameter_descriptions or tool_info['parameter_descriptions'],
            "return_description": config_update.return_description or tool_info['return_description'],
            "examples": config_update.examples or tool_info['examples']
        }
        agent_dir = Path(__file__).parent.parent.parent
        tools_config_dir = agent_dir / "config" / "tools"
        tools_config_dir.mkdir(parents=True, exist_ok=True)
        tool_config_file = tools_config_dir / f"{name}.json"
        with open(tool_config_file, 'w', encoding='utf-8') as f:
            json.dump(tool_config, f, ensure_ascii=False, indent=2)
        reload_config()
        return wrap_response(message=f"工具配置已更新: {name}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/tools/{name}/export")
async def export_tool_config(name: str, token: str = Depends(verify_token)):
    try:
        agent_dir = Path(__file__).parent.parent.parent
        tools_config_dir = agent_dir / "config" / "tools"
        tool_config_file = tools_config_dir / f"{name}.json"
        if not tool_config_file.exists():
            raise HTTPException(status_code=404, detail=f"工具配置文件不存在: {tool_config_file}")
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            with open(tool_config_file, 'rb') as f:
                zipf.writestr(f'tools/{name}.json', f.read())
        zip_buffer.seek(0)
        zip_data = zip_buffer.getvalue()
        zip_buffer.close()
        if len(zip_data) == 0:
            raise HTTPException(status_code=500, detail="ZIP")
        return Response(
            content=zip_data,
            media_type='application/zip',
            headers={
                'Content-Disposition': f'attachment; filename="tool_{name}.zip"'
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/tools/export-all")
async def export_all_tool_configs(token: str = Depends(verify_token)):
    try:
        config_db = get_config_db()
        tool_registry = get_tool_registry()
        tools = tool_registry.get_all()
        if not tools:
            raise HTTPException(status_code=404, detail="没有可导出的工具")
        agent_dir = Path(__file__).parent.parent.parent
        tools_config_dir = agent_dir / "config" / "tools"
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for tool in tools:
                try:
                    tool_name = None
                    if hasattr(tool, 'name'):
                        tool_name = tool.name
                    elif hasattr(tool, '__name__'):
                        tool_name = tool.__name__
                    if not tool_name:
                        continue
                    tool_config_file = tools_config_dir / f"{tool_name}.json"
                    tool_config = None
                    if tool_config_file.exists():
                        try:
                            with open(tool_config_file, 'r', encoding='utf-8') as f:
                                tool_config = json.load(f)
                        except Exception as e:
                            logger.warning(f"读取工具配置文件失败 {tool_config_file}: {e}")
                    if not tool_config:
                        tool_info = extract_tool_info(tool)
                        tool_config = {
                            "name": tool_name,
                            "description": tool_info.get('description', ''),
                            "parameter_descriptions": tool_info.get('parameter_descriptions', {}),
                            "return_description": tool_info.get('return_description', ''),
                            "examples": tool_info.get('examples', [])
                        }
                    config_json = json.dumps(tool_config, ensure_ascii=False, indent=2)
                    zipf.writestr(f'tools/{tool_name}.json', config_json.encode('utf-8'))
                except Exception as e:
                    logger.warning(f"导出工具配置失败 {tool_name if 'tool_name' in locals() else 'unknown'}: {e}")
                    continue
        zip_buffer.seek(0)
        zip_data = zip_buffer.getvalue()
        zip_buffer.close()
        if len(zip_data) == 0:
            raise HTTPException(status_code=500, detail="ZIP")
        return Response(
            content=zip_data,
            media_type='application/zip',
            headers={
                'Content-Disposition': 'attachment; filename="tools_all.zip"'
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/tools/{name}/restore-defaults")
async def restore_default_tool_config(name: str, token: str = Depends(verify_token)):
    try:
        tool_registry = get_tool_registry()
        tool = tool_registry.get(name)
        if not tool:
            raise HTTPException(status_code=404, detail=f"工具不存在: {name}")
        agent_dir = Path(__file__).parent.parent.parent
        tools_config_dir = agent_dir / "config" / "tools"
        tool_config_file = tools_config_dir / f"{name}.json"
        tool_config = None
        source = "code"
        if tool_config_file.exists():
            try:
                with open(tool_config_file, 'r', encoding='utf-8') as f:
                    tool_config = json.load(f)
                source = "files"
                logger.info(f"JSON: {name}")
            except Exception as e:
                logger.warning(f"JSON {name}: {str(e)}")
        if not tool_config:
            tool_info = extract_tool_info(tool)
            tool_config = {
                "name": name,
                "description": tool_info['description'],
                "parameter_descriptions": tool_info['parameter_descriptions'],
                "return_description": tool_info['return_description'],
                "examples": tool_info['examples']
            }
            source = "code"
        tools_config_dir.mkdir(parents=True, exist_ok=True)
        with open(tool_config_file, 'w', encoding='utf-8') as f:
            json.dump(tool_config, f, ensure_ascii=False, indent=2)
        reload_config()
        return {
            "message": f": {name} (: {source})",
            "source": source,
            "status": "success"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/tools/restore-defaults")
async def restore_default_tool_configs(token: str = Depends(verify_token)):
    try:
        agent_dir = Path(__file__).parent.parent.parent
        tools_config_dir = agent_dir / "config" / "tools"
        tools_config_dir.mkdir(parents=True, exist_ok=True)
        tool_registry = get_tool_registry()
        tools = tool_registry.get_all()
        restored = []
        failed = []
        for tool in tools:
            try:
                tool_info = extract_tool_info(tool)
                tool_name = tool_info['name']
                tool_config_file = tools_config_dir / f"{tool_name}.json"
                tool_config = None
                if tool_config_file.exists():
                    try:
                        with open(tool_config_file, 'r', encoding='utf-8') as f:
                            tool_config = json.load(f)
                    except Exception as e:
                        logger.warning(f"读取工具配置文件失败 {tool_config_file}: {e}")
                if not tool_config:
                    tool_config = {
                        "name": tool_name,
                        "description": tool_info['description'],
                        "parameter_descriptions": tool_info['parameter_descriptions'],
                        "return_description": tool_info['return_description'],
                        "examples": tool_info['examples']
                    }
                with open(tool_config_file, 'w', encoding='utf-8') as f:
                    json.dump(tool_config, f, ensure_ascii=False, indent=2)
                restored.append(tool_name)
            except Exception as e:
                tool_name = tool.name if hasattr(tool, 'name') else str(tool)
                failed.append({
                    "name": tool_name,
                    "error": str(e)
                })
                logger.warning(f"恢复工具配置失败 {tool_name}: {e}")
        reload_config()
        return {
            "message": f"成功恢复 {len(restored)} 个",
            "restored": restored,
            "failed": failed,
            "count": len(restored),
            "source": "files" if restored else "code",
            "status": "success"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))