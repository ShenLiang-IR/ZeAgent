"""Meta-Agent MCP 管理工具。

每个工具直接调用 McpService（不经过 HTTP），返回 LLM 可读的字符串。
用 async @tool 装饰器（langchain StructuredTool，支持 ainvoke）。
"""
import json
import asyncio
from langchain_core.tools import tool
from loguru import logger


@tool
async def create_mcp(
    name: str,
    connection_type: str = "stdio",
    exec_cmd: str = "",
    params_args: str = "",
    description: str = "",
) -> str:
    """创建一个 MCP 服务配置。当用户想添加一个新的 MCP 服务时使用此工具。

    Args:
        name: MCP 服务名称（唯一标识，如 "text-analysis-tools"）
        connection_type: 连接类型，"stdio"（本地进程）或 "sse"（HTTP/SSE）
        exec_cmd: stdio 模式的执行命令（如 "python" 或完整路径），sse 模式留空
        params_args: stdio 模式的脚本参数，JSON 数组字符串（如 '["/path/to/server.py"]'），sse 模式留空
        description: MCP 服务描述

    Returns:
        创建结果，含 pr_key_id 和 mcp_id
    """
    from services.mcp_service import McpService

    service = McpService()
    params = None
    if params_args:
        try:
            parsed = json.loads(params_args)
            params = {"args": parsed} if isinstance(parsed, list) else parsed
        except json.JSONDecodeError:
            return f"参数错误: params_args 不是有效的 JSON 数组: {params_args}"
    try:
        result = service.register(
            mcp_name=name,
            description=description,
            connection_type=connection_type,
            exec_cmd=exec_cmd,
            params=params,
        )
        return (
            f"MCP '{name}' 创建成功。"
            f"pr_key_id={result['pr_key_id']}, mcp_id={result['mcp_id']}"
        )
    except Exception as e:
        return f"创建 MCP 失败: {e}"


@tool
async def sync_mcp_interfaces(pr_key_id: str) -> str:
    """从 MCP 服务拉取工具列表，同步到接口表（tb_mcp_intfc）。创建 MCP 后务必调用此工具。

    Args:
        pr_key_id: MCP 服务的 pr_key_id（从 create_mcp 或 list_mcps 获取）

    Returns:
        同步结果（同步了多少个接口）
    """
    from services.mcp_service import McpService

    service = McpService()
    try:
        result = await service.sync_interfaces(int(pr_key_id))
        return f"同步完成，共 {result['synced']} 个接口。"
    except Exception as e:
        return f"同步失败: {e}"


@tool
async def test_mcp_connection(
    connection_type: str = "stdio",
    exec_cmd: str = "",
    params_args: str = "",
    connection_url: str = "",
) -> str:
    """测试 MCP 连接，返回工具列表（不写库）。创建前可先测试连接是否正常。

    Args:
        connection_type: "stdio" 或 "sse"
        exec_cmd: stdio 执行命令
        params_args: stdio 脚本参数 JSON 数组
        connection_url: sse 连接 URL

    Returns:
        工具列表或错误信息
    """
    from services.mcp_service import McpService

    service = McpService()
    params = None
    if params_args:
        try:
            parsed = json.loads(params_args)
            params = {"args": parsed} if isinstance(parsed, list) else parsed
        except json.JSONDecodeError:
            params = {}
    try:
        tools = await service.test_connect(
            connection_type=connection_type,
            exec_cmd=exec_cmd,
            connection_url=connection_url,
            params=params,
        )
        tool_names = [t.get("name", "unknown") for t in tools]
        return f"连接成功，获取到 {len(tools)} 个工具: {tool_names}"
    except Exception as e:
        return f"连接失败: {e}"


@tool
async def list_mcps() -> str:
    """列出所有已创建的 MCP 服务。"""
    from services.mcp_service import McpService

    service = McpService()
    result = service.page(page_no=1, page_size=50)
    lines = []
    for mcp in result.get("list", []):
        status = "启用" if mcp.get("enabled") else "禁用"
        lines.append(
            f"- {mcp['mcp_name']} (pr_key_id={mcp['pr_key_id']}, "
            f"mcp_id={mcp['mcp_id']}, {status})"
        )
    return f"共 {result.get('total', 0)} 个 MCP:\n" + "\n".join(lines)


@tool
async def delete_mcp(pr_key_id: str) -> str:
    """删除一个 MCP 服务（级联删除其接口）。

    Args:
        pr_key_id: MCP 服务的 pr_key_id

    Returns:
        删除结果
    """
    from services.mcp_service import McpService

    service = McpService()
    try:
        ok = service.delete(int(pr_key_id))
        if ok:
            return f"MCP (pr_key_id={pr_key_id}) 删除成功。"
        return f"MCP (pr_key_id={pr_key_id}) 不存在或删除失败。"
    except Exception as e:
        return f"删除失败: {e}"
