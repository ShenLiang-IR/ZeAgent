from loguru import logger
from abc import ABC, abstractmethod
from typing import Optional, Any, List, AsyncGenerator
from langchain_core.messages import BaseMessage, AIMessage
class BaseExecutor(ABC):
    def __init__(
        self,
        session_id: str = "default",
        llm_model: Optional[Any] = None
    ):
        self.session_id = session_id
        self.llm_model = llm_model
    @abstractmethod
    async def execute(
        self, 
        messages: List[BaseMessage],
        **kwargs
    ) -> List[BaseMessage]:
        pass
    @abstractmethod
    async def execute_stream(
        self,
        messages: List[BaseMessage],
        event_sender: Optional[Any] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        pass
    def _extract_user_input(self, messages: List[BaseMessage]) -> str:
        from api.chat.message_utils import extract_user_input_from_messages
        return extract_user_input_from_messages(messages)
    async def _build_graph_config(self, recursion_limit: int) -> dict:
        """构建 langgraph 调用 config（thread_id + recursion_limit + langfuse callbacks）。

        P2-4: 抽出 ReAct/DeepAgent execute() 的公共 config 组装逻辑。
        """
        config = {
            "configurable": {"thread_id": self.session_id or "default"},
            "recursion_limit": recursion_limit,
        }
        try:
            from utils.observability.langfuse_handler import attach_callbacks
            config = attach_callbacks(config, session_id=self.session_id)
        except Exception as e:
            logger.warning(f"[BaseExecutor] langfuse attach 跳过: {e}")
        return config
    async def _invoke_graph_non_stream(
        self,
        graph,
        messages: List[BaseMessage],
        recursion_limit: int,
        executor_name: str,
    ) -> List[BaseMessage]:
        """非流式调用 langgraph 并包装为 AIMessage（含错误分支）。

        P2-4: 抽出 ReActExecutor/DeepAgentExecutor execute() 的 ~90% 重复逻辑。
        """
        import time
        from utils.message.extract import extract_final_output
        start_time = time.time()
        try:
            config = await self._build_graph_config(recursion_limit)
            result = await graph.ainvoke({"messages": messages}, config=config)
            output = extract_final_output(result)
            duration = time.time() - start_time
            logger.info(f"[{executor_name}] 执行完成 | 耗时: {duration:.2f}s")
            return [AIMessage(
                content=output,
                response_metadata={
                    'executor': executor_name,
                    'duration': duration,
                }
            )]
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[{executor_name}] 执行失败: {e}", exc_info=True)
            return [AIMessage(
                content=f"执行失败: {e}",
                response_metadata={'error': str(e), 'duration': duration, 'executor': executor_name}
            )]
    async def close(self):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        await self.close()