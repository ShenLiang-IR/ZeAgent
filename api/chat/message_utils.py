from loguru import logger

from utils.message.message_helper import extract_user_input_from_messages  # noqa: F401


def extract_user_input(request_messages):
    if not request_messages:
        return None
    for msg in reversed(request_messages):
        if isinstance(msg, dict):
            if msg.get('role') == 'user':
                return msg.get('content', '')
        elif hasattr(msg, 'role') and msg.role == 'user':
            if hasattr(msg, 'content'):
                return msg.content
            elif hasattr(msg, 'text'):
                return msg.text
    return None


def _build_kb_context(request_messages) -> str:
    """遍历所有消息的 kb_refs，构建知识库上下文前缀。"""
    parts = []
    for msg in request_messages:
        refs = None
        if isinstance(msg, dict):
            refs = msg.get('kb_refs')
        elif hasattr(msg, 'kb_refs'):
            refs = msg.kb_refs
        if not refs:
            continue
        for ref in refs:
            if isinstance(ref, dict):
                parts.append(f"知识库「{ref.get('label', '')}」：\n{ref.get('content', '')}")
            else:
                parts.append(f"知识库「{ref.label}」：\n{ref.content}")
    if parts:
        result = "【参考知识库】\n" + "\n\n".join(parts) + "\n---\n"
        logger.info(f"[_build_kb_context] 构建 KB 上下文: {len(parts)} 条引用, 长度={len(result)}")
        return result
    logger.info("[_build_kb_context] 无 kb_refs，KB 上下文为空")
    return ""


def convert_to_langchain_messages(request_messages):
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    kb_context = _build_kb_context(request_messages)
    langchain_messages = []
    if kb_context:
        langchain_messages.append(SystemMessage(content=kb_context))
    for msg in request_messages:
        if isinstance(msg, dict):
            role = msg.get('role', 'user')
            content = msg.get('content', '')
        else:
            role = getattr(msg, 'role', 'user')
            content = getattr(msg, 'content', '')
        if role == 'user':
            langchain_messages.append(HumanMessage(content=content))
        elif role == 'assistant':
            langchain_messages.append(AIMessage(content=content))
        elif role == 'system':
            langchain_messages.append(SystemMessage(content=content))
    return langchain_messages
