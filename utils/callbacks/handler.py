from loguru import logger
from typing import Any, Dict, List, Optional
from langchain_core.callbacks import BaseCallbackHandler
from .helpers import get_events
from .agent_inference import (
    load_subagent_names,
    load_tool_to_subagent_map
)
from .llm_callbacks import LLMCallbacksMixin
from .tool_callbacks import ToolCallbacksMixin
from .chain_callbacks import ChainCallbacksMixin
from .agent_callbacks import AgentCallbacksMixin
from ..common.logging_utils import get_agent_logger
logger = get_agent_logger()
class AgentCallbackHandler(
    BaseCallbackHandler,
    LLMCallbacksMixin,
    ToolCallbacksMixin,
    ChainCallbacksMixin,
    AgentCallbacksMixin
):
    def __init__(self, session_id: Optional[str] = None, verbose: bool = True):
        super().__init__()
        self.session_id = session_id or "default"
        self.verbose = verbose
        self.run_stack: List[Dict[str, Any]] = []
        self.start_times: Dict[str, float] = {}
        self.event_queue: List[Dict[str, Any]] = []
        self.tool_run_map: Dict[str, str] = {}
        self.llm_run_map: Dict[str, str] = {}
        self.llm_model_map: Dict[str, str] = {}
        self.subagent_names = load_subagent_names()
        self.tool_to_subagent_map = load_tool_to_subagent_map()
        self.final_messages: List[Any] = []
        self.last_result: Dict[str, Any] = {}
    def _log(self, level: int, message: str, event_type: str, **kwargs):
        exc_info = kwargs.pop('exc_info', False)
        extra = {
            'event_type': event_type,
            'session_id': self.session_id,
            **kwargs
        }
        logger.log(level, message, extra=extra, exc_info=exc_info)
    def get_events(self) -> List[Dict[str, Any]]:
        return get_events(self.event_queue)
    def get_final_messages(self) -> List[Any]:
        if self.final_messages:
            return self.final_messages
        if isinstance(self.last_result, dict):
            outputs = self.last_result
            msgs = None
            if 'messages' in outputs:
                msgs = outputs.get('messages')
            elif 'output' in outputs and isinstance(outputs['output'], dict) and 'messages' in outputs['output']:
                msgs = outputs['output']['messages']
            elif 'values' in outputs and isinstance(outputs['values'], dict) and 'messages' in outputs['values']:
                msgs = outputs['values']['messages']
            if msgs:
                return msgs
        return []