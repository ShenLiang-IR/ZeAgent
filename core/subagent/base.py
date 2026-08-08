from abc import ABC
from typing import Dict, Any, Union
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
class BaseSubAgent(ABC):
    def __init__(self, name: str, description: str, config: Dict[str, Any]):
        self.name = name
        self.description = description
        self.config = config
        self.system_prompt = config.get('system_prompt', '')
        self.tools = config.get('tools', [])
        self.external_tools = config.get('external_tools', [])
        self.model_config = config.get('model')
    def get_model(self, default_model: Union[ChatOpenAI, ChatOllama]) -> Union[ChatOpenAI, ChatOllama]:
        if self.model_config:
            from ..utils.config_loader import get_config
            from ..utils.llm_factory import is_ollama_provider, create_llm_model
            base_url = get_config('llm.default.base_url')
            api_key = get_config('llm.default.api_key')
            provider = get_config('llm.default.provider')
            is_ollama = is_ollama_provider(provider)
            if isinstance(self.model_config, str):
                if ':' in self.model_config and not is_ollama:
                    _, model_name = self.model_config.split(':', 1)
                else:
                    model_name = self.model_config
            else:
                model_name = self.model_config.get('model', 'qwen-turbo')
            temperature = self.model_config.get('temperature', 0.7) if isinstance(self.model_config, dict) else 0.7
            max_tokens = self.model_config.get('max_tokens') if isinstance(self.model_config, dict) else get_config('llm.default.max_tokens')
            enable_thinking = get_config('llm.default.enable_thinking')
            return create_llm_model(
                base_url=base_url,
                model_name=model_name,
                api_key=api_key,
                temperature=temperature,
                max_tokens=max_tokens,
                provider=provider,
                enable_thinking=enable_thinking
            )
        return default_model
    def to_agent_config(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "external_tools": self.external_tools,
            "model": self.model_config
        }