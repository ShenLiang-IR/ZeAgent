import time
from loguru import logger
from typing import Any, Dict, Optional, Union
from .base_callbacks import BaseCallbacksMixin
from .helpers import (
    get_run_id,
    format_duration,
    get_parent_run_id_str,
    add_event,
    extract_chain_name_unified,
    log_chain_debug
)
from .agent_inference import (
    extract_agent_name,
    infer_agent_from_tool,
    find_agent_from_task_tool
)
from ..common.logging_utils import get_agent_logger
logger = get_agent_logger()
class ChainCallbacksMixin(BaseCallbacksMixin):
    def on_chain_start(
        self,
        serialized: Optional[Dict[str, Any]],
        inputs: Optional[Dict[str, Any]],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        run_id = get_run_id(run_id)
        self.start_times[run_id] = time.time()
        chain_name = extract_chain_name_unified(serialized, kwargs or {}, parent_run_id, self.run_stack)
        if serialized is None or chain_name == 'unknown':
            log_chain_debug(
                self.session_id,
                self.verbose,
                run_id, 
                chain_name, 
                serialized, 
                parent_run_id, 
                kwargs or {}
            )
        agent_name = extract_agent_name(chain_name, self.subagent_names)
        if not agent_name and parent_run_id:
            parent_run_id_str = get_parent_run_id_str(parent_run_id)
            for run_info in self.run_stack:
                if run_info.get('run_id') == parent_run_id_str:
                    agent_name = run_info.get('agent_name')
                    break
            if not agent_name:
                for run_info in reversed(self.run_stack):
                    if run_info.get('agent_name'):
                        agent_name = run_info.get('agent_name')
                        break
            task_agent = find_agent_from_task_tool(self.tool_run_map)
            if task_agent:
                agent_name = task_agent
                if self.verbose:
                    print(f"[DEBUG] Chain task  SubAgent: {agent_name}")
            elif not agent_name:
                if parent_run_id_str:
                    if parent_run_id_str in self.tool_run_map:
                        tool_identifier = self.tool_run_map[parent_run_id_str]
                        inferred_agent = infer_agent_from_tool(tool_identifier, self.tool_to_subagent_map)
                        if inferred_agent:
                            agent_name = inferred_agent
                            if self.verbose:
                                print(f"[DEBUG] Chain {tool_identifier}  SubAgent: {agent_name}")
        if not agent_name and self.run_stack:
            agent_name = self.run_stack[-1].get('agent_name')
        if chain_name == 'unknown' and not agent_name and self.verbose:
            parent_run_id_str = get_parent_run_id_str(parent_run_id)
            print(f"[DEBUG] ChainAgent: run_id={run_id[:8]}, parent_run_id={parent_run_id_str[:8] if parent_run_id_str else None}")
        if agent_name or chain_name != 'unknown':
            self.run_stack.append({
                'run_id': run_id, 
                'agent_name': agent_name,
                'chain_name': chain_name,
                'type': 'chain_start'
            })
        self._log(
            20,
            f"🔗 Chain | : {chain_name}" + (f" | Agent: {agent_name}" if agent_name else ""),
            "chain_start",
            run_id=run_id,
            chain_name=chain_name,
            agent_name=agent_name
        )
        add_event(
            self.event_queue,
            'chain_start',
            run_id,
            parent_run_id,
            {
                'chain_name': chain_name,
                'agent_name': agent_name,
                'inputs_preview': str(inputs)[:200] if inputs else None
            }
        )
        if self.verbose:
            print(f"\n{'='*60}")
            print(f"🔗 Chain: {chain_name}")
            print(f"  Run ID: {run_id[:8] if run_id else 'N/A'}")
            print(f"{'='*60}\n")
    def on_chain_end(
        self,
        outputs: Optional[Dict[str, Any]],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        run_id = get_run_id(run_id)
        duration = time.time() - self.start_times.get(run_id, time.time())
        agent_name = None
        for run_info in self.run_stack:
            if run_info.get('run_id') == run_id:
                agent_name = run_info.get('agent_name')
                break
        self._log(
            20,
            f"[Chain] : {format_duration(duration)}" + (f" | Agent: {agent_name}" if agent_name else ""),
            "chain_end",
            run_id=run_id,
            duration=duration,
            agent_name=agent_name
        )
        add_event(
            self.event_queue,
            'chain_end',
            run_id,
            parent_run_id,
            {
                'duration': duration,
                'agent_name': agent_name,
                'outputs_preview': str(outputs)[:200] if outputs else None
            }
        )
        try:
            if outputs:
                self.last_result = outputs
                msgs = None
                if isinstance(outputs, dict):
                    if 'messages' in outputs:
                        msgs = outputs.get('messages')
                    elif 'output' in outputs and isinstance(outputs['output'], dict) and 'messages' in outputs['output']:
                        msgs = outputs['output']['messages']
                    elif 'values' in outputs and isinstance(outputs['values'], dict) and 'messages' in outputs['values']:
                        msgs = outputs['values']['messages']
                if msgs:
                    try:
                        self.final_messages = msgs
                    except Exception:
                        pass
        except Exception:
            pass
        if self.verbose:
            print(f"\n{'='*60}")
            print("[Chain]")
            print(f"  : {format_duration(duration)}")
            print(f"{'='*60}\n")
    def on_chain_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        duration = self._handle_error(
            error=error,
            run_id=run_id,
            event_type="chain_error",
            log_message_prefix="[Chain]",
            parent_run_id=parent_run_id
        )
        self._print_verbose_error(
            "[Chain]",
            error,
            duration
        )