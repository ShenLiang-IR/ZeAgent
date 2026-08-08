from typing import List, Dict, Any, Optional
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
def attach_tool_results_to_message(
    message: AIMessage,
    tool_results: List[Dict[str, Any]]
) -> None:
    if not tool_results:
        return
    if not hasattr(message, 'response_metadata') or not message.response_metadata:
        message.response_metadata = {}
    message.response_metadata["tool_results"] = tool_results
def get_tool_results_from_message(message: BaseMessage) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(message, AIMessage):
        return None
    if not hasattr(message, 'response_metadata') or not message.response_metadata:
        return None
    return message.response_metadata.get("tool_results")
def ensure_message_metadata(message: AIMessage, session_id: str, request_id: Optional[str] = None) -> None:
    if not hasattr(message, 'response_metadata') or not message.response_metadata:
        if request_id is None:
            from .message_metadata import create_request_id
            request_id = create_request_id(session_id)
        from .message_metadata import create_final_response_metadata
        message.response_metadata = create_final_response_metadata(
            request_id=request_id,
            session_id=session_id
        )


def extract_user_input_from_messages(messages) -> str:
    """从 LangChain 消息列表中提取最后一条 HumanMessage 的文本内容。"""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            if isinstance(msg.content, str):
                return msg.content
            elif isinstance(msg.content, list):
                text_parts = [
                    part.get('text', '')
                    for part in msg.content
                    if isinstance(part, dict) and part.get('type') == 'text'
                ]
                return ' '.join(text_parts)
    return ""