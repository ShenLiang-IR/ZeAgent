"""从 LangGraph 执行结果中提取最终输出文本的共享工具函数。"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from utils.message.message_extractor import extract_reasoning_from_content


def extract_final_output(final_state: Any) -> str:
    """从 graph.ainvoke 结果中提取最终输出文本。

    依次尝试以下策略：
    1. final_state["messages"][-1] 是 AIMessage → 剥离 thinking 标签后返回
    2. final_state 本身是 str → 直接返回
    3. final_state 是 dict → 检查 content / output / result / text 键
    4. 兜底返回空字符串

    被 DeepAgentExecutor / ReActExecutor / LangGraphTaskExecutor 共用，
    替代各自重复的 _extract_output 方法。
    """
    messages = final_state.get("messages", []) if isinstance(final_state, dict) else []
    if not messages:
        # 没有 messages 列表时，尝试从 final_state 本身提取
        if isinstance(final_state, str):
            return final_state
        if isinstance(final_state, dict):
            for key in ("content", "output", "result", "text"):
                if key in final_state:
                    content = final_state[key]
                    if isinstance(content, str) and content.strip():
                        return content
        return ""

    last_msg = messages[-1]
    if isinstance(last_msg, AIMessage):
        content = last_msg.content or ""
        try:
            _, cleaned_content = extract_reasoning_from_content(content)
            if cleaned_content != content:
                return cleaned_content
        except Exception:
            pass
        return content
    return str(last_msg)
