from __future__ import annotations
from typing import Optional, Any, List, AsyncGenerator
from langchain_core.messages import BaseMessage, AIMessage
from loguru import logger
from core.builder import build_graph
from utils.config import get_config
from .base_executor import BaseExecutor
from .stream_helper import StreamResponseHelper
class ReActExecutor(BaseExecutor):
    async def execute(
        self,
        messages: List[BaseMessage],
        **kwargs
    ) -> List[BaseMessage]:
        user_input = self._extract_user_input(messages)
        if not user_input:
            # P2-9: 恢复有意义的错误消息（原中文文案被剥离为空串）
            raise ValueError("用户输入为空，无法执行 ReAct")
        logger.info(f"[ReActExecutor] 开始执行: {user_input[:100]}...")
        agent_name = kwargs.get('agent')
        response_mode = kwargs.get('response_mode')
        try:
            graph = await build_graph(
                session_id=self.session_id,
                subagent_name=agent_name,
                response_mode=response_mode
            )
            if graph is None:
                raise ValueError(f"build_graph 返回 None（agent={agent_name}）")
            recursion_limit = get_config('agent.recursion_limit', 25)
            # P2-4: 复用基类共享逻辑，消除与 DeepAgentExecutor 的重复
            result = await self._invoke_graph_non_stream(
                graph, messages, recursion_limit, "react"
            )
            # 补充 selected_subagent 元数据
            if result and isinstance(result[-1], AIMessage):
                meta = result[-1].response_metadata or {}
                if agent_name:
                    meta['selected_subagent'] = agent_name
                result[-1].response_metadata = meta
            return result
        except Exception as e:
            logger.error(f"[ReActExecutor] 执行失败: {e}", exc_info=True)
            return [AIMessage(
                content=f"ReAct 执行失败: {e}",
                response_metadata={'error': str(e), 'executor': 'react'}
            )]
    async def execute_stream(
        self,
        messages: List[BaseMessage],
        event_sender: Optional[Any] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        user_input = self._extract_user_input(messages)
        yield StreamResponseHelper.send_config()
        yield StreamResponseHelper.send_started()
        try:
            from utils.callbacks import AgentCallbackHandler
            from executor.agent_stream_handler import generate_simple_stream
            agent_name = kwargs.get('agent')
            response_mode = kwargs.get('response_mode')
            memory_context = kwargs.get('memory_context')
            # 把 memory_context（用户偏好+相关记忆）作为 SystemMessage 注入 LLM
            if memory_context:
                from langchain_core.messages import SystemMessage
                # 记忆仅作辅助；涉及之前对话内容时优先用历史原文，避免凭记忆编造
                mem_msg = SystemMessage(content=f"以下是用户的相关记忆和偏好，仅作辅助参考。若问题涉及之前的对话内容（如“之前写过什么”“上次说的”“他俩”），优先从下方对话历史原文中查找准确内容，不要凭记忆编造：\n{memory_context}")
                messages = [mem_msg] + list(messages)
            graph = await build_graph(
                session_id=self.session_id,
                subagent_name=agent_name,
                response_mode=response_mode
            )
            if not graph:
                error_msg = f"无法构建 ReAct Agent 图（agent={agent_name}）"
                logger.error(f"[ReActExecutor] {error_msg}")
                yield StreamResponseHelper.send_error(error_msg)
                return
            callback_handler = AgentCallbackHandler(session_id=self.session_id)
            logger.info(f"[ReActExecutor] 启动 Agent 流式（消息数: {len(messages)})...")
            async for data in generate_simple_stream(
                graph=graph,
                langchain_messages=messages,
                callback_handler=callback_handler,
                session_id=self.session_id
            ):
                yield data
            logger.info("[ReActExecutor] 流式完成")
        except Exception as e:
            logger.error(f"[ReActExecutor] 流式失败: {e}", exc_info=True)
            yield StreamResponseHelper.send_error(f'执行失败: {e}')