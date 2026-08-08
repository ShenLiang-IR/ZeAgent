from typing import Optional, Tuple
from langchain_core.messages import AIMessage
from loguru import logger
from utils.config import get_config
from utils.common.constants import DEFAULT_DEBUG
def _debug_log(message: str):
    if get_config('agent.debug', DEFAULT_DEBUG):
        logger.debug(f"[DEBUG] {message}")
def _get_execution_panel_enabled() -> bool:
    try:
        return get_config('agent.enable_execution_panel', False)
    except Exception as e:
        logger.warning(f"Error reading enable_execution_panel config: {e}")
    return False
def _unwrap_overwrite(obj):
    try:
        if hasattr(obj, 'value'):
            return _unwrap_overwrite(obj.value)
        if isinstance(obj, dict):
            return {k: _unwrap_overwrite(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_unwrap_overwrite(v) for v in obj]
        return obj
    except Exception:
        return obj
def _get_last_ai_message(messages):
    if not messages:
        return None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return msg
    return None
def _is_internal_data_structure(content: str) -> bool:
    if not content or not content.strip():
        return False
    try:
        import json
        if not content.strip().startswith('{'):
            return False
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return False
        has_tasks = parsed.get('tasks') and isinstance(parsed.get('tasks'), list)
        has_workflow_fields = (
            parsed.get('id') or 
            parsed.get('name') or 
            parsed.get('execution_mode') or
            parsed.get('merge_mode')
        )
        has_task_id = parsed.get('task_id')
        has_status = parsed.get('status')
        has_task_name = parsed.get('task_name')
        if (has_tasks or has_workflow_fields) and not parsed.get('output'):
            return True
        if (has_task_id and has_status) or (has_task_name and parsed.get('result')):
            return True
        return False
    except (json.JSONDecodeError, TypeError):
        return False
async def _get_checkpoint_content_with_validation(
    session_id: str,
    current_request_id: Optional[str],
    logger
) -> Tuple[str, str]:
    if not current_request_id:
        logger.debug(f"[Workflow]  request_id")
        return "", ""
    return "", ""