"""统一 trace 上下文（A7）。

经 contextvar + loguru contextualize 把 trace_id（dispatch_id/session_id）+ trigger_id
贯穿 trigger→dispatch→workflow→task→llm→tool 全链路。下游所有 loguru 日志自动带
extra.trace_id/dispatch_id/trigger_id，实现 langfuse 未启用时的日志关联。

与 langfuse_handler.attach_callbacks 互补：
- attach_callbacks：langfuse 启用时关联 trace（外部 tracing 系统）
- trace_context：始终生效的日志关联（含 langfuse 未启用场景）
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Optional

from loguru import logger

# trace 上下文：跨层传递，asyncio 子任务经 context copy 继承
_TRACE_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("trace_id", default=None)
_DISPATCH_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("dispatch_id", default=None)
_TRIGGER_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("trigger_id", default=None)


def get_trace_id() -> Optional[str]:
    """当前 trace_id（dispatch_id/session_id），无则 None。"""
    return _TRACE_ID.get()


def get_dispatch_id() -> Optional[str]:
    return _DISPATCH_ID.get()


def get_trigger_id() -> Optional[str]:
    return _TRIGGER_ID.get()


@contextmanager
def trace_context(
    trace_id: str,
    dispatch_id: Optional[str] = None,
    trigger_id: Optional[str] = None,
):
    """设置 trace 上下文：contextvar + loguru contextualize（下游日志自动带 trace_id）。

    用法（dispatch/plan 入口）：
        with trace_context(trace_id=dispatch_id, dispatch_id=dispatch_id, trigger_id=tid):
            async for ev in dispatch_stream(...): ...

    退出时恢复原值（contextvar token reset + logger contextualize 退出）。
    """
    tid_token = _TRACE_ID.set(trace_id)
    did_token = _DISPATCH_ID.set(dispatch_id)
    trid_token = _TRIGGER_ID.set(trigger_id)
    # loguru contextualize：把 trace_id 注入所有下游日志的 extra（异步上下文内自动传播）
    extra = {"trace_id": trace_id}
    if dispatch_id:
        extra["dispatch_id"] = dispatch_id
    if trigger_id:
        extra["trigger_id"] = trigger_id
    with logger.contextualize(**extra):
        try:
            yield
        finally:
            _TRACE_ID.reset(tid_token)
            _DISPATCH_ID.reset(did_token)
            _TRIGGER_ID.reset(trid_token)
