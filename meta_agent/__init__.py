"""Meta-Agent 包入口。

管理工具不注册到全局 tool_registry（隔离），只有 meta-agent 专门加载。
"""
from meta_agent.mcp_tools import (
    create_mcp,
    sync_mcp_interfaces,
    test_mcp_connection,
    list_mcps,
    delete_mcp,
)
from meta_agent.skill_tools import (
    create_skill,
    list_skills,
    delete_skill,
    generate_skill_impl,
)
from meta_agent.tool_tools import (
    create_external_tool,
    list_external_tools,
    delete_external_tool,
)
from meta_agent.agent_tools import (
    create_agent,
    list_agents,
    delete_agent,
)

from meta_agent.system_prompt import META_AGENT_SYSTEM_PROMPT

__all__ = [
    # System Prompt
    "META_AGENT_SYSTEM_PROMPT",
    # MCP
    "create_mcp",
    "sync_mcp_interfaces",
    "test_mcp_connection",
    "list_mcps",
    "delete_mcp",
    # Skill
    "create_skill",
    "list_skills",
    "delete_skill",
    "generate_skill_impl",
    # External Tool
    "create_external_tool",
    "list_external_tools",
    "delete_external_tool",
    # Agent
    "create_agent",
    "list_agents",
    "delete_agent",
]


def get_management_tools():
    """返回 meta-agent 的全部管理工具列表（langchain StructuredTool 实例）。"""
    return [
        # MCP
        create_mcp,
        sync_mcp_interfaces,
        test_mcp_connection,
        list_mcps,
        delete_mcp,
        # Skill
        create_skill,
        list_skills,
        delete_skill,
        generate_skill_impl,
        # External Tool
        create_external_tool,
        list_external_tools,
        delete_external_tool,
        # Agent
        create_agent,
        list_agents,
        delete_agent,
    ]
