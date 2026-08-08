from .task_executor import LangGraphTaskExecutor
from .task_context import (
    TaskContext,
    ExecutionOptions,
    ExecutionEvent,
    TaskResult,
    TaskStatus,
    TaskType,
)

# 模块级单例：PlanExecutor 与 MultiAgentService 共享同一 LangGraphTaskExecutor，
# 使 _compiled_graphs 图缓存跨 execute/dispatch 复用（触发器高频重复 agent 受益最大）。
# 配合 LangGraphTaskExecutor._compiled_graphs 的 LRU 上限防内存膨胀。
_executor_instance: LangGraphTaskExecutor | None = None


def get_langgraph_executor() -> LangGraphTaskExecutor:
    """返回模块级单例 LangGraphTaskExecutor（惰性创建）。"""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = LangGraphTaskExecutor()
    return _executor_instance


def reset_langgraph_executor() -> None:
    """重置单例（测试用）。"""
    global _executor_instance
    _executor_instance = None


__all__ = [
    "LangGraphTaskExecutor",
    "TaskContext",
    "ExecutionOptions",
    "ExecutionEvent",
    "TaskResult",
    "TaskStatus",
    "TaskType",
    "get_langgraph_executor",
    "reset_langgraph_executor",
]
