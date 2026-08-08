from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from utils.config import get_config_db
from .common import reload_config
from .permissions import require_manage
from .base import wrap_response
from utils.common.permissions import UserPermissions
from loguru import logger
from pathlib import Path
router = APIRouter(tags=["admin"])
class SystemConfigRequest(BaseModel):
    system_name: Optional[str] = None
    system_description: Optional[str] = None
class SystemConfigResponse(BaseModel):
    system_name: str
    system_description: str
@router.get("/config/system")
async def get_system_config(user_permissions: UserPermissions = Depends(require_manage("system"))):
    try:
        config_db = get_config_db()
        system_name = config_db.get_system_name()
        system_description = config_db.get_system_description()
        return SystemConfigResponse(
            system_name=system_name or "",
            system_description=system_description or ""
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/config/agent")
async def get_agent_config():
    """返回完整 agent_config.json 内容（前端系统配置页使用）。

    checkpoint 配置已在 agent_config.json 的 database.checkpoint 段，
    合并到返回值的 checkpoint.mysql 中供前端 Checkpoint 标签页显示。
    """
    try:
        import json
        base_dir = Path(__file__).parent.parent.parent
        config_path = base_dir / "config" / "agent_config.json"
        with open(config_path, encoding='utf-8') as f:
            config = json.load(f)
        # 从 agent_config.json 的 database.checkpoint 段读取
        db_section = config.get("database", {})
        checkpoint_db = db_section.get("checkpoint", {})
        if checkpoint_db:
            if "checkpoint" not in config or not isinstance(config.get("checkpoint"), dict):
                config["checkpoint"] = {}
            config["checkpoint"]["mysql"] = {
                "host": checkpoint_db.get("host", ""),
                "port": checkpoint_db.get("port", 3306),
                "user": checkpoint_db.get("user", ""),
                "password": checkpoint_db.get("password", ""),
                "database": checkpoint_db.get("database", ""),
            }
            config["checkpoint"]["backend"] = "mysql" if config["checkpoint"].get("mysql_enabled") else "memory"
        return config
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/config/agent")
async def update_agent_config(config: dict):
    """更新 agent_config.json 内容，保存后刷新运行时配置。"""
    try:
        import json
        config_path = Path(__file__).parent.parent.parent / "config" / "agent_config.json"
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        # 保存后刷新运行时配置（ConfigLoader + tool_registry + subagent_registry）
        try:
            reload_config()
        except Exception as e:
            logger.warning(f"[Config] reload after save failed: {e}")
        return wrap_response(message="Configuration saved")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.put("/config/system")
async def update_system_config(
    config: SystemConfigRequest,
    user_permissions: UserPermissions = Depends(require_manage("system"))
):
    try:
        config_db = get_config_db()
        if config.system_name is not None:
            config_db.set_system_name(config.system_name)
        if config.system_description is not None:
            config_db.set_system_description(config.system_description)
        return {
            "message": "",
            "status": "success"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/config/statistics")
async def get_statistics(user_permissions: UserPermissions = Depends(require_manage("system"))):
    try:
        config_db = get_config_db()
        subagents = config_db.subagents.get_all()
        subagent_count = 0
        for s in subagents:
            enabled = s.get('enabled', True)
            if isinstance(enabled, bool):
                if enabled:
                    subagent_count += 1
            elif isinstance(enabled, (int, str)):
                if int(enabled) != 0:
                    subagent_count += 1
            else:
                subagent_count += 1
        try:
            from tools.registry import get_tool_registry
            tool_registry = get_tool_registry()
            tools = tool_registry.get_all()
            external_tool_configs = config_db.external_tools.get_all()
            external_tool_names = {cfg['name'] for cfg in external_tool_configs}
            tool_count = 0
            for tool in tools:
                tool_name = None
                if hasattr(tool, 'name'):
                    tool_name = tool.name
                elif hasattr(tool, '__name__'):
                    tool_name = tool.__name__
                else:
                    tool_name = str(tool)
                if tool_name not in external_tool_names:
                    tool_count += 1
        except Exception as e:
            agent_dir = Path(__file__).parent.parent.parent
            tools_dir = agent_dir / "config" / "tools"
            tool_count = 0
            if tools_dir.exists():
                tool_files = [f for f in tools_dir.glob("*.json") if not f.name.endswith('.example')]
                tool_count = len(tool_files)
        external_tools = config_db.external_tools.get_all()
        external_tool_count = 0
        for t in external_tools:
            enabled = t.get('enabled', True)
            if isinstance(enabled, bool):
                if enabled:
                    external_tool_count += 1
            elif isinstance(enabled, (int, str)):
                if int(enabled) != 0:
                    external_tool_count += 1
            else:
                external_tool_count += 1
        return {
            "subagent_count": subagent_count,
            "tool_count": tool_count,
            "external_tool_count": external_tool_count,
            "total": subagent_count + tool_count + external_tool_count
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))