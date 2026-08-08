from __future__ import annotations
from typing import Any, Optional, Protocol, Sequence, runtime_checkable
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from loguru import logger


@runtime_checkable
class AgentFactory(Protocol):
    """Agent 工厂协议，定义 create() 接口。"""

    def create(
        self,
        model: BaseChatModel,
        tools: Sequence[BaseTool],
        system_prompt: str,
        middleware: Optional[list] = None,
        checkpointer: Optional[Any] = None,
        **kwargs,
    ) -> CompiledStateGraph: ...


def _build_skill_prompt_section(skill_prompt_generator) -> str:
    """构建 skill 提示词段落，追加到 system_prompt 末尾。"""
    if not skill_prompt_generator:
        return ""
    return skill_prompt_generator.generate_full_section()


def _build_agent_kwargs(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    system_prompt: str,
    middleware: Optional[list],
    checkpointer: Optional[Any],
    kwargs: dict,
) -> dict:
    """构建 create_agent / create_deep_agent 的公共 kwargs 字典。

    LangGraphAgentFactory 和 DeepAgentFactory 共用此函数，消除两者
    create() 中约 90% 的重复逻辑：
    - 基础字段填充（model / tools / system_prompt）
    - 条件字段填充（middleware / checkpointer）
    - skill 提示词合并到 system_prompt
    - 清理无用的 kwargs 键（skill_backend / agent_id）
    """
    create_kwargs: dict = {
        'model': model,
        'tools': tools,
        'system_prompt': system_prompt,
    }
    if middleware:
        create_kwargs['middleware'] = middleware
    if checkpointer:
        create_kwargs['checkpointer'] = checkpointer
    skill_prompt_generator = kwargs.pop("skill_prompt_generator", None)
    skill_section = _build_skill_prompt_section(skill_prompt_generator)
    if skill_section:
        create_kwargs['system_prompt'] = system_prompt + "\n\n" + skill_section
    kwargs.pop("skill_backend", None)
    kwargs.pop("agent_id", None)
    create_kwargs.update(kwargs)
    return create_kwargs


class LangGraphAgentFactory:
    """使用 langchain.agents.create_agent 构建 Agent。"""

    def create(
        self,
        model: BaseChatModel,
        tools: Sequence[BaseTool],
        system_prompt: str,
        middleware: Optional[list] = None,
        checkpointer: Optional[Any] = None,
        **kwargs,
    ) -> CompiledStateGraph:
        from langchain.agents import create_agent
        create_kwargs = _build_agent_kwargs(
            model, tools, system_prompt, middleware, checkpointer, kwargs
        )
        compiled_graph = create_agent(**create_kwargs)
        mw_names = [type(m).__name__ for m in (create_kwargs.get('middleware') or [])]
        has_skill = create_kwargs.get('system_prompt', '') != system_prompt
        logger.debug(
            f"[LangGraphAgentFactory]  | "
            f"tools={len(tools)}, middleware={mw_names}, "
            f"has_skill_prompt={has_skill}"
        )
        return compiled_graph


class DeepAgentFactory:
    """使用 deepagents.create_deep_agent 构建 DeepAgent。"""

    def create(
        self,
        model: BaseChatModel,
        tools: Sequence[BaseTool],
        system_prompt: str,
        middleware: Optional[list] = None,
        checkpointer: Optional[Any] = None,
        **kwargs,
    ) -> CompiledStateGraph:
        from deepagents import create_deep_agent
        from utils.llm.llm_utils import _DynamicHeadersModelProxy
        # DeepAgent 需要解包动态请求头代理，获取底层真实模型
        actual_model = model._model if isinstance(model, _DynamicHeadersModelProxy) else model
        build_kwargs = _build_agent_kwargs(
            actual_model, tools, system_prompt, middleware, checkpointer, kwargs
        )
        final_prompt = build_kwargs.get('system_prompt', '')
        logger.debug(
            f"[DeepAgentFactory]  create_deep_agent | "
            f"tools={[getattr(t, 'name', str(t)) for t in tools]}, "
            f"middleware={[type(m).__name__ for m in (middleware or [])]}, "
            f"prompt_len={len(final_prompt)}"
        )
        compiled_graph = create_deep_agent(**build_kwargs)
        middleware_names = [type(m).__name__ for m in (middleware or [])]
        logger.info(
            f"[DeepAgentFactory]  | "
            f"tools={len(tools)}, middleware={middleware_names}, "
            f"checkpointer={'enabled' if checkpointer else 'disabled'}"
        )
        return compiled_graph
