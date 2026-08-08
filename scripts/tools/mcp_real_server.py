"""真实 MCP Server（用 mcp SDK 的 FastMCP）

提供 echo 和 word_count 两个工具，通过 stdio 传输。
用 langchain-mcp-adapters 可将其转为 langchain tools。
"""
from mcp.server.fastmcp import FastMCP

server = FastMCP("text-analysis-tools")


@server.tool()
def echo(text: str) -> str:
    """回显输入文本，用于确认结果"""
    return f"MCP Echo: {text}"


@server.tool()
def word_count(text: str) -> str:
    """统计文本中的单词数量"""
    count = len(text.split())
    return f"Word count: {count}"


if __name__ == "__main__":
    server.run(transport="stdio")
