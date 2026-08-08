"""Agent 间通信工具（设计 G5）：让 Agent 在 ReAct 循环中主动收发消息。

暴露两个 @tool：
- send_message_to_agent(to_agent, content, from_agent)：向另一个 Agent 发消息
- read_my_messages(agent_name)：拉取自己的待处理消息

设计参见 docs/specs/2026-07-19-team-collaboration-design.md G5。

用法：Agent 在对话中可主动调这两个工具与其他 Agent 协作。
例如：研究员 Agent 完成调研后，调 send_message_to_agent 通知总结者 Agent。
"""
from langchain_core.tools import tool
from loguru import logger


@tool
async def send_message_to_agent(to_agent: str, content: str, from_agent: str = "current") -> str:
    """Send a message to another agent in the team. Use this to communicate with teammate agents.

    Args:
        to_agent: The name of the receiving agent (e.g. "summary-agent")
        content: The message content to send
        from_agent: Your own agent name (defaults to "current" if unknown)

    Returns:
        Success/failure confirmation message
    """
    try:
        from services.agent_team_service import AgentTeamService
        result = AgentTeamService().send_message(
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            msg_type="text",
        )
        if result:
            logger.info(f"[agent_comm] {from_agent} -> {to_agent}: message sent")
            return f"Message sent to {to_agent} successfully (message_id={result.get('message_id', '')})"
        return f"Failed to send message to {to_agent}"
    except Exception as e:
        logger.error(f"[agent_comm] send_message_to_agent failed: {e}", exc_info=True)
        return f"Error sending message: {e}"


@tool
async def read_my_messages(agent_name: str) -> str:
    """Read your pending messages from other agents. Call this to check if teammates sent you messages.

    Args:
        agent_name: Your own agent name (e.g. "summary-agent")

    Returns:
        List of pending messages, or "no messages" if inbox is empty
    """
    try:
        from services.agent_team_service import AgentTeamService
        messages = AgentTeamService().poll_messages(agent_name)
        if not messages:
            return f"No pending messages for {agent_name}"
        # 格式化消息列表
        lines = [f"You have {len(messages)} pending message(s):"]
        for i, msg in enumerate(messages, 1):
            lines.append(f"  {i}. From: {msg.get('from_agent', '?')} | Content: {msg.get('content', '')} | message_id: {msg.get('message_id', '')}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[agent_comm] read_my_messages failed: {e}", exc_info=True)
        return f"Error reading messages: {e}"


def get_team_communication_tools():
    """获取团队通信工具列表（供 agent_factory 注入）。

    Returns:
        [send_message_to_agent, read_my_messages]
    """
    return [send_message_to_agent, read_my_messages]
