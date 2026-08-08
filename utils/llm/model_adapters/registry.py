import fnmatch
from typing import Dict, Optional, Type
from .base import BaseModelAdapter
from .deepseek_adapter import DeepSeekAdapter
from .qwen_adapter import QwenAdapter
from .openai_adapter import OpenAICompatibleAdapter
_adapter_registry: Dict[str, Type[BaseModelAdapter]] = {}
_adapter_instances: Dict[str, BaseModelAdapter] = {}
def register_adapter(adapter_class: Type[BaseModelAdapter]) -> None:
    instance = adapter_class()
    _adapter_registry[instance.name] = adapter_class
    _adapter_instances[instance.name] = instance
def get_adapter(model_name: Optional[str] = None) -> BaseModelAdapter:
    if not model_name:
        return _adapter_instances.get("openai", OpenAICompatibleAdapter())
    model_name_lower = model_name.lower()
    for adapter in _adapter_instances.values():
        for pattern in adapter.model_patterns:
            if pattern == "*":
                continue
            if fnmatch.fnmatch(model_name_lower, pattern.lower()):
                return adapter
    return _adapter_instances.get("openai", OpenAICompatibleAdapter())
def get_all_adapters() -> Dict[str, BaseModelAdapter]:
    return _adapter_instances.copy()
register_adapter(DeepSeekAdapter)
register_adapter(QwenAdapter)
register_adapter(OpenAICompatibleAdapter)