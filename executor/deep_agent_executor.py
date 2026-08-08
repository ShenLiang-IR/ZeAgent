from __future__ import annotations
import time
import asyncio
import datetime as _dt
from typing import Optional, Any, List, AsyncGenerator
from loguru import logger
from langchain_core.messages import BaseMessage, AIMessage
from .base_executor import BaseExecutor
from .stream_helper import StreamResponseHelper
from utils.sse import send_sse_data
from core.builder import build_graph
from utils.config import get_config
from utils.common.constants import get_heartbeat_interval
from utils.message.extract import extract_final_output
class DeepAgentExecutor(BaseExecutor):
    def __init__(
        self,
        session_id: str = "default",
        llm_model: Optional[Any] = None
    ):
        super().__init__(session_id, llm_model)
    async def execute(
        self,
        messages: List[BaseMessage],
        **kwargs
    ) -> List[BaseMessage]:
        user_input = self._extract_user_input(messages)
        if not user_input:
            # P2-9: 恢复有意义的错误消息
            raise ValueError("用户输入为空，无法执行 DeepAgent")
        logger.info(f"[DeepAgentExecutor] 开始执行: {user_input[:100]}...")
        try:
            response_mode = kwargs.get('response_mode')
            agent_name = kwargs.get('agent')
            graph = await build_graph(
                session_id=self.session_id,
                subagent_name=agent_name,
                deep_thinking=True,
                response_mode=response_mode
            )
            if not graph:
                raise ValueError(f"无法构建 DeepAgent 图（agent={agent_name}）")
            recursion_limit = get_config('agent.recursion_limit', 25)
            logger.info("[DeepAgentExecutor] 启动 DeepAgent...")
            # P2-4: 复用基类共享逻辑，消除与 ReActExecutor 的重复
            result = await self._invoke_graph_non_stream(
                graph, messages, recursion_limit, "deep_agent"
            )
            if result and isinstance(result[-1], AIMessage):
                meta = result[-1].response_metadata or {}
                if agent_name:
                    meta['selected_subagent'] = agent_name
                result[-1].response_metadata = meta
            return result
        except Exception as e:
            logger.error(f"[DeepAgentExecutor] 执行失败: {e}", exc_info=True)
            return [AIMessage(
                content=f"DeepAgent 执行失败: {e}",
                response_metadata={'error': str(e), 'executor': 'deep_agent'}
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
        start_time = time.time()
        try:
            response_mode = kwargs.get('response_mode')
            agent_name = kwargs.get('agent')
            graph = await build_graph(
                session_id=self.session_id,
                subagent_name=agent_name,
                deep_thinking=True,
                response_mode=response_mode
            )
            if not graph:
                error_msg = f"无法构建 DeepAgent 图（agent={agent_name}）"
                logger.error(f"[DeepAgentExecutor] {error_msg}")
                yield StreamResponseHelper.send_error(error_msg)
                return
            yield StreamResponseHelper.send_thinking_start()
            recursion_limit = get_config('agent.recursion_limit', 25)
            config = {
                "configurable": {"thread_id": self.session_id or "default"},
                "recursion_limit": recursion_limit,
            }
            # P2-15: ainvoke 是批量调用（非真 token 流式），期间无输出会让客户端冻结。
            # 改为后台任务 + 心跳循环：保留 ainvoke+extract_final_output 的 reasoning 处理不变，
            # 仅在等待期间周期性发 ping 保活，防网关超时掐断。
            # 用 asyncio.wait（超时不取消 task）而非 wait_for（超时取消 task 导致 re-await 失败）。
            # 真正的 token 级流式需 reasoning 内容提取（已随死代码删除），改了有回归风险，故用此安全迭代。
            # R1: 客户端断开（CancelledError 是 BaseException，不被 except Exception 捕获）时，
            # invoke_task 作为独立后台任务会继续跑 → LLM/工具配额泄漏。try/finally 保证取消。
            invoke_task = asyncio.create_task(graph.ainvoke({"messages": messages}, config=config))
            last_heartbeat = time.time()
            heartbeat_interval = get_heartbeat_interval()
            result = None
            try:
                while True:
                    done, _pending = await asyncio.wait({invoke_task}, timeout=heartbeat_interval)
                    if done:
                        result = invoke_task.result()  # ainvoke 抛异常时 re-raise 由外层 except 捕获
                        break
                    # 超时未完成：发心跳保活
                    if time.time() - last_heartbeat >= heartbeat_interval:
                        yield send_sse_data({'ping': _dt.datetime.now().isoformat()})
                        last_heartbeat = time.time()
            finally:
                # 客户端断开/异常退出时取消后台 ainvoke，防 LLM/工具继续执行泄漏资源
                if not invoke_task.done():
                    invoke_task.cancel()
                    try:
                        await invoke_task
                    except (asyncio.CancelledError, Exception):
                        pass  # 取消引发的异常无需传播
            output = extract_final_output(result)
            if output:
                async for chunk in StreamResponseHelper.send_content_chunks(output):
                    yield chunk
            duration = time.time() - start_time
            yield StreamResponseHelper.send_done()
            logger.info(f"[DeepAgentExecutor] 完成 | 耗时: {duration:.2f}s")
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[DeepAgentExecutor] 流式失败: {e}", exc_info=True)
            yield StreamResponseHelper.send_error(f'执行失败: {e}')