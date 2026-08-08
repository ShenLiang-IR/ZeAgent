"""Agent 流式输出处理（精简版）。

P2-1: 已删除 ~700 行死代码 generate_stream_response 及其 _handle_*/_finalize_stream/
_StreamState/日志格式化辅助函数（生产无调用方，仅旧测试引用）。
保留唯一生产路径 generate_simple_stream。
"""
import time
import datetime as _dt
from typing import AsyncGenerator

from utils.config import get_config
from utils.common.constants import DEFAULT_RECURSION_LIMIT, get_heartbeat_interval
from langchain_core.messages import AIMessageChunk
from api.chat.event_processor import extract_chunk_content
from utils.sse import send_sse_data
from utils.common.logging_utils import get_agent_logger

logger = get_agent_logger()


async def generate_simple_stream(
    graph,
    langchain_messages: list,
    callback_handler,
    session_id: str,
    **kwargs
) -> AsyncGenerator[str, None]:
    """简化流式：用 stream_mode='messages' 直接流式 content。

    替代复杂的 astream_events + think_flag + buffers 逻辑（该逻辑 content 被过滤导致空）。
    generate_stream_response 已删除（见模块 docstring）。
    """
    # P2-16: 不在此发 {'status':'started'}——调用方 react_executor 已发 send_config+send_started；
    # 此处只负责流式 content，避免重复 started 事件与双 schema。
    recursion_limit = get_config('agent.recursion_limit', DEFAULT_RECURSION_LIMIT)
    cfg = {
        'callbacks': [callback_handler],
        'recursion_limit': recursion_limit,
        'configurable': {'thread_id': session_id or 'default'}
    }
    # 注入 langfuse callbacks + session_id 关联（启用时零影响）
    from utils.observability.langfuse_handler import attach_callbacks
    cfg = attach_callbacks(cfg, session_id=session_id)
    full_content = ''
    # P1-3: 心跳——上游 LLM 挂起时周期性发 ping 保活，防网关超时掐断
    last_heartbeat = time.time()
    heartbeat_interval = get_heartbeat_interval()
    try:
        async for msg, _meta in graph.astream(
            {'messages': langchain_messages}, config=cfg, stream_mode='messages'
        ):
            if isinstance(msg, AIMessageChunk) and msg.content:
                # P2-17: content 可能是 list（多 part/多模态），用提取器取文本，避免 str() 产出 repr
                chunk_text = extract_chunk_content(msg, "content") or ""
                if not chunk_text and isinstance(msg.content, str):
                    chunk_text = msg.content
                if not chunk_text:
                    # list 型 content：拼接各 part 的 text
                    if isinstance(msg.content, list):
                        parts = []
                        for p in msg.content:
                            if isinstance(p, str):
                                parts.append(p)
                            elif isinstance(p, dict) and p.get('type') == 'text':
                                parts.append(p.get('text', ''))
                        chunk_text = "".join(parts)
                if chunk_text:
                    full_content += chunk_text
                    yield send_sse_data({'content': chunk_text, 'reasoning_content': ''})
            # P1-3: 心跳仅在距上次发心跳超过阈值时补发
            if time.time() - last_heartbeat >= heartbeat_interval:
                yield send_sse_data({'ping': _dt.datetime.now().isoformat()})
                last_heartbeat = time.time()
        # fallback：流式 content 空（如仅调用工具）时，从 callback_handler 的 final messages 提取
        # 避免重新 ainvoke 导致 LLM/工具双重调用
        if not full_content and hasattr(callback_handler, 'get_final_messages'):
            try:
                final_msgs = callback_handler.get_final_messages() or []
                from api.chat.stream.helpers import _get_last_ai_message
                last_ai = _get_last_ai_message(final_msgs)
                if last_ai and hasattr(last_ai, 'content') and last_ai.content:
                    yield send_sse_data({'content': str(last_ai.content), 'reasoning_content': ''})
            except Exception as e:
                logger.warning(f"[generate_simple_stream] fallback: {e}")
    except Exception as e:
        logger.error(f"[generate_simple_stream] {e}", exc_info=True)
        yield send_sse_data({'error': str(e)})
    yield send_sse_data({'content': '', 'reasoning_content': '', 'done': True})
