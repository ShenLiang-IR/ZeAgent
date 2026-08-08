"""Tool Execution Guard — Human-in-the-Loop 审批守卫模块。"""
from .tool_execution_guard import ToolExecutionGuard
from .policy import risk_exceeds, resolve_approval_required, RISK_ORDER
from .tool_guard_integration import (
    get_guard, seed_risk_levels, get_tool_risk_level,
    wrap_tool_with_guard, wrap_tools_with_guard,
    DEFAULT_RISK_LEVELS, DEFAULT_APPROVAL_POLICY,
)

__all__ = [
    "ToolExecutionGuard", "risk_exceeds", "resolve_approval_required", "RISK_ORDER",
    "get_guard", "seed_risk_levels", "get_tool_risk_level",
    "wrap_tool_with_guard", "wrap_tools_with_guard",
    "DEFAULT_RISK_LEVELS", "DEFAULT_APPROVAL_POLICY",
]
