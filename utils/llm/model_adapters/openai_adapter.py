from typing import List, Tuple
from langchain_core.messages import AIMessage
from .base import BaseModelAdapter, ModelCapabilities
class OpenAICompatibleAdapter(BaseModelAdapter):
    @property
    def name(self) -> str:
        return "openai"
    @property
    def model_patterns(self) -> List[str]:
        return ["gpt-*", "o1-*", "o3-*", "*"]
    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            supports_reasoning=False,
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