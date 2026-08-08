from typing import Any, Dict, List, Optional
from loguru import logger
from langchain.agents.middleware import AgentMiddleware, AgentState
from langgraph.runtime import Runtime
from langchain_core.messages import AIMessage, ToolMessage
class ContextEdit:
    def __init__(
        self,
        trigger: int = 50000,
        keep: int = 3,
        placeholder: str = "[]"
    ):
        self.trigger = trigger
        self.keep = keep
        self.placeholder = placeholder
class ClearToolUsesEdit(ContextEdit):
    def __init__(
        self,
        trigger: int = 50000,
        keep: int = 3,
        placeholder: str = "[]"
    ):
        super().__init__(trigger, keep, placeholder)
    def should_apply(self, estimated_tokens: int) -> bool:
        return estimated_tokens >= self.trigger
    def apply(self, messages: List[Any]) -> List[Any]:
        if len(messages) <= self.keep:
            return messages
        tool_message_indices = []
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage):
                tool_message_indices.append(i)
        if len(tool_message_indices) <= self.keep:
            return messages
        indices_to_clear = tool_message_indices[:-self.keep]
        if not indices_to_clear:
            return messages
        result = []
        cleared_count = 0
        for i, msg in enumerate(messages):
            if i in indices_to_clear:
                tool_name = getattr(msg, 'name', None) or getattr(msg, 'tool_name', 'unknown')
                simplified = AIMessage(
                    content=self.placeholder,
                    response_metadata={'cleared_tool': tool_name}
                )
                result.append(simplified)
                cleared_count += 1
            else:
                result.append(msg)
        logger.info(
            f"[ClearToolUsesEdit] 已清理 {cleared_count} 条工具调用结果, 保留最近 {self.keep} 条"
        )
        return result
class ContextEditingMiddleware(AgentMiddleware):
    def __init__(
        self,
        edits: Optional[List[ContextEdit]] = None,
        default_trigger: int = 50000,
        default_keep: int = 3
    ):
        self.edits = edits or [
            ClearToolUsesEdit(trigger=default_trigger, keep=default_keep)
        ]
        self._last_edit_count = 0
        logger.info(
            f"[ContextEditingMiddleware] : "
            f"={len(self.edits)}, default_trigger={default_trigger}, default_keep={default_keep}"
        )
    def _estimate_tokens(self, messages: List[Any]) -> int:
        total_chars = 0
        for msg in messages:
            content = getattr(msg, 'content', '')
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and 'text' in item:
                        total_chars += len(item['text'])
                    elif isinstance(item, str):
                        total_chars += len(item)
        return max(total_chars // 3, total_chars // 4)
    def before_model(self, state: AgentState, runtime: Runtime) -> Dict[str, Any] | None:
        messages = state.get('messages', [])
        if not messages:
            return None
        estimated_tokens = self._estimate_tokens(messages)
        logger.debug(
            f"[ContextEditingMiddleware] before_model - "
            f": {len(messages)},  tokens: {estimated_tokens}"
        )
        modified_messages = messages
        for edit in self.edits:
            if isinstance(edit, ClearToolUsesEdit) and edit.should_apply(estimated_tokens):
                modified_messages = edit.apply(modified_messages)
        if modified_messages != messages:
            self._last_edit_count += 1
            logger.info(
                f"[ContextEditingMiddleware]  "
                f"( {self._last_edit_count} ), "
                f" tokens: {self._estimate_tokens(modified_messages)}"
            )
            return {"messages": modified_messages}
        return None
    def after_model(self, state: AgentState, runtime: Runtime) -> Dict[str, Any] | None:
        return None
def create_context_editing_middleware(
    trigger: int = 50000,
    keep: int = 3,
    placeholder: str = "[]"
) -> ContextEditingMiddleware:
    edits = [
        ClearToolUsesEdit(trigger=trigger, keep=keep, placeholder=placeholder)
    ]
    return ContextEditingMiddleware(edits=edits)