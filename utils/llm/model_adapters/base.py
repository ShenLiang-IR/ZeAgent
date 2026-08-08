from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple, List
from langchain_core.messages import AIMessage
@dataclass
class ModelCapabilities:
    supports_tool_calls: bool = True
    supports_streaming: bool = True
    supports_reasoning: bool = False
    reasoning_in_content: bool = False
    reasoning_tag_format: Optional[str] = None
    tool_calls_location: str = "tool_calls"
class BaseModelAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    @property
    @abstractmethod
    def model_patterns(self) -> List[str]:
        pass
    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities()
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
        return "", content_str
    def extract_tool_calls(self, message: AIMessage) -> List[Dict[str, Any]]:
        tool_calls = self._extract_from_dict_or_object(
            message, 'tool_calls', 'tools', 'function_calls', default=None
        )
        if tool_calls and isinstance(tool_calls, list) and len(tool_calls) > 0:
            return self._normalize_tool_calls(tool_calls)
        if hasattr(message, 'response_metadata') and message.response_metadata:
            metadata = message.response_metadata
            tool_calls = self._extract_from_dict_or_object(
                metadata, 'tool_calls', 'tools', 'function_calls', default=None
            )
            if tool_calls and isinstance(tool_calls, list) and len(tool_calls) > 0:
                return self._normalize_tool_calls(tool_calls)
        if hasattr(message, 'additional_kwargs') and message.additional_kwargs:
            kwargs = message.additional_kwargs
            tool_calls = self._extract_from_dict_or_object(
                kwargs, 'tool_calls', 'tools', 'function_calls', default=None
            )
            if tool_calls and isinstance(tool_calls, list) and len(tool_calls) > 0:
                return self._normalize_tool_calls(tool_calls)
        return []
    @staticmethod
    def _normalize_tool_calls(tool_calls: Any) -> List[Dict[str, Any]]:
        if not tool_calls:
            return []
        if not isinstance(tool_calls, list):
            tool_calls = [tool_calls]
        normalized = []
        for call in tool_calls:
            if not call:
                continue
            if not isinstance(call, dict):
                try:
                    call = vars(call)
                except TypeError:
                    continue
            normalized_call = {}
            call_id = call.get('id') or call.get('tool_id') or call.get('call_id')
            if call_id:
                normalized_call['id'] = str(call_id)
            name = call.get('name') or call.get('tool_name') or call.get('function_name')
            if name:
                normalized_call['name'] = str(name)
            args = call.get('args') or call.get('input') or call.get('arguments') or call.get('parameters', {})
            if args:
                if isinstance(args, str):
                    import json
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                if isinstance(args, dict):
                    normalized_call['args'] = args
                else:
                    normalized_call['args'] = {}
            else:
                normalized_call['args'] = {}
            for key in ['type', 'tool_id', 'raw_output', 'output', 'error', 'duration']:
                if key in call and call[key]:
                    normalized_call[key] = call[key]
            if 'name' in normalized_call:
                normalized.append(normalized_call)
        return normalized
    def extract_token_usage(self, message: AIMessage) -> Dict[str, int]:
        usage = {}
        if hasattr(message, 'response_metadata') and message.response_metadata:
            metadata = message.response_metadata
            raw = metadata.get('token_usage') or metadata.get('usage_metadata', {})
            if isinstance(raw, dict):
                usage = {
                    'prompt_tokens': raw.get('input_tokens') or raw.get('prompt_tokens', 0),
                    'completion_tokens': raw.get('output_tokens') or raw.get('completion_tokens', 0),
                    'total_tokens': raw.get('total_tokens', 0)
                }
        if not usage:
            usage = {
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'total_tokens': 0
            }
        return usage
    def _safe_get_value(self, obj: Any, *keys: str, default: Any = None) -> Any:
        if not obj:
            return default
        if isinstance(obj, dict):
            for key in keys:
                if key in obj and obj[key]:
                    return obj[key]
            return default
        for key in keys:
            if hasattr(obj, key):
                value = getattr(obj, key, None)
                if value:
                    return value
        return default
    def _extract_from_dict_or_object(self, source: Any, *keys: str, default: Any = "") -> Any:
        value = self._safe_get_value(source, *keys, default=None)
        if value is None:
            return default
        return value
    @staticmethod
    def extract_and_clean_think_tags(content: str) -> tuple[str, str]:
        if not content or not isinstance(content, str):
            return "", content or ""
        import re
        cleaned_content = content
        patterns = [
            (r'`<think>`(.*?)`</think>`', '<think> with backticks'),
            (r'<think>(.*?)</think>', '<think> without backticks'),
        ]
        for pattern, description in patterns:
            cleaned_content = re.sub(pattern, '', cleaned_content, flags=re.DOTALL)
        cleaned_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', cleaned_content)
        cleaned_content = cleaned_content.strip()
        return "", cleaned_content
    def extract_chunk_content(self, chunk: Any) -> Tuple[str, str]:
        content = ""
        reasoning = ""
        content = self._extract_from_dict_or_object(
            chunk, 'content', 'text', 'message', 'delta', default=""
        )
        if not content and hasattr(chunk, 'choices'):
            try:
                choices = chunk.choices
                if choices and len(choices) > 0:
                    delta = choices[0].get('delta') if isinstance(choices[0], dict) else getattr(choices[0], 'delta', None)
                    if delta:
                        content = self._extract_from_dict_or_object(
                            delta, 'content', 'text', 'message', default=""
                        )
            except (IndexError, AttributeError, TypeError):
                pass
        if not content and isinstance(chunk, dict):
            content = chunk.get('content') or chunk.get('text') or chunk.get('message') or ""
        reasoning = self._extract_from_dict_or_object(
            chunk, 'reasoning_content', 'thinking', 'reasoning', 'think', default=""
        )
        if content:
            has_complete_tag = (
                ('<think>' in content and '</think>' in content) or
                ('`<think>`' in content and '`</think>`' in content)
            )
            if has_complete_tag:
                reasoning_from_tag, cleaned_content = self.extract_and_clean_think_tags(content)
                if reasoning_from_tag:
                    if reasoning:
                        reasoning = reasoning + "\n\n" + reasoning_from_tag
                    else:
                        reasoning = reasoning_from_tag
                    content = cleaned_content
        return str(content), str(reasoning)
    def normalize_response(self, message: AIMessage) -> Dict[str, Any]:
        reasoning, content = self.extract_reasoning(message)
        tool_calls = self.extract_tool_calls(message)
        token_usage = self.extract_token_usage(message)
        return {
            'content': content,
            'reasoning_content': reasoning,
            'tool_calls': tool_calls,
            'token_usage': token_usage,
            'raw_message': message
        }