"""delegate_agent 工具：agent 间子任务委派（L4）。

让一个 agent 在 ReAct 循环中调用另一个 agent 执行子任务并回灌结果文本，
补齐"无 agent 间直接对话/子委派"的局限（L4）。

防护（A3 硬化）：
- 深度限制（contextvar）：agent A→B→C 嵌套委派超 max_depth 拒绝，防无限递归。
- agent 不存在 / 执行失败 → 返回 'error: ...'（与 is_error_result 契约一致）。

执行路径（A2 轻量化）：走 LangGraphWorkflowAdapter.execute_task 直跑单 agent，
复用模块单例 LangGraphTaskExecutor + 图缓存，不经 MultiAgentService.dispatch_stream
的 DispatchRecord 持久化/usage/eval/event hooks——细粒度协作低成本、无 DB 噪声。
"""
from __future__ import annotations

import contextvars
from typing import Any

from langchain_core.tools import tool
from loguru import logger

# 委派深度（contextvar）：跨嵌套委派链传递，asyncio 子任务经 context copy 继承
_DELEGATION_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar(
    "delegation_depth", default=0
)
# 调用方 workspace（由 agent executor 注入，delegate 内做目标 agent 可见性校验；
# None=未设置，get_by_name 跳过 workspace 过滤——长期需 executor 设此值实现彻底隔离）
_DELEGATION_WORKSPACE: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "delegation_workspace", default=None
)
# N4: instruction 长度上限（防超长 prompt injection 载荷）
_MAX_INSTRUCTION_LEN = 10000


async def _run_delegation(agent_name: str, instruction: str) -> str:
    """A2 轻量路径：构造单 task plan + adapter.execute_task 直跑，无 dispatch 持久化。"""
    from utils.config import get_config, get_config_db
    from utils.llm import get_default_llm
    from utils.planning.schemas import ExecutionPlan, TaskNode, PlanMode
    from executor.langgraph import get_langgraph_executor
    from executor.workflow import create_workflow_adapter

    cfg = get_config_db().subagents.get_by_name(agent_name, workspace_id=_DELEGATION_WORKSPACE.get())
    if not cfg:
        return f"error: 未找到 agent '{agent_name}'"
    pr_key_id = cfg.get("pr_key_id") or cfg.get("agent_id")
    if not pr_key_id:
        return f"error: agent '{agent_name}' 无 pr_key_id"

    # 复用单例 executor + 图缓存；adapter 轻量构造（仅存 callable）
    lg_executor = get_langgraph_executor()
    llm_model = get_default_llm()
    adapter = create_workflow_adapter(
        langgraph_executor=lg_executor,
        subagent_getter=lambda name: get_config_db().subagents.get_by_name(name, workspace_id=_DELEGATION_WORKSPACE.get()),
        tools_getter=_delegate_tools_getter,
        llm_model=llm_model,
    )
    plan = ExecutionPlan(
        mode=PlanMode.AGENT,
        tasks=[TaskNode(id=f"delegate_{agent_name}", agent=agent_name, description=instruction)],
        original_query=instruction,
    )
    # A2 关键：execute_task 直跑单 agent，不写 DispatchRecord、不跑 hooks
    result = await adapter.execute_task(plan.tasks[0], plan, {})
    if isinstance(result, str) and result.startswith("error:"):
        return result
    return result or "(目标 agent 未返回内容)"


async def _delegate_tools_getter(agent_name: str, subagent_config: dict):
    """tools_getter：包装 collect_subagent_tools_async 签名（adapter 期望）。"""
    from core.builder.tool_collector import collect_subagent_tools_async
    tools, skill_index, skill_ids, kb_stats = await collect_subagent_tools_async(
        subagent_config,
        subagent_config.get("pr_key_id"),
        return_skill_ids=True,
        return_kb_stats=True,
    )
    return tools, skill_index, skill_ids, kb_stats


@tool
async def delegate_agent(agent_name: str, instruction: str) -> str:
    """委派子任务给另一个 agent，返回其输出。用于 agent 间协作。

    适用：当前 agent 不擅长某子任务时，可委派给更合适的 agent。
    嵌套委派有深度上限（默认 2），超限拒绝以避免无限递归。

    Args:
        agent_name: 目标 agent 的名称
        instruction: 委派给目标 agent 的子任务说明
    """
    from utils.config import get_config
    from utils.config.config_loader import get_agent_config

    # A3 深度防护硬化：先查深度，再执行，优先 Agent 级配置
    from utils.config import get_config_db
    cfg = get_config_db().subagents.get_by_name(agent_name, workspace_id=_DELEGATION_WORKSPACE.get())
    agent_id_for_cfg = int(cfg.get("pr_key_id")) if cfg and cfg.get("pr_key_id") else None
    max_depth = get_agent_config("agent.execution.delegation.max_depth", 2, agent_id=agent_id_for_cfg)
    depth = _DELEGATION_DEPTH.get()
    if depth >= max_depth:
        logger.warning(f"[delegate_agent] 委派深度 {depth} 达上限 {max_depth}，拒绝")
        return f"error: 委派深度达上限({max_depth})，拒绝继续委派"
    # N1 防御性硬上限：若 contextvar 在某 Pregel 子任务边界失效致 depth 异常大，
    # 强制阻断（max_depth 的 3 倍为安全边际，正常不会触发）
    hard_cap = max(max_depth * 3, max_depth + 5)
    if depth >= hard_cap:
        logger.error(f"[delegate_agent] 委派深度 {depth} 越过硬上限 {hard_cap}（疑似 contextvar 失效），强制阻断")
        return f"error: 委派深度越过硬上限({hard_cap})，强制阻断"

    # N4: instruction 长度上限（防超长 prompt injection 载荷）+ 审计日志（追踪委派链）
    if len(instruction) > _MAX_INSTRUCTION_LEN:
        logger.warning(f"[delegate_agent] instruction 超长（{len(instruction)} > {_MAX_INSTRUCTION_LEN}），拒绝委派到 {agent_name}")
        return f"error: instruction 超长（>{_MAX_INSTRUCTION_LEN} 字符），拒绝委派"
    logger.info(f"[delegate_agent] 委派审计: target={agent_name}, depth={depth}, workspace={_DELEGATION_WORKSPACE.get()}, instruction_preview={instruction[:100]!r}")

    token = _DELEGATION_DEPTH.set(depth + 1)
    try:
        return await _run_delegation(agent_name, instruction)
    except Exception as e:
        logger.error(f"[delegate_agent] 委派 {agent_name} 失败: {e}", exc_info=True)
        return f"error: 委派失败: {e}"
    finally:
        _DELEGATION_DEPTH.reset(token)


def get_delegation_tools() -> list[Any]:
    """返回 delegation 工具列表（供 tool_collector 条件加载）。"""
    return [delegate_agent]

