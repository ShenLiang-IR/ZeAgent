"""记忆工具运行时上下文 — ContextVar 自动捕获当前 user_id/session_id。

chat 入口 set_memory_context(user_id, session_id)；记忆工具内 get_memory_context() 取值，
LLM 只传 query/content/memory_id。async 任务内 ContextVar 自动传播。
"""
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass
class MemoryContext:
    user_id: Optional[str]
    session_id: Optional[str]


_var: ContextVar[MemoryContext] = ContextVar(
    "memory_context", default=MemoryContext(None, None)
)


def set_memory_context(user_id: Optional[str], session_id: Optional[str]) -> None:
    _var.set(MemoryContext(user_id=user_id, session_id=session_id))


def get_memory_context() -> MemoryContext:
    return _var.get()


def reset_memory_context() -> None:
    _var.set(MemoryContext(None, None))
