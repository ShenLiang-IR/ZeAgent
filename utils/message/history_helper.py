from typing import List, Any, Optional
from loguru import logger
from utils.config.config_loader import get_config
def extract_session_history(
    messages: List[Any],
    max_turns: Optional[int] = None,
    content_max_len: int = 500,
) -> Optional[str]:
    if max_turns is None:
        max_turns = get_config('context.recent_window_size', 10)
    if not messages or len(messages) < 2:
        return None
    try:
        history_messages = messages[:-1]
        if not history_messages:
            return None
        summary_parts = []
        conversation_msgs = []
        for msg in history_messages:
            msg_type = _get_msg_type(msg)
            if msg_type == 'system':
                content = _get_msg_content(msg)
                if content and ('<compressed_history>' in content or '[]' in content):
                    summary_parts.append(content)
                continue
            if msg_type in ('tool', 'tool_result'):
                continue
            conversation_msgs.append(msg)
        recent_msgs = _take_recent_turns(conversation_msgs, max_turns)
        lines = []
        if summary_parts:
            lines.append("")
            for s in summary_parts:
                lines.append(s[:800])
            lines.append("")
        for msg in recent_msgs:
            msg_type = _get_msg_type(msg)
            content = _get_msg_content(msg)
            if not content or not content.strip():
                continue
            truncated = content[:content_max_len]
            if 'human' in (msg_type or ''):
                lines.append(f": {truncated}")
            elif 'ai' in (msg_type or ''):
                lines.append(f": {truncated}")
        return "\n".join(lines) if lines else None
    except Exception as e:
        logger.debug(f"[extract_session_history] : {e}")
        return None
def _get_msg_type(msg: Any) -> Optional[str]:
    if hasattr(msg, 'type'):
        return str(msg.type).lower()
    if hasattr(msg, '__class__'):
        name = msg.__class__.__name__.lower()
        for keyword in ('human', 'user', 'ai', 'assistant', 'system', 'tool'):
            if keyword in name:
                return keyword
    if isinstance(msg, dict):
        return str(msg.get('type', msg.get('role', ''))).lower()
    return None
def _get_msg_content(msg: Any) -> Optional[str]:
    if hasattr(msg, 'content'):
        c = msg.content
        return c if isinstance(c, str) else str(c)
    if isinstance(msg, dict):
        return str(msg.get('content', ''))
    return None
def _take_recent_turns(messages: List[Any], max_turns: int) -> List[Any]:
    if not messages or max_turns <= 0:
        return []
    turn_starts = []
    for i, msg in enumerate(messages):
        if _get_msg_type(msg) in ('human', 'user'):
            turn_starts.append(i)
    if not turn_starts:
        return messages[-2:] if len(messages) >= 2 else messages
    if len(turn_starts) <= max_turns:
        return messages
    start_idx = turn_starts[-max_turns]
    return messages[start_idx:]