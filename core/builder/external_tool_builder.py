from loguru import logger
from typing import Optional, Any
from tools.external_tool import create_external_tool_from_config
def create_external_tool(tool_name: str) -> Optional[Any]:
    try:
        external_tool = create_external_tool_from_config(tool_name)
        if not external_tool:
            return None
        langchain_tool = external_tool.to_langchain_tool()
        return langchain_tool
    except Exception as e:
        logger.error(f"构建外部工具 {tool_name} 失败: {e}", exc_info=True)
        return None