"""重规划 / task 级循环 决策函数（PlanExecutor 与 MultiAgentService 共享）。

从 PlanExecutor 下沉：让 dispatch（触发器场景）也具备动态重规划 + task 级循环能力，
两入口行为对齐，默认读全局 config（agent.execution.replan）。

设计：
- match_condition / match_replan_on / check_loop：纯函数，无 self 依赖
- replan(trigger_task, trigger_result, llm_model)：调 LLM 重规划，降级返回 None
- check_replan(plan, context, context_health, llm_model, replan_fn=None)：
    遍历 task，命中 condition/replan_on 即重规划。replan_fn 可注入（PlanExecutor
    传 self._replan 以保留单测 mock 契约），None 则用本模块 replan。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from loguru import logger

from utils.planning.schemas import ExecutionPlan, TaskNode
from executor.workflow.types import is_error_result


def match_condition(condition: Optional[dict], result: str) -> bool:
    """检查 result 是否匹配 condition 触发条件。

    - when=failed: result 以 'error:' 开头
    - when=contains + keyword: result 含 keyword
    - 无 when 或空 condition: 不触发
    """
    if not condition:
        return False
    when = condition.get("when", "")
    if when == "failed" and is_error_result(result):
        return True
    if when == "contains":
        keyword = condition.get("keyword", "")
        return keyword in result if keyword else False
    return False


def match_replan_on(expr: Optional[str], result: str) -> bool:
    """检查 result 是否匹配 replan_on 表达式（当前只支持 contains('keyword')）。"""
    if not expr:
        return False
    if "contains" in expr:
        match = re.search(r"contains\(['\"](.+?)['\"]\)", expr)
        if match:
            return match.group(1) in result
    return False


def check_loop(plan: ExecutionPlan, context: Dict[str, Any]) -> bool:
    """检查是否有 task 的 loop.until 未满足，需循环重跑同 plan。

    Returns: True 需循环重跑，False 无需循环。
    """
    for task in plan.tasks:
        if not task.loop:
            continue
        until = task.loop.get("until", "")
        result = context.get(task.id, "")
        result_str = result if isinstance(result, str) else str(result)
        if until and not match_replan_on(until, result_str):
            logger.info(f"[replan] task {task.id} loop until 未满足，触发循环重跑")
            return True
    return False


async def replan(trigger_task: TaskNode, trigger_result: str, llm_model: Any) -> Optional[ExecutionPlan]:
    """调 LLM 重规划，生成新 ExecutionPlan。降级返回 None。

    无 LLM（llm_model 为 None）→ 直接降级返回 None。
    """
    try:
        from utils.planning.generator import generate_execution_plan
        from utils.config import get_config_db
        if not llm_model:
            logger.warning("[replan] 无 LLM，重规划降级")
            return None
        subagents = get_config_db().subagents.get_all(enabled_only=True) or []
        new_plan = await generate_execution_plan(
            user_input=f"上游 task '{trigger_task.id}' 结果：'{trigger_result[:500]}'。基于此结果，需要追加什么 agent 或走什么路径？",
            subagents=subagents,
            llm_model=llm_model,
        )
        logger.info(f"[replan] 重规划成功：{len(new_plan.tasks)} tasks, mode={new_plan.mode}")
        return new_plan
    except Exception as e:
        logger.warning(f"[replan] 重规划失败: {e}，继续用原结果")
        return None


async def check_replan(
    plan: ExecutionPlan,
    context: Dict[str, Any],
    context_health: Dict[str, dict],
    llm_model: Any,
    replan_fn: Optional[Any] = None,
) -> Optional[ExecutionPlan]:
    """检查 task 结果，命中 condition/replan_on 则重规划。

    Args:
        replan_fn: 可注入的重规划回调，签名 (trigger_task, trigger_result, plan, context)
            → Optional[ExecutionPlan]。None 时用本模块 replan（dispatch 路径）。
            PlanExecutor 传 self._replan 以保留单测 mock 契约。

    Returns: 新 ExecutionPlan（需重规划）或 None（无需重规划）。
    """
    for task in plan.tasks:
        result = context.get(task.id, "")
        result_str = result if isinstance(result, str) else str(result)

        if task.condition and match_condition(task.condition, result_str):
            logger.info(f"[replan] task {task.id} condition 触发重规划")
            if replan_fn is not None:
                return await replan_fn(task, result_str, plan, context)
            return await replan(task, result_str, llm_model)

        if task.replan_on and match_replan_on(task.replan_on, result_str):
            logger.info(f"[replan] task {task.id} replan_on 触发重规划")
            if replan_fn is not None:
                return await replan_fn(task, result_str, plan, context)
            return await replan(task, result_str, llm_model)

    return None
