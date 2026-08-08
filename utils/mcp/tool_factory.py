"""MCP 工具集 - LangChain StructuredTool 工厂。"""
from loguru import logger
from typing import Any, Dict, Optional
from langchain_core.tools import StructuredTool
from pydantic import create_model, Field
from .sse import _call_mcp_tool_sse
from .stdio import _call_mcp_tool_stdio


def create_mcp_langchain_tool(mcp_config: Dict[str, Any], tool_def: Dict[str, Any]) -> StructuredTool:
    name = tool_def.get("name")
    description = tool_def.get("description", "")
    input_schema = tool_def.get("inputSchema", {})
    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])
    fields = {}
    for prop_name, prop_info in properties.items():
        prop_type = prop_info.get("type", "string")
        prop_desc = prop_info.get("description", "")
        type_map = {
            "string": str,
            "number": float,
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict
        }
        py_type = type_map.get(prop_type, Any)
        if prop_name in required:
            fields[prop_name] = (py_type, Field(..., description=prop_desc))
        else:
            fields[prop_name] = (Optional[py_type], Field(None, description=prop_desc))
    InputModel = create_model(f"{name}Input", **fields)
    logger.info(f"[LLM-MCP] {name} - : {len(properties)}")
    for prop_name, prop_info in properties.items():
        req = "" if prop_name in required else ""
        prop_desc = prop_info.get("description", "")
        prop_type = prop_info.get("type", "string")
        logger.info(f"[LLM-MCP] {name} - : {prop_name} = {prop_desc} ({prop_type}, {req})")
    logger.debug(f"[LLM-MCP] {name} - :\n{description}")
    async def _call_mcp_tool(**kwargs):
        mcp_type = mcp_config.get("mcp_type")
        headers = mcp_config.get("headers")
        url_params = mcp_config.get("url_params")
        if mcp_type == "sse":
            return await _call_mcp_tool_sse(mcp_config.get("url"), name, kwargs, headers=headers, url_params=url_params)
        elif mcp_type == "stdio":
            return await _call_mcp_tool_stdio(
                mcp_config.get("command"),
                mcp_config.get("args", []),
                mcp_config.get("env", {}),
                name,
                kwargs
            )
        else:
            raise ValueError(f" MCP : {mcp_type}")
    return StructuredTool.from_function(
        func=None,
        coroutine=_call_mcp_tool,
        name=name,
        description=description,
        args_schema=InputModel
    )
