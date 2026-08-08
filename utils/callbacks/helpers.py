import json
from loguru import logger
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from ..common.sanitize import sanitize_for_json
from ..common.constants import get_event_queue_max_size
from ..common.logging_utils import get_agent_logger
logger = get_agent_logger()
def extract_model_name_unified(serialized: Optional[Dict[str, Any]], fallback_name: Optional[str] = None) -> str:
    if serialized:
        name = serialized.get('_type')
        if name and name != 'unknown':
            return name
        model_id = serialized.get('id')
        if model_id:
            if isinstance(model_id, list) and len(model_id) > 0:
                return model_id[-1]
            if isinstance(model_id, str):
                return model_id
        name = serialized.get('name')
        if name:
            return name
    return fallback_name or 'unknown'
def extract_tool_name_unified(serialized: Optional[Dict[str, Any]], kwargs: Optional[Dict[str, Any]] = None) -> str:
    if serialized and 'name' in serialized:
        return serialized.get('name', 'unknown')
    if kwargs and 'name' in kwargs:
        return kwargs.get('name', 'unknown')
    return 'unknown'
def extract_chain_name_from_serialized(serialized: Optional[Dict[str, Any]]) -> str:
    if not serialized:
        return 'unknown'
    chain_name = serialized.get('name', 'unknown')
    if chain_name == 'unknown':
        chain_name = serialized.get('_type', 'unknown')
    if chain_name == 'unknown':
        chain_id = serialized.get('id')
        if chain_id:
            if isinstance(chain_id, list) and len(chain_id) > 0:
                chain_name = chain_id[-1]
            elif isinstance(chain_id, str):
                chain_name = chain_id
    return chain_name
def extract_chain_name_from_kwargs(kwargs: Dict[str, Any]) -> str:
    if not kwargs:
        return 'unknown'
    if 'name' in kwargs:
        return kwargs.get('name', 'unknown')
    if 'tags' in kwargs:
        tags = kwargs.get('tags', [])
        if tags and isinstance(tags, list) and len(tags) > 0:
            return str(tags[0])
    return 'unknown'
def extract_chain_name_from_parent(parent_run_id: Optional[Union[str, Any]], run_stack: List[Dict[str, Any]]) -> str:
    if not parent_run_id:
        return 'unknown'
    parent_run_id_str = get_parent_run_id_str(parent_run_id)
    if not parent_run_id_str:
        return 'unknown'
    for run_info in run_stack:
        if run_info.get('run_id') == parent_run_id_str:
            parent_chain_name = run_info.get('chain_name')
            if parent_chain_name and parent_chain_name != 'unknown':
                return f"{parent_chain_name}_child"
    return 'unknown'
def extract_chain_name_unified(
    serialized: Optional[Dict[str, Any]], 
    kwargs: Optional[Dict[str, Any]], 
    parent_run_id: Optional[Union[str, Any]],
    run_stack: List[Dict[str, Any]]
) -> str:
    if serialized:
        name = extract_chain_name_from_serialized(serialized)
        if name and name != 'unknown':
            return name
    if kwargs:
        name = extract_chain_name_from_kwargs(kwargs)
        if name and name != 'unknown':
            return name
    return extract_chain_name_from_parent(parent_run_id, run_stack)
def get_run_id(run_id: Optional[Union[str, Any]] = None) -> str:
    if run_id:
        if not isinstance(run_id, str):
            run_id = str(run_id)
        return run_id
    return f"run_{int(time.time() * 1000)}"
def format_duration(duration: float) -> str:
    if duration < 1:
        return f"{duration*1000:.0f}ms"
    return f"{duration:.2f}s"
def get_parent_run_id_str(parent_run_id: Optional[Union[str, Any]]) -> Optional[str]:
    if parent_run_id:
        return str(parent_run_id)
    return None
def log_chain_debug(
    session_id: str,
    verbose: bool,
    run_id: str, 
    chain_name: str, 
    serialized: Optional[Dict[str, Any]], 
    parent_run_id: Optional[Union[str, Any]], 
    kwargs: Dict[str, Any]
):
    if chain_name != 'unknown' or serialized is not None:
        return
    parent_run_id_str = get_parent_run_id_str(parent_run_id)
    debug_msg = (
        f"Chain serialized  None, run_id={run_id[:8]}, "
        f"parent_run_id={parent_run_id_str[:8] if parent_run_id_str else None}, "
        f"chain_name={chain_name}"
    )
    extra = {
        'event_type': 'chain_start_debug',
        'session_id': session_id,
        'run_id': run_id,
        'kwargs_keys': list(kwargs.keys()) if kwargs else []
    }
    logger.log(10, debug_msg, extra=extra)
def add_event(
    event_queue: List[Dict[str, Any]],
    event_type: str, 
    run_id: Union[str, Any], 
    parent_run_id: Optional[Union[str, Any]] = None, 
    data: Optional[Dict[str, Any]] = None
):
    run_id_str = str(run_id) if run_id else ""
    parent_run_id_str = str(parent_run_id) if parent_run_id else None
    sanitized_data = sanitize_for_json(data) if data else {}
    event = {
        'event_type': event_type,
        'timestamp': datetime.now().isoformat(),
        'run_id': run_id_str,
        'parent_run_id': parent_run_id_str,
        'data': sanitized_data
    }
    event_queue.append(event)
    max_size = get_event_queue_max_size()
    if max_size and len(event_queue) > max_size:
        overflow = len(event_queue) - max_size
        if overflow > 0:
            del event_queue[:overflow]
def get_events(event_queue: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    events = event_queue.copy()
    event_queue.clear()
    sanitized_events = []
    for event in events:
        try:
            sanitized_event = sanitize_for_json(event)
            sanitized_events.append(sanitized_event)
        except Exception as e:
            print(f"Warning: Failed to sanitize event {event.get('event_type', 'unknown')}: {e}")
            try:
                json.dumps(event, default=str)
                sanitized_events.append(event)
            except (TypeError, ValueError):
                print(f"Error: Event {event.get('event_type', 'unknown')} cannot be serialized, skipping")
    return sanitized_events