from loguru import logger
import json
import re
import time
from typing import List, Dict, Optional
from langchain_core.messages import AIMessage, ToolMessage, BaseMessage

# think 标签常量（统一各处 think 标签模式定义）
THINK_OPEN = "<think"
THINK_CLOSE = "</think>"
def is_data_query_tool(tool_name: str) -> bool:
    if not tool_name:
        return False
    data_query_patterns = ['get_', 'search_', 'query_', 'fetch_', 'find_', 'list_']
    tool_name_lower = str(tool_name).lower()
    return any(pattern in tool_name_lower for pattern in data_query_patterns)
def extract_tool_results(messages: List[BaseMessage], initial_message_count: int = 0) -> List[Dict]:
    tool_results = []
    relevant_messages = messages[initial_message_count:] if initial_message_count > 0 else messages
    for msg in relevant_messages:
        if isinstance(msg, ToolMessage):
            tool_name = getattr(msg, 'name', None) or 'unknown'
            content = getattr(msg, 'content', '')
            if is_data_query_tool(tool_name):
                try:
                    if isinstance(content, str):
                        try:
                            raw_data = json.loads(content)
                        except json.JSONDecodeError:
                            raw_data = content
                    else:
                        raw_data = content
                    chart_type = None
                    visualization_hint = None
                    if isinstance(raw_data, dict):
                        chart_type = raw_data.get('chart_type')
                        visualization_hint = raw_data.get('visualization_hint')
                    tool_results.append({
                        "tool_name": tool_name,
                        "raw_data": raw_data,
                        "timestamp": int(time.time() * 1000),
                        "chart_type": chart_type,
                        "visualization_hint": visualization_hint
                    })
                except Exception as e:
                    print(f"Warning: Failed to parse tool result for {tool_name}: {str(e)}")
                    tool_results.append({
                        "tool_name": tool_name,
                        "raw_data": str(content),
                        "timestamp": int(time.time() * 1000),
                        "chart_type": None,
                        "visualization_hint": None
                    })
    return tool_results
def extract_reasoning_from_content(content: str, _caller: str = "") -> tuple[str, str]:
    if not content or not isinstance(content, str):
        return "", content or ""
    import traceback
    caller_info = _caller or ''.join(traceback.format_stack()[-3].strip().split('\n')[-1].strip())
    logger.debug(f"[extract_reasoning_from_content] : {caller_info}")
    cleaned_content = content
    original_len = len(cleaned_content)
    patterns = [
        (r'<think>(.*?)</think>', ''),
        (r'(.*?)</think>', ''),
    ]
    reasoning_parts = []
    for pattern, description in patterns:
        think_contents = re.findall(pattern, cleaned_content, flags=re.DOTALL)
        for think_content in think_contents:
            if think_content.strip():
                reasoning_parts.append(think_content.strip())
                logger.debug(f"[{description}] : {think_content}")
        cleaned_content = re.sub(pattern, '', cleaned_content, flags=re.DOTALL)
    reasoning_content = "\n\n".join(reasoning_parts) if reasoning_parts else ""
    cleaned_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', cleaned_content)
    cleaned_content = cleaned_content.strip()
    return reasoning_content, cleaned_content
def extract_reasoning_content(messages: List[BaseMessage], initial_message_count: int = 0, model_name: Optional[str] = None) -> str:
    reasoning_parts = []
    adapter = None
    try:
        from utils.llm.model_adapters import get_adapter
        adapter = get_adapter(model_name)
    except Exception:
        adapter = None
    relevant_messages = messages[initial_message_count:] if initial_message_count > 0 else messages
    for i, msg in enumerate(relevant_messages):
        if isinstance(msg, AIMessage):
            if adapter:
                reasoning, _ = adapter.extract_reasoning(msg)
                if reasoning:
                    reasoning_parts.append(f"{reasoning}\n\n")
                else:
                    if hasattr(msg, 'content') and msg.content:
                        content_str = str(msg.content)
                        reasoning_from_content, _ = extract_reasoning_from_content(content_str)
                        if reasoning_from_content:
                            reasoning_parts.append(f"{reasoning_from_content}\n\n")
            else:
                if hasattr(msg, 'reasoning_content') and msg.reasoning_content:
                    reasoning_parts.append(f"{msg.reasoning_content}\n\n")
                if hasattr(msg, 'response_metadata') and msg.response_metadata:
                    reasoning = msg.response_metadata.get('reasoning_content')
                    if reasoning:
                        reasoning_parts.append(f"{reasoning}\n\n")
                if hasattr(msg, 'additional_kwargs') and msg.additional_kwargs:
                    thinking = msg.additional_kwargs.get('thinking') or msg.additional_kwargs.get('reasoning')
                    if thinking:
                        reasoning_parts.append(f"{thinking}\n\n")
                if hasattr(msg, 'content') and msg.content:
                    content_str = str(msg.content)
                    reasoning_from_content, _ = extract_reasoning_from_content(content_str)
                    if reasoning_from_content:
                        reasoning_parts.append(f"{reasoning_from_content}\n\n")
    if not reasoning_parts:
        return ""
    reasoning_text = "".join(reasoning_parts).rstrip()
    if reasoning_text:
        reasoning_text = f"# Agent \n\n{reasoning_text}"
    return reasoning_text