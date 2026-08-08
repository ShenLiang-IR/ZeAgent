"""MCP 工具集（已拆分到 utils/mcp/ 包）。

本文件保留为 re-export 桥接，保 `from utils.mcp_util import X` 旧路径兼容。
原 844 行单文件已按职责拆为：
- utils/mcp/common.py    URL 解析 / 环境变量替换 / SSE 文本解析
- utils/mcp/sse.py       SSE/HTTP 传输
- utils/mcp/stdio.py     stdio 进程传输 + 错误格式化
- utils/mcp/tool_factory.py  LangChain StructuredTool 工厂

新代码建议直接用 utils.mcp 子模块路径。
"""
from .mcp.common import (
    resolve_env_vars,
    extract_params_from_url,
    parse_json_from_sse_text,
    build_url_with_params,
    ENV_VAR_PATTERN,
)
from .mcp.sse import (
    fetch_mcp_server_info,
    fetch_mcp_tools_from_url,
    _call_mcp_tool_sse,
)
from .mcp.stdio import (
    fetch_mcp_tools_from_command,
    _call_mcp_tool_stdio,
    _call_mcp_tool_stdio_shortlived,
    _format_mcp_error,
)
from .mcp.tool_factory import create_mcp_langchain_tool

__all__ = [
    "resolve_env_vars",
    "extract_params_from_url",
    "parse_json_from_sse_text",
    "build_url_with_params",
    "ENV_VAR_PATTERN",
    "fetch_mcp_server_info",
    "fetch_mcp_tools_from_url",
    "_call_mcp_tool_sse",
    "fetch_mcp_tools_from_command",
    "_call_mcp_tool_stdio",
    "_call_mcp_tool_stdio_shortlived",
    "_format_mcp_error",
    "create_mcp_langchain_tool",
]
