"""langfuse trace 上下文管理器。

propagate_attributes 封装，langfuse 未装/未启用时降级 no-op（不阻断主流程）。
"""
from contextlib import contextmanager
from typing import Optional


@contextmanager
def langfuse_trace(
    trace_name: str,
    session_id: str,
    tags: Optional[list] = None,
    metadata: Optional[dict] = None,
):
    """包裹执行入口，设 trace 元信息（trace_name/session_id/tags/metadata）。

    langfuse 未装或 propagate_attributes 不可用时降级为 no-op（不影响主流程）。
    tags/metadata 为 None 时默认空 list/dict。

    用法：
        with langfuse_trace(trace_name="plan_executor", session_id=sid, tags=["dag"]):
            # 执行 graph.astream(...)，langfuse 自动关联 trace
            ...
    """
    try:
        from langfuse import propagate_attributes
    except ImportError:
        yield  # 降级 no-op
        return
    with propagate_attributes(
        trace_name=trace_name,
        session_id=session_id,
        tags=tags or [],
        metadata=metadata or {},
    ):
        yield
