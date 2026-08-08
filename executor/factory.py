from loguru import logger
from enum import Enum
from typing import Dict, Type, Optional, Any
from .base_executor import BaseExecutor
class ExecutionMode(str, Enum):
    REACT = "react"
    DEEP_AGENT = "deep_thinking"
    PLANNING = "planning"
    TREE_OF_THOUGHT = "tree_of_thought"
class ExecutorFactory:
    @classmethod
    def _get_registry(cls) -> Dict[ExecutionMode, Type[BaseExecutor]]:
        from .react_executor import ReActExecutor
        from .deep_agent_executor import DeepAgentExecutor
        from .plan_executor import PlanExecutor
        from .tree_of_thought_executor import TreeOfThoughtExecutor
        return {
            ExecutionMode.DEEP_AGENT: DeepAgentExecutor,
            ExecutionMode.PLANNING: PlanExecutor,
            ExecutionMode.REACT: ReActExecutor,
            ExecutionMode.TREE_OF_THOUGHT: TreeOfThoughtExecutor,
        }
    @classmethod
    def create_executor(
        cls,
        execution_mode: ExecutionMode,
        session_id: str = "default",
        llm_model: Optional[Any] = None,
        workspace_id: Optional[int] = None,
    ) -> BaseExecutor:
        registry = cls._get_registry()
        executor_class = registry.get(execution_mode)
        if executor_class is None:
            available_modes = list(registry.keys())
            raise ValueError(
                f"不支持的执行模式 '{execution_mode.value}'，"
                f"可用模式: {', '.join([m.value for m in available_modes])}"
            )
        logger.debug(f"执行模式: {execution_mode.value} -> {executor_class.__name__}")
        return executor_class(
            session_id=session_id,
            llm_model=llm_model,
            workspace_id=workspace_id,
        )
    @classmethod
    def get_supported_modes(cls) -> list:
        return list(cls._get_registry().keys())