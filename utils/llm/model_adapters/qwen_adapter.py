from typing import List, Tuple, Any
from langchain_core.messages import AIMessage
from .base import BaseModelAdapter, ModelCapabilities
class QwenAdapter(BaseModelAdapter):
    @property
    def name(self) -> str:
        return "qwen"
    @property
    def model_patterns(self) -> List[str]:
        return ["qwen*", "Qwen*", "qwen-plus*", "qwen-turbo*", "qwen3*", "Qwen3*"]
    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            supports_reasoning=True,
            reasoning_in_content=False,
            supports_tool_calls=True,
            supports_streaming=True
        )
    def extract_reasoning(self, message: AIMessage) -> Tuple[str, str]:
        content = self._extract_from_dict_or_object(
            message, 'content', 'text', 'message', default=""
        )
        if not content:
            return "", ""
        content_str = str(content)
        reasoning = self._extract_from_dict_or_object(
            message, 'reasoning_content', 'thinking', 'reasoning', 'think', default=None
        )
        if reasoning:
            return str(reasoning), content_str
        if hasattr(message, 'response_metadata') and message.response_metadata:
            metadata = message.response_metadata
            reasoning = self._extract_from_dict_or_object(
                metadata, 'reasoning_content', 'thinking', 'reasoning', 'think', default=None
            )
            if reasoning:
                return str(reasoning), content_str
        if hasattr(message, 'additional_kwargs') and message.additional_kwargs:
            kwargs = message.additional_kwargs
            reasoning = self._extract_from_dict_or_object(
                kwargs, 'reasoning_content', 'thinking', 'reasoning', 'think', 'reasoning_text', default=None
            )
            if reasoning:
                return str(reasoning), content_str
        reasoning, cleaned = self.extract_and_clean_think_tags(content_str)
        if reasoning:
            return reasoning, cleaned
        return "", content_str
    def extract_chunk_content(self, chunk: Any) -> Tuple[str, str]:
        content, reasoning = super().extract_chunk_content(chunk)
        if not reasoning and hasattr(chunk, 'additional_kwargs') and chunk.additional_kwargs:
            reasoning = self._extract_from_dict_or_object(
                chunk.additional_kwargs, 'reasoning_content', 'thinking', 'reasoning', 'think', default=""
            )
        return content, reasoning