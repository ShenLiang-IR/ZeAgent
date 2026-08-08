"""get_upstream_result 工具（W1）：让下游 agent 无损获取上游 task 完整结果。

经 artifact_context contextvar 读取（node 在调 adapter 前设置），不依赖 prompt 文本截断。
注册：config agent.execution.upstream_result_tool.enabled=true 时由 tool_collector 注入所有 agent。
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from loguru import logger


@tool
def get_upstream_result(task_id: str) -> str:
    """获取上游 task 的完整结果（不截断）。

    当 prompt 中注入的上游结果被截断（含 '已截断' 标记）时，用此工具按 task_id 获取完整内容。
    Args:
        task_id: 上游 task 的 id（见 prompt 中的依赖说明）
    """
    from executor.workflow.artifact_context import get_dep_context
    from executor.workflow.types import result_to_text
    ctx = get_dep_context() or {}
    val = ctx.get(task_id)
    if val is None:
        return f"error: 未找到上游 task '{task_id}' 的结果（可能无此依赖或上下文未设置）"
    try:
        return result_to_text(val)
    except Exception as e:
        logger.warning(f"[get_upstream_result] {task_id} 转文本失败: {e}")
        return str(val) if val is not None else f"error: {task_id} 结果转换失败"


def get_upstream_result_tools() -> list[Any]:
    """返回 upstream_result 工具列表（供 tool_collector 条件加载）。"""
    return [get_upstream_result]
