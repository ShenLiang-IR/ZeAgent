from loguru import logger
from typing import Any, Optional
from .base_callbacks import BaseCallbacksMixin
from .helpers import (
    get_run_id,
    add_event
)
from ..common.logging_utils import get_agent_logger
logger = get_agent_logger()
class AgentCallbacksMixin(BaseCallbacksMixin):
    def on_agent_action(
        self,
        action: Any,
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        run_id = get_run_id(run_id)
        tool_name = getattr(action, 'tool', 'unknown')
        tool_input = getattr(action, 'tool_input', {})
        self._log(
            20,
            f"🤖 Agent | : {tool_name}",
            "agent_action",
            run_id=run_id,
            tool_name=tool_name,
            tool_input=tool_input
        )
        add_event(
            self.event_queue,
            'agent_action',
            run_id,
            parent_run_id,
            {
                'tool_name': tool_name,
                'tool_input': tool_input,
                'tool_input_preview': str(tool_input)[:200] if tool_input else None
            }
        )
        if self.verbose:
            print(f"\n{'='*60}")
            print("🤖 Agent")
            print(f"  : {tool_name}")
            print(f"  : {tool_input}")
            print(f"{'='*60}\n")
    def on_agent_finish(
        self,
        finish: Any,
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        run_id = get_run_id(run_id)
        return_value = getattr(finish, 'return_values', {})
        self._log(
            20,
            f"🎉 Agent | Run ID: {run_id[:8]}",
            "agent_finish",
            run_id=run_id,
            return_value=return_value
        )
        add_event(
            self.event_queue,
            'agent_finish',
            run_id,
            parent_run_id,
            {
                'return_value': return_value,
                'return_value_preview': str(return_value)[:200] if return_value else None
            }
        )
        if self.verbose:
            print(f"\n{'='*60}")
            print("🎉 Agent")
            print(f"  Run ID: {run_id[:8] if run_id else 'N/A'}")
            if return_value:
                print(f"  : {return_value}")
            print(f"{'='*60}\n")