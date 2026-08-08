"""ToolExecutionGuard — 工具执行前置审批守卫。

在 LangGraph tool 执行前拦截：检查是否需要审批，
如需审批则通过 ReviewRegistry 暂停等待人工确认。
"""
import uuid
from typing import Dict, Any, Optional
from loguru import logger

from .policy import resolve_approval_required


class ToolExecutionGuard:
    """工具执行守卫 — 在每个 tool_call 前检查是否需要人工审批。"""

    def __init__(self):
        pass

    def check(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        risk_level: str,
        agent_id: Optional[str] = None,
        approval_policy: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """检查 tool 调用是否需要审批。

        同步方法：返回 {action, dispatch_id, ...} 表示判定结果。
        实际暂停/唤醒在 executor 层异步执行。

        Args:
            tool_name: 工具名称 (如 "sandbox.execute_command")
            tool_args: 工具调用参数
            risk_level: 工具风险等级
            agent_id: Agent ID（用于策略查找和审计）
            approval_policy: Agent 的审批策略配置 dict:
                {"enabled": True, "threshold": "destructive",
                 "timeout_seconds": 600, "tools_override": {}}

        Returns:
            {
                "action": "pass" | "require_approval",
                "dispatch_id": "...",       # 仅 require_approval 时
                "reason": "risk_exceeds_threshold" | "override_always" | "..."
            }
        """
        policy = approval_policy or {}
        enabled = policy.get("enabled", False)
        threshold = policy.get("threshold", "destructive")
        overrides = policy.get("tools_override", {})

        requires = resolve_approval_required(
            risk_level=risk_level,
            threshold=threshold,
            overrides=overrides,
            tool_name=tool_name,
            enabled=enabled,
        )

        if not requires:
            return {
                "action": "pass",
                "reason": "policy_allows",
            }

        dispatch_id = f"tool-{tool_name}-{uuid.uuid4().hex[:8]}"
        logger.info(
            f"[ToolExecutionGuard] Tool='{tool_name}' risk={risk_level} "
            f"agent={agent_id} → REQUIRE_APPROVAL (dispatch={dispatch_id})"
        )

        return {
            "action": "require_approval",
            "dispatch_id": dispatch_id,
            "reason": (
                "risk_exceeds_threshold"
                if overrides.get(tool_name) != "always"
                else "override_always"
            ),
            "tool_name": tool_name,
            "tool_args": tool_args,
            "risk_level": risk_level,
            "agent_id": agent_id,
        }
