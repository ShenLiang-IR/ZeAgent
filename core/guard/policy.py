"""Tool 审批策略引擎。

提供风险等级比较和审批策略解析，供 ToolExecutionGuard 使用。
"""

# 风险等级排序（值越大越危险）
RISK_ORDER = {
    "read_only": 0,
    "write_safe": 1,
    "destructive": 2,
    "external": 3,
    "always": 4,  # 用于 override，强制审批
}


def risk_exceeds(level: str, threshold: str) -> bool:
    """检查 risk_level 是否超过审批阈值。

    Args:
        level: 工具的 risk_level (read_only/write_safe/destructive/external)
        threshold: Agent 配置的审批阈值

    Returns:
        True 表示需要审批，False 表示自动放行
    """
    lv = RISK_ORDER.get(level, 0)
    th = RISK_ORDER.get(threshold, 0)
    return lv > th


def resolve_approval_required(
    risk_level: str,
    threshold: str,
    overrides: dict,
    tool_name: str,
    enabled: bool = True,
) -> bool:
    """解析是否需要审批。

    优先级：
    1. enabled=False → 全部放行
    2. override=never → 强制放行
    3. override=always → 强制审批
    4. risk_level vs threshold → 按等级判定

    Args:
        risk_level: 工具风险等级
        threshold: 审批阈值
        overrides: {tool_name: "always"|"never"} 特例覆盖
        tool_name: 当前工具名称
        enabled: 审批策略是否启用

    Returns:
        True: 需要审批
        False: 自动放行
    """
    if not enabled:
        return False

    override = overrides.get(tool_name)
    if override == "never":
        return False
    if override == "always":
        return True

    return risk_exceeds(risk_level, threshold)
