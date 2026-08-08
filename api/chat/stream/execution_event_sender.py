import datetime
import time
from typing import Optional, Dict, Any, List
from ..sse_utils import send_sse_data, _send_execution_event
from .helpers import _get_execution_panel_enabled
class ExecutionEventSender:
    def __init__(self, enabled: Optional[bool] = None):
        self.enabled = enabled if enabled is not None else _get_execution_panel_enabled()
    def send_config(self) -> str:
        if not self.enabled:
            return ""
        return send_sse_data({
            'config': {
                'enable_execution_panel': self.enabled
            }
        })
    def send_planning_start(self, user_input: str) -> str:
        if not self.enabled:
            return ""
        return send_sse_data({
            'event': 'planning_start',
            'data': {'user_input': user_input[:200]}
        })
    def send_planning_complete(self, tasks_count: int) -> str:
        if not self.enabled:
            return ""
        return send_sse_data({
            'event': 'planning_complete',
            'data': {
                'tasks_count': tasks_count
            }
        })
    def send_workflow_planning(self, workflow_plan, session_id: str) -> str:
        try:
            metadata = {
                'timestamp': datetime.datetime.now().isoformat(),
                'run_id': f"planning_{session_id}_{int(time.time())}",
                'parent_id': None
            }
            execution_mode = getattr(workflow_plan, 'execution_mode', getattr(workflow_plan, 'mode', 'unknown'))
            if hasattr(execution_mode, 'value'):
                execution_mode_val = execution_mode.value
            else:
                execution_mode_val = str(execution_mode)
            merge_mode = getattr(workflow_plan, 'merge_mode', getattr(workflow_plan, 'mode', 'unknown'))
            if hasattr(merge_mode, 'value'):
                merge_mode_val = merge_mode.value
            else:
                merge_mode_val = str(merge_mode)
            event_data = {
                'workflow': workflow_plan.to_dict(),
                'tasks_count': len(workflow_plan.tasks),
                'execution_mode': execution_mode_val,
                'merge_mode': merge_mode_val
            }
            return _send_execution_event('plan', metadata, event_data)
        except Exception as e:
            from loguru import logger
            logger.error(f"[Planner]  planning_event : {e}")
            return ""
    def send_execution_start(self, workflow_name: str) -> str:
        return send_sse_data({
            'event': 'execution_start',
            'data': {'workflow_name': workflow_name}
        })
    def send_task_event(
        self,
        task_result,
        task_def=None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        include_full_output: bool = False,
        max_output_length: int = 200
    ) -> str:
        output = task_result.output
        if not include_full_output and output:
            output_len = len(str(output))
            if output_len > max_output_length:
                output = f"[ {output_len} ]"
            else:
                output = output
        task_data = {
            "task_id": task_result.task_id,
            "task_name": task_result.task_name,
            "status": task_result.status.value,
            "task_type": task_result.task_type.value,
            "duration": task_result.duration,
            "output": output,
            "error": task_result.error
        }
        if task_def:
            task_data["agent"] = task_def.agent
            task_data["description"] = task_def.description
        if tool_calls:
            task_data["tool_calls"] = self._summarize_tool_calls(tool_calls)
        return send_sse_data({
            "event": f"task_{task_result.status.value}",
            "data": task_data
        })
    def send_workflow_summary(self, summary: Dict[str, Any]) -> str:
        return send_sse_data({
            'event': 'workflow_summary',
            'data': {
                'total_tasks': summary['total_tasks'],
                'completed': summary['completed'],
                'failed': summary['failed'],
                'success_rate': summary['success_rate'],
                'total_duration': summary['total_duration']
            }
        })
    def send_execution_complete(self, summary: Dict[str, Any]) -> str:
        return send_sse_data({
            'event': 'execution_complete',
            'data': summary
        })
    def create_planner_event_sender(self, session_id: str):
        if not self.enabled:
            return None
        def event_sender(event_type: str, metadata: dict, data: dict):
            try:
                event_str = _send_execution_event(event_type, metadata, data)
                from loguru import logger
                logger.debug(f"[Planner] : {event_type}")
            except Exception as e:
                from loguru import logger
                logger.warning(f"[Planner] : {e}")
        return event_sender
    @staticmethod
    def _summarize_tool_calls(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tool_calls_summary = []
        for tool_call in tool_calls:
            tool_name = tool_call.get('tool_name', tool_call.get('name', 'unknown'))
            summary = {
                'type': tool_call.get('type'),
                'tool_name': tool_name,
            }
            if tool_call.get('type') == 'tool_start':
                input_data = tool_call.get('input_data', tool_call.get('input', {}))
                input_preview = str(input_data)[:200] if input_data else ""
                if len(str(input_data)) > 200:
                    summary['input_preview'] = input_preview + "..."
                else:
                    summary['input_preview'] = input_preview
            elif tool_call.get('type') == 'tool_end':
                output = tool_call.get('output', tool_call.get('raw_output', ''))
                output_length = len(str(output))
                summary['output_length'] = output_length
                output_preview = str(output)[:200]
                if output_length > 200:
                    summary['output_preview'] = output_preview + "..."
                else:
                    summary['output_preview'] = output_preview
            else:
                input_data = tool_call.get('input_data', tool_call.get('input', {}))
                if input_data:
                    input_preview = str(input_data)[:200] if input_data else ""
                    if len(str(input_data)) > 200:
                        summary['input_preview'] = input_preview + "..."
                    else:
                        summary['input_preview'] = input_preview
                output = tool_call.get('output', tool_call.get('raw_output', ''))
                if output is not None:
                    output_length = len(str(output))
                    summary['output_length'] = output_length
                    output_preview = str(output)[:200]
                    if output_length > 200:
                        summary['output_preview'] = output_preview + "..."
                    else:
                        summary['output_preview'] = output_preview
                if tool_call.get('duration'):
                    summary['duration'] = tool_call.get('duration')
                if tool_call.get('error'):
                    summary['error'] = tool_call.get('error')
            tool_calls_summary.append(summary)
        return tool_calls_summary