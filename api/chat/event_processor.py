import json
import time
from typing import Optional
def normalize_run_id(run_id) -> str:
    return str(run_id) if run_id else ""
def find_agent_name_in_run_stack(run_id_str: str, callback_handler) -> Optional[str]:
    if not callback_handler or not hasattr(callback_handler, 'run_stack'):
        return None
    for run_info in callback_handler.run_stack:
        stack_run_id = run_info.get('run_id')
        stack_run_id_str = normalize_run_id(stack_run_id)
        if stack_run_id_str == run_id_str:
            return run_info.get('agent_name')
    return None
def is_subagent_chain_in_on_chain_start(
    chain_name: str,
    run_id_str: str,
    parent_run_id,
    subagent_run_ids: set,
    callback_handler
) -> bool:
    if "SummarizationMiddleware" in chain_name and parent_run_id:
        parent_run_id_str = normalize_run_id(parent_run_id)
        if parent_run_id_str in subagent_run_ids:
            subagent_run_ids.add(run_id_str)
            return True
        agent_name = find_agent_name_in_run_stack(parent_run_id_str, callback_handler)
        if agent_name:
            subagent_run_ids.add(run_id_str)
            subagent_run_ids.add(parent_run_id_str)
            return True
    if callback_handler and hasattr(callback_handler, 'subagent_names'):
        chain_name_lower = chain_name.lower()
        for subagent_name in callback_handler.subagent_names:
            if subagent_name.lower() in chain_name_lower:
                subagent_run_ids.add(run_id_str)
                return True
    if parent_run_id:
        parent_run_id_str = normalize_run_id(parent_run_id)
        if parent_run_id_str in subagent_run_ids:
            subagent_run_ids.add(run_id_str)
            return True
        agent_name = find_agent_name_in_run_stack(parent_run_id_str, callback_handler)
        if agent_name:
            subagent_run_ids.add(run_id_str)
            return True
    if callback_handler and hasattr(callback_handler, '_find_agent_from_task_tool'):
        try:
            task_agent = callback_handler._find_agent_from_task_tool()
            if task_agent:
                subagent_run_ids.add(run_id_str)
                return True
        except Exception:
            pass
    agent_name = find_agent_name_in_run_stack(run_id_str, callback_handler)
    if agent_name:
        subagent_run_ids.add(run_id_str)
        return True
    return False
def is_from_subagent_in_on_chat_model_stream(
    run_id,
    parent_run_id,
    subagent_run_ids: set,
    callback_handler
) -> bool:
    run_id_str = normalize_run_id(run_id)
    if run_id_str and run_id_str in subagent_run_ids:
        return True
    if run_id_str:
        agent_name = find_agent_name_in_run_stack(run_id_str, callback_handler)
        if agent_name:
            subagent_run_ids.add(run_id_str)
            return True
    if parent_run_id:
        parent_run_id_str = normalize_run_id(parent_run_id)
        if parent_run_id_str in subagent_run_ids:
            if run_id_str:
                subagent_run_ids.add(run_id_str)
            return True
        agent_name = find_agent_name_in_run_stack(parent_run_id_str, callback_handler)
        if agent_name:
            if run_id_str:
                subagent_run_ids.add(run_id_str)
            subagent_run_ids.add(parent_run_id_str)
            return True
        if callback_handler and hasattr(callback_handler, '_find_agent_from_task_tool'):
            try:
                task_agent = callback_handler._find_agent_from_task_tool()
                if task_agent:
                    if run_id_str:
                        subagent_run_ids.add(run_id_str)
                    subagent_run_ids.add(parent_run_id_str)
                    return True
            except Exception:
                pass
    if not parent_run_id and run_id_str:
        agent_name = find_agent_name_in_run_stack(run_id_str, callback_handler)
        if agent_name:
            subagent_run_ids.add(run_id_str)
            return True
        if callback_handler and hasattr(callback_handler, '_find_agent_from_task_tool'):
            try:
                task_agent = callback_handler._find_agent_from_task_tool()
                if task_agent and callback_handler.run_stack:
                    latest_chain = callback_handler.run_stack[-1]
                    latest_agent_name = latest_chain.get('agent_name')
                    if latest_agent_name:
                        subagent_run_ids.add(run_id_str)
                        return True
            except Exception:
                pass
    return False
def extract_chunk_content(chunk, attr_name: str = "content"):
    if chunk is None:
        return None
    if hasattr(chunk, attr_name):
        value = getattr(chunk, attr_name, None)
        if value is not None:
            return value
    if isinstance(chunk, dict):
        value = chunk.get(attr_name)
        if value is not None:
            return value
    if attr_name == 'content' and hasattr(chunk, 'text'):
        return getattr(chunk, 'text', None)
    if hasattr(chunk, 'response_metadata'):
        metadata = getattr(chunk, 'response_metadata', {})
        if isinstance(metadata, dict) and attr_name in metadata:
            return metadata.get(attr_name)
    if isinstance(chunk, str):
        return chunk
    return None
def build_tool_result(tool_name: str, tool_output: any) -> dict:
    raw_data = tool_output
    if isinstance(tool_output, str):
        try:
            raw_data = json.loads(tool_output)
        except (json.JSONDecodeError, TypeError):
            raw_data = tool_output
    chart_type = None
    visualization_hint = None
    if isinstance(raw_data, dict):
        chart_type = raw_data.get('chart_type')
        visualization_hint = raw_data.get('visualization_hint')
    return {
        "tool_name": tool_name,
        "raw_data": raw_data,
        "timestamp": int(time.time() * 1000),
        "chart_type": chart_type,
        "visualization_hint": visualization_hint
    }
def extract_metadata(event):
    metadata = event.get("metadata", {})
    return {
        'timestamp': metadata.get("timestamp") or event.get("timestamp"),
        'run_id': normalize_run_id(event.get("run_id", "")),
        'parent_id': normalize_run_id(event.get("parent_run_id")) if event.get("parent_run_id") else None,
        'name': event.get("name", ""),
        'event': event.get("event", "")
    }
def extract_token_usage(event_data):
    token_usage = {}
    if "token_usage" in event_data:
        token_usage = event_data["token_usage"]
    elif "usage_metadata" in event_data:
        usage = event_data["usage_metadata"]
        token_usage = {
            'total_tokens': usage.get('total_tokens', 0) or usage.get('total_token_count', 0),
            'prompt_tokens': usage.get('input_tokens', 0) or usage.get('prompt_tokens', 0),
            'completion_tokens': usage.get('output_tokens', 0) or usage.get('completion_tokens', 0)
        }
    elif "response_metadata" in event_data:
        metadata = event_data["response_metadata"]
        if "token_usage" in metadata:
            token_usage = metadata["token_usage"]
        elif "usage_metadata" in metadata:
            usage = metadata["usage_metadata"]
            token_usage = {
                'total_tokens': usage.get('total_tokens', 0) or usage.get('total_token_count', 0),
                'prompt_tokens': usage.get('input_tokens', 0) or usage.get('prompt_tokens', 0),
                'completion_tokens': usage.get('output_tokens', 0) or usage.get('completion_tokens', 0)
            }
    return token_usage if token_usage else {}
def get_agent_name_from_event(event, callback_handler):
    if not callback_handler or not hasattr(callback_handler, 'run_stack'):
        return None
    run_id = event.get("run_id")
    parent_run_id = event.get("parent_run_id")
    if parent_run_id:
        parent_run_id_str = normalize_run_id(parent_run_id)
        for run_info in callback_handler.run_stack:
            if run_info.get('run_id') == parent_run_id_str:
                agent_name = run_info.get('agent_name')
                if agent_name:
                    return agent_name
        if hasattr(callback_handler, 'tool_run_map') and parent_run_id_str in callback_handler.tool_run_map:
            tool_identifier = callback_handler.tool_run_map[parent_run_id_str]
            if tool_identifier.startswith('task:'):
                subagent_type = tool_identifier.split(':', 1)[1]
                return subagent_type.replace('_', ' ').title()
            if hasattr(callback_handler, '_infer_agent_from_tool'):
                inferred_agent = callback_handler._infer_agent_from_tool(tool_identifier)
                if inferred_agent:
                    return inferred_agent
        if hasattr(callback_handler, '_find_agent_from_task_tool'):
            try:
                task_agent = callback_handler._find_agent_from_task_tool()
                if task_agent:
                    return task_agent
            except Exception:
                pass
        if callback_handler.run_stack:
            for run_info in reversed(callback_handler.run_stack):
                agent_name = run_info.get('agent_name')
                if agent_name:
                    return agent_name
    if run_id:
        run_id_str = normalize_run_id(run_id)
        for run_info in callback_handler.run_stack:
            if run_info.get('run_id') == run_id_str:
                agent_name = run_info.get('agent_name')
                if agent_name:
                    return agent_name
    if callback_handler.run_stack:
        latest_chain = callback_handler.run_stack[-1]
        return latest_chain.get('agent_name')
    return None
def extract_messages_from_event_data(event_data):
    if not isinstance(event_data, dict):
        return None
    if "messages" in event_data:
        return event_data.get('messages')
    if "output" in event_data:
        output = event_data.get("output", {})
        if isinstance(output, dict):
            if "messages" in output:
                return output["messages"]
            if "values" in output and isinstance(output["values"], dict) and "messages" in output["values"]:
                return output["values"]["messages"]
        if isinstance(output, list):
            return output
    if "values" in event_data and isinstance(event_data["values"], dict) and "messages" in event_data["values"]:
        return event_data["values"]["messages"]
    if "updates" in event_data and isinstance(event_data["updates"], dict):
        updates = event_data["updates"]
        for _, value in updates.items():
            if hasattr(value, 'value'):
                value = value.value
            if isinstance(value, dict) and "messages" in value:
                return value["messages"]
            if isinstance(value, list):
                return value
    return None