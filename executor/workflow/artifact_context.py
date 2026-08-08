"""W1: 工作流 dep 上下文（contextvar）——桥接 WorkflowState 到工具。

问题：工具（langchain @tool）无法直接访问 LangGraph WorkflowState（artifacts/blackboard），
导致上游 task 的完整结构化结果只能截断后拼进下游 prompt（失真）。

解法：node 函数在调 adapter 前把 dep_context（含 envelope/blackboard）设入 contextvar，
下游 agent 的 get_upstream_result 工具经 context copy 读取（asyncio 子任务继承，A7 已验证机制），
从而无损获取上游完整结果，不依赖 prompt 文本截断。
"""
from __future__ import annotations

import contextvars
from typing import Optional

# 当前 task 可见的 dep 上下文：{task_id | blackboard_key: envelope | str | val}
_DEP_CONTEXT: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "workflow_dep_context", default=None
)


def set_dep_context(ctx: Optional[dict]):
    """设置 dep 上下文（返回 token，退出时 reset）。"""
    return _DEP_CONTEXT.set(ctx)


def reset_dep_context(token):
    _DEP_CONTEXT.reset(token)


def get_dep_context() -> Optional[dict]:
    """当前 dep 上下文（工具读取，无则 None）。"""
    return _DEP_CONTEXT.get()
