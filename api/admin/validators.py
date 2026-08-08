from typing import List, Tuple
from fastapi import HTTPException
from utils.config import get_config_db
from tools.registry import get_tool_registry
def validate_tools(
    tools: List[str],
    external_tools: List[str],
    check_local: bool = True,
    check_external: bool = True,
    check_duplicate: bool = True
) -> Tuple[List[str], List[str], List[str]]:
    invalid_tools = []
    invalid_external_tools = []
    duplicate_tools = []
    if check_local and tools:
        tool_registry = get_tool_registry()
        local_tool_names = [t.name if hasattr(t, 'name') else str(t) for t in tool_registry.get_all()]
        invalid_tools = [t for t in tools if t not in local_tool_names]
    if check_external and external_tools:
        config_db = get_config_db()
        external_tool_configs = config_db.external_tools.get_all()
        external_tool_names = [cfg['name'] for cfg in external_tool_configs]
        invalid_external_tools = [t for t in external_tools if t not in external_tool_names]
    if check_duplicate:
        duplicate_tools = list(set(tools) & set(external_tools))
    return invalid_tools, invalid_external_tools, duplicate_tools
def validate_and_raise_tools(
    tools: List[str],
    external_tools: List[str],
    check_local: bool = True,
    check_external: bool = True,
    check_duplicate: bool = True
):
    invalid_tools, invalid_external_tools, duplicate_tools = validate_tools(
        tools, external_tools, check_local, check_external, check_duplicate
    )
    if invalid_tools:
        raise HTTPException(
            status_code=400,
            detail=f"无效的工具: {', '.join(invalid_tools)}"
        )
    if invalid_external_tools:
        raise HTTPException(
            status_code=400,
            detail=f"无效的外部工具: {', '.join(invalid_external_tools)}"
        )
    if duplicate_tools:
        raise HTTPException(
            status_code=400,
            detail=f"toolsexternal_tools: {', '.join(duplicate_tools)}"
        )