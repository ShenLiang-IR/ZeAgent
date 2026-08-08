"""agent 间委派工具包（L4：agent-as-tool，独立包，不被 tool_registry 自动扫描）。

启用：config agent.execution.delegation.enabled=true 时由 tool_collector 条件加载，
为所有 agent 注入 delegate_agent 工具，使其可在 ReAct 循环中委派子任务给另一 agent。
"""
from .delegate_agent import get_delegation_tools, delegate_agent

__all__ = ["get_delegation_tools", "delegate_agent"]
