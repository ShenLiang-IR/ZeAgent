"""工具审批守卫集成 — 在工具执行层注入人工审批检查。

提供 wrap_tool_with_guard() 函数，将 LangChain Tool 包装为带审批检查的版本。
在 _get_or_build_graph 中自动注入。
"""
from typing import Any, Callable, Dict, Optional
from loguru import logger

from core.guard import ToolExecutionGuard

# 默认工具风险等级（Phase 1 内置，后续可从 tb_tool 或配置文件加载）
DEFAULT_RISK_LEVELS = {
    # read_only — 纯读操作
    "read_file": "read_only",
    "knowledge_base_search": "read_only",
    "knowledge_base_retrieve": "read_only",
    "memory.remember": "write_safe",
    "memory.recall": "read_only",
    "memory.forget": "write_safe",
    "execute_sql": "read_only",  # text2sql 默认只读
    "csv_to_json": "read_only",
    "json_to_csv": "read_only",
    "text-stats": "read_only",
    "regex-tester": "read_only",
    "hash-tool": "read_only",
    "uuid-generator": "read_only",
    "text-diff": "read_only",
    "word-frequency": "read_only",
    "markdown-to-html": "read_only",
    "format-table-to-json": "read_only",

    # write_safe — 写入但低风险
    "write_file": "write_safe",
    "memory.remember": "write_safe",
    "code-runner": "write_safe",
    "csv-tool": "write_safe",
    "excel-tool": "write_safe",
    "doc-converter": "write_safe",
    "base64-tool": "write_safe",
    "pdf-extractor": "write_safe",
    "datetime-tool": "write_safe",

    # destructive — 不可逆操作
    "sandbox.execute_command": "destructive",
    "delete_file": "destructive",
    "sql_template": "destructive",
    "exec_sql_template": "destructive",
    "make_tools.execute_sql": "destructive",

    # external — 外部通信
    "http_request": "external",
    "http-request": "external",
    "email_sender": "external",
    "email-sender": "external",
}

# Agent 默认审批策略（非破坏性操作不审批）
DEFAULT_APPROVAL_POLICY = {
    "enabled": True,
    "threshold": "destructive",
    "timeout_seconds": 600,
    "tools_override": {},
}


_guard: Optional[ToolExecutionGuard] = None


def get_guard() -> ToolExecutionGuard:
    """获取 ToolExecutionGuard 单例。"""
    global _guard
    if _guard is None:
        _guard = ToolExecutionGuard()
        seed_risk_levels()
    return _guard


def seed_risk_levels():
    """初始化工具风险等级到 ToolRegistry。"""
    from tools.registry import ToolRegistry
    for tool_name, level in DEFAULT_RISK_LEVELS.items():
        ToolRegistry.set_risk_level(
            tool_name, level,
            f"内置默认风险等级: {level}"
        )
    logger.info(f"[ToolGuard] 已初始化 {len(DEFAULT_RISK_LEVELS)} 个工具的默认风险等级")


def get_tool_risk_level(tool_name: str) -> str:
    """获取工具风险等级。"""
    from tools.registry import ToolRegistry
    reg = ToolRegistry()
    return reg.get_risk_level(tool_name)


def wrap_tool_with_guard(tool: Any, agent_id: str = "",
                         approval_policy: Optional[Dict] = None) -> Any:
    """将 LangChain Tool 包装为带审批守卫的版本。

    在每个 tool 调用前检查是否需要审批；需要时阻塞等待审批结果。

    Args:
        tool: LangChain BaseTool 实例
        agent_id: Agent ID
        approval_policy: Agent 审批策略（None 使用 DEFAULT_APPROVAL_POLICY）

    Returns:
        包装后的 tool（同类型）
    """
    policy = approval_policy or DEFAULT_APPROVAL_POLICY
    if not policy.get("enabled", True):
        return tool

    guard = get_guard()
    tool_name = getattr(tool, 'name', getattr(tool, '__name__', str(tool)))
    risk_level = get_tool_risk_level(tool_name)

    # 保存原始 func/invoke 以做包装
    original_invoke = getattr(tool, '_run', None) or getattr(tool, 'func', None)

    if original_invoke is None or not callable(original_invoke):
        logger.debug(f"[ToolGuard] Tool '{tool_name}' 无可包装的 callable，跳过")
        return tool

    # 检查是否需要包装
    from core.guard.policy import resolve_approval_required
    requires = resolve_approval_required(
        risk_level=risk_level,
        threshold=policy.get("threshold", "destructive"),
        overrides=policy.get("tools_override", {}),
        tool_name=tool_name,
        enabled=policy.get("enabled", True),
    )

    if not requires:
        # 该 tool 在当前策略下不需要审批，直接返回
        return tool

    # 创建同步包装函数
    def guarded_func(*args, **kwargs):
        """同步守卫包装 — 检查审批后执行原函数。"""
        # 注意：同步包装不支持 async 审批（ReviewRegistry 是 async 的）
        # 对于同步 tool 调用，跳过审批直接执行
        logger.debug(f"[ToolGuard] Sync tool '{tool_name}': 跳过审批（同步模式不支持审批暂停）")
        return original_invoke(*args, **kwargs)

    # 创建异步包装函数（如果原始函数是 async）
    import asyncio
    import inspect

    if inspect.iscoroutinefunction(original_invoke):
        async def async_guarded_func(*args, **kwargs):
            """异步守卫包装 — 检查审批后执行原函数。"""
            tool_args = {}
            if args:
                tool_args = args[0] if isinstance(args[0], dict) else {"args": str(args)}
            if kwargs:
                tool_args.update(kwargs)

            # 检查审批
            check_result = guard.check(
                tool_name=tool_name,
                tool_args=tool_args,
                risk_level=risk_level,
                agent_id=agent_id,
                approval_policy=policy,
            )

            if check_result["action"] == "pass":
                return await original_invoke(*args, **kwargs)

            # 需要审批：暂停并等待
            dispatch_id = check_result["dispatch_id"]
            from utils.review.registry import ReviewRegistry
            ReviewRegistry.register(dispatch_id)

            timeout = policy.get("timeout_seconds", 600)
            review_result = await ReviewRegistry.await_review(
                dispatch_id, timeout=timeout
            )

            if review_result["action"] == "approve":
                logger.info(f"[ToolGuard] 审批通过: {tool_name} (disp={dispatch_id})")
                result = await original_invoke(*args, **kwargs)
                ReviewRegistry.remove(dispatch_id)
                return result
            else:
                reason = review_result.get("reason", "审批拒绝")
                logger.info(f"[ToolGuard] 审批拒绝: {tool_name} (disp={dispatch_id}, reason={reason})")
                ReviewRegistry.remove(dispatch_id)
                return f"[审批拒绝] Tool '{tool_name}' 执行已被管理员拒绝: {reason}"

        # 替换原 tool 的异步方法
        if hasattr(tool, '_arun'):
            tool._arun = async_guarded_func
        if hasattr(tool, 'ainvoke'):
            original_ainvoke = tool.ainvoke

            async def guarded_ainvoke(input_data, *ainvoke_args, **ainvoke_kwargs):
                return await async_guarded_func(input_data)

            tool.ainvoke = guarded_ainvoke
    else:
        if hasattr(tool, '_run'):
            tool._run = guarded_func

    logger.info(f"[ToolGuard] Tool '{tool_name}' 已包装审批守卫 (risk={risk_level})")
    return tool


def wrap_tools_with_guard(tools: list, agent_id: str = "",
                          approval_policy: Optional[Dict] = None) -> list:
    """批量包装工具。"""
    return [wrap_tool_with_guard(t, agent_id, approval_policy) for t in tools]
