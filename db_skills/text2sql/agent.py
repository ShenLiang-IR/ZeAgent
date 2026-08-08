"""Deep Agent — wraps LangChain's Deep Agents harness for agentic tool-calling loops.

适配项目：用 ollama/openai provider（从 config 读 LLM 配置），不依赖 anthropic。
deepagents 已安装在 conda p311 环境。
"""

from __future__ import annotations

from deepagents import create_deep_agent as _deepagents_create
from langchain_core.messages import HumanMessage


def _get_chat_model(model_str: str = None):
    """获取 LangChain chat model。

    优先用项目 config 的 LLM 配置（ollama/openai），不依赖 anthropic。
    model_str 为 None 或以 'ollama:'/'openai:' 开头时用项目 config。
    """
    from utils.config import get_config
    from utils.llm.llm_factory import create_llm_model

    base_url = get_config("llm.default.base_url")
    model_name = get_config("llm.default.model")
    api_key = get_config("llm.default.api_key", "")
    provider = get_config("llm.default.provider", "openai")

    # 如果传了 model_str，解析覆盖
    if model_str and ":" in model_str:
        p, m = model_str.split(":", 1)
        if p.lower() == "ollama":
            provider = "ollama"
        elif p.lower() == "openai":
            provider = "openai"
        model_name = m
    elif model_str:
        model_name = model_str

    return create_llm_model(
        base_url=base_url,
        model_name=model_name,
        api_key=api_key,
        provider=provider,
        max_tokens=4096,
    )


class DeepAgent:
    """LangChain Deep Agents harness with text2sql tools and system prompt."""

    def __init__(
        self,
        model_str: str,
        tools: list,
        system_prompt: str,
    ):
        self.llm = _get_chat_model(model_str)
        self.system_prompt = system_prompt

        self.agent = _deepagents_create(
            model=self.llm,
            tools=tools,
            system_prompt=system_prompt,
            subagents=[],
        )

    def invoke(self, input_dict: dict) -> dict:
        """Run the agent. Input: {"messages": [{"role": "user", "content": "..."}]}"""
        messages = []
        for msg in input_dict.get("messages", []):
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))

        result = self.agent.invoke(
            {"messages": messages},
            config={"recursion_limit": 50},
        )

        return {"messages": result["messages"]}


def create_deep_agent(
    model: str,
    tools: list,
    system_prompt: str,
    token_limit: int = 75_000,  # kept for backward compatibility
) -> DeepAgent:
    """Create a Deep Agent with tools and a system prompt."""
    return DeepAgent(
        model_str=model,
        tools=tools,
        system_prompt=system_prompt,
    )
