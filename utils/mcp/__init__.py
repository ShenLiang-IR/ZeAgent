"""MCP 工具集（utils/mcp 包）。

按传输协议/职责拆分：
- common.py: URL 解析 / 环境变量替换 / SSE 文本解析（通用基础）
- sse.py: SSE/HTTP 传输（fetch server info / tools list / tool call）
- stdio.py: stdio 进程传输（握手 / tools list / tools/call + 错误格式化）
- tool_factory.py: LangChain StructuredTool 工厂

向后兼容：`from utils.mcp_util import X` 仍可用（utils/mcp_util.py re-export 全部符号）。
"""
from .common import (
    resolve_env_vars,
    extract_params_from_url,
    parse_json_from_sse_text,
    build_url_with_params,
    ENV_VAR_PATTERN,
)
from .sse import (
    fetch_mcp_server_info,
    fetch_mcp_tools_from_url,
    _call_mcp_tool_sse,
)
from .stdio import (
    fetch_mcp_tools_from_command,
    _call_mcp_tool_stdio,
    _call_mcp_tool_stdio_shortlived,
    _format_mcp_error,
)
from .tool_factory import create_mcp_langchain_tool

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
