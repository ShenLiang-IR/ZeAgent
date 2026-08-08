from loguru import logger
from typing import Any
from langchain_core.messages import AIMessage
from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
)
from langgraph.runtime import Runtime
from utils.message import extract_reasoning_from_content
class CleanThinkMiddleware(AgentMiddleware):
    def __init__(self, subagent_name: str = "default", system_prompt: str = ""):
        self.subagent_name = subagent_name
        self.system_prompt = system_prompt
    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        updated = []
        for msg in state.get('messages', []):
            if isinstance(msg, AIMessage):
                _, cleaned = extract_reasoning_from_content(msg.content)
                if cleaned != msg.content:
                    updated.append(msg.model_copy(update={"content": cleaned}))
        if updated:
            logger.debug(f"[CleanThink]  {len(updated)}  AIMessage ")
            return {"messages": updated}
        return None