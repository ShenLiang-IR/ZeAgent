from typing import Dict, Any, Optional
import time
from enum import Enum
class MessageType(str, Enum):
    USER_INPUT = "user_input"
    FINAL_RESPONSE = "final_response"
    SUBAGENT_RESPONSE = "subagent_response"
    SYNTHESIS_RESPONSE = "synthesis_response"
    WORKFLOW_PLAN = "workflow_plan"
    TASK_RESULT = "task_result"
    TOOL_INTERMEDIATE = "tool_intermediate"
    SYSTEM_INTERNAL = "system_internal"
class MessageSource(str, Enum):
    MAIN_AGENT = "main_agent"
    SUBAGENT = "subagent"
    WORKFLOW_SYNTHESIS = "workflow_synthesis"
    WORKFLOW_PLANNER = "workflow_planner"
    SYSTEM = "system"
def create_request_id(session_id: str) -> str:
    timestamp_ms = int(time.time() * 1000)
    return f"{session_id}_{timestamp_ms}"
def create_user_input_metadata(
    request_id: str,
    session_id: str
) -> Dict[str, Any]:
    return {
        "message_type": MessageType.USER_INPUT.value,
        "is_user_visible": True,
        "source": MessageSource.SYSTEM.value,
        "request_id": request_id,
        "request_timestamp": time.time(),
        "is_current_request": True,
        "metadata_version": "1.0",
        "created_by": "stream_handler"
    }
def create_final_response_metadata(
    request_id: str,
    session_id: str,
    workflow_id: Optional[str] = None,
    workflow_name: Optional[str] = None,
    merge_mode: Optional[str] = None,
    performance: Optional[Dict[str, Any]] = None,
    content_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    metadata = {
        "message_type": MessageType.FINAL_RESPONSE.value,
        "is_user_visible": True,
        "source": MessageSource.WORKFLOW_SYNTHESIS.value,
        "request_id": request_id,
        "request_timestamp": time.time(),
        "is_current_request": True,
        "metadata_version": "1.0",
        "created_by": "workflow_executor"
    }
    if workflow_id:
        metadata["workflow_id"] = workflow_id
    if workflow_name:
        metadata["workflow_name"] = workflow_name
    if merge_mode:
        metadata["merge_mode"] = merge_mode
    if performance:
        metadata["performance"] = performance
    if content_metadata:
        metadata["content_metadata"] = content_metadata
    return metadata
def create_subagent_response_metadata(
    request_id: str,
    session_id: str,
    agent_name: str,
    task_id: Optional[str] = None,
    task_name: Optional[str] = None,
    task_type: Optional[str] = None,
    workflow_id: Optional[str] = None,
    performance: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    metadata = {
        "message_type": MessageType.SUBAGENT_RESPONSE.value,
        "is_user_visible": True,
        "source": MessageSource.SUBAGENT.value,
        "request_id": request_id,
        "request_timestamp": time.time(),
        "is_current_request": True,
        "agent_name": agent_name,
        "metadata_version": "1.0",
        "created_by": "workflow_executor"
    }
    if task_id:
        metadata["task_id"] = task_id
    if task_name:
        metadata["task_name"] = task_name
    if task_type:
        metadata["task_type"] = task_type
    if workflow_id:
        metadata["workflow_id"] = workflow_id
    if performance:
        metadata["performance"] = performance
    return metadata
def create_internal_message_metadata(
    message_type: MessageType,
    source: MessageSource,
    request_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    task_id: Optional[str] = None
) -> Dict[str, Any]:
    metadata = {
        "message_type": message_type.value,
        "is_user_visible": False,
        "source": source.value,
        "metadata_version": "1.0",
        "created_by": "workflow_executor"
    }
    if request_id:
        metadata["request_id"] = request_id
    if workflow_id:
        metadata["workflow_id"] = workflow_id
    if task_id:
        metadata["task_id"] = task_id
    return metadata
def is_user_visible(metadata: Optional[Dict[str, Any]]) -> bool:
    if not metadata:
        return True
    return metadata.get("is_user_visible", True)
def is_current_request(metadata: Optional[Dict[str, Any]], request_id: Optional[str] = None) -> bool:
    if not metadata:
        return False
    if request_id:
        return metadata.get("request_id") == request_id
    return metadata.get("is_current_request", False)
def get_message_type(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
    if not metadata:
        return None
    return metadata.get("message_type")
def is_internal_message(metadata: Optional[Dict[str, Any]]) -> bool:
    if not metadata:
        return False
    message_type = get_message_type(metadata)
    if not message_type:
        return False
    internal_types = [
        MessageType.WORKFLOW_PLAN.value,
        MessageType.TASK_RESULT.value,
        MessageType.TOOL_INTERMEDIATE.value,
        MessageType.SYSTEM_INTERNAL.value
    ]
    return message_type in internal_types