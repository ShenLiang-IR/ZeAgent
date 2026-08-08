import json
import ast
import time
from loguru import logger
from typing import Any, Dict, Optional, Union
from .base_callbacks import BaseCallbacksMixin
from .helpers import (
    get_run_id,
    format_duration,
    add_event,
    extract_tool_name_unified
)
from ..common.sanitize import sanitize_input
from ..common.logging_utils import (
    get_agent_logger,
    should_log_tool_io_details,
    format_log_payload
)
logger = get_agent_logger()
class ToolCallbacksMixin(BaseCallbacksMixin):
    def on_tool_start(
        self,
        serialized: Optional[Dict[str, Any]],
        input_str: Optional[str],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        logger.info("=== [] on_tool_start  ===")
        run_id = get_run_id(run_id)
        self.start_times[run_id] = time.time()
        tool_name = extract_tool_name_unified(serialized, kwargs)
        input_data = {}
        if input_str:
            try:
                input_data = json.loads(input_str)
            except (json.JSONDecodeError, TypeError):
                try:
                    input_data = ast.literal_eval(input_str)
                except (ValueError, SyntaxError):
                    if isinstance(input_str, str) and input_str.strip().startswith('{'):
                        try:
                            input_data = ast.literal_eval(input_str)
                        except (ValueError, SyntaxError):
                            input_data = {"raw_input": input_str[:200]}
                    else:
                        input_data = {"raw_input": input_str[:200]}
        if tool_name == 'task' and isinstance(input_data, dict):
            subagent_type = input_data.get('subagent_type')
            if subagent_type:
                self.tool_run_map[run_id] = f"task:{subagent_type}"
                if self.verbose:
                    print(f"[DEBUG]  task subagent_type: {subagent_type}")
            else:
                raw_input = input_data.get('raw_input', '')
                if isinstance(raw_input, str) and 'subagent_type' in raw_input:
                    try:
                        parsed = ast.literal_eval(raw_input)
                        if isinstance(parsed, dict) and 'subagent_type' in parsed:
                            subagent_type = parsed.get('subagent_type')
                            self.tool_run_map[run_id] = f"task:{subagent_type}"
                            if self.verbose:
                                print(f"[DEBUG]  raw_input  subagent_type: {subagent_type}")
                        else:
                            self.tool_run_map[run_id] = tool_name
                    except (ValueError, SyntaxError):
                        self.tool_run_map[run_id] = tool_name
                else:
                    self.tool_run_map[run_id] = tool_name
        elif tool_name != 'unknown':
            self.tool_run_map[run_id] = tool_name
        safe_input = sanitize_input(input_data)
        input_preview = json.dumps(safe_input, ensure_ascii=False)[:200]
        self._log(
            20,
            f"🔧  | : {tool_name} | Run ID: {run_id[:8]}",
            "tool_start",
            run_id=run_id,
            tool_name=tool_name,
            input_data=safe_input
        )
        add_event(
            self.event_queue,
            'tool_start',
            run_id,
            parent_run_id,
            {
                'tool_name': tool_name,
                'input_data': safe_input,
                'input_full': input_str if input_str else None
            }
        )
        should_log = should_log_tool_io_details()
        if should_log:
            logger.info(f"🔧 [] : {tool_name} | : {format_log_payload(input_data)}")
        else:
            logger.debug(f"[] on_tool_start: should_log_tool_io_details() = False")
        if self.verbose:
            print(f"\n{'='*60}")
            print("🔧 ")
            print(f"  : {tool_name}")
            print(f"  Run ID: {run_id[:8]}")
            print(f"  : {input_preview}")
            print(f"{'='*60}\n")
    def on_tool_end(
        self,
        output: Union[str, Any],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        logger.info("=== [] on_tool_end  ===")
        run_id = get_run_id(run_id)
        duration = time.time() - self.start_times.get(run_id, time.time())
        tool_name = kwargs.get('name', 'unknown')
        if not tool_name or tool_name == 'unknown':
            for run_info in reversed(self.run_stack):
                if run_info.get('type') == 'tool_start':
                    tool_name = run_info.get('tool_name', 'unknown')
                    break
        if isinstance(output, str):
            output_str = output
        else:
            if hasattr(output, 'content'):
                output_str = str(output.content)
            elif hasattr(output, 'text'):
                output_str = str(output.text)
            else:
                output_str = str(output)
        if isinstance(output_str, dict):
            output_str = json.dumps(output_str, ensure_ascii=False, indent=2)
        output_preview = output_str[:200] + "..." if len(output_str) > 200 else output_str
        self._log(
            20,
            f"[] : {tool_name} | : {format_duration(duration)}",
            "tool_end",
            run_id=run_id,
            tool_name=tool_name,
            duration=duration,
            output_preview=output_preview,
            output_length=len(output_str)
        )
        add_event(
            self.event_queue,
            'tool_end',
            run_id,
            parent_run_id,
            {
                'tool_name': tool_name,
                'duration': duration,
                'output_preview': output_preview,
                'output_length': len(output_str),
                'output_full': output_str if len(output_str) < 5000 else None
            }
        )
        should_log = should_log_tool_io_details()
        if should_log:
            logger.info(f"[] : {tool_name} | : {format_log_payload(output_str)}")
        else:
            logger.debug(f"[] on_tool_end: should_log_tool_io_details() = False")
        if self.verbose:
            print(f"\n{'='*60}")
            print("[]")
            print(f"  : {tool_name}")
            print(f"  : {format_duration(duration)}")
            print(f"  : {output_preview}")
            print(f"{'='*60}\n")
    def on_tool_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        tool_name = kwargs.get('name', 'unknown')
        duration = self._handle_error(
            error=error,
            run_id=run_id,
            event_type="tool_error",
            log_message_prefix=f"[] : {tool_name}",
            event_data={'tool_name': tool_name},
            parent_run_id=parent_run_id,
            tool_name=tool_name
        )
        self._print_verbose_error(
            "[]",
            error,
            duration,
            tool_name=tool_name
        )