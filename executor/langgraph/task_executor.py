from __future__ import annotations
import asyncio
import hashlib
import time
import uuid
from collections import OrderedDict
from typing import Any, AsyncGenerator, Dict, Optional
from langchain_core.messages import HumanMessage
from loguru import logger
from core.builder.agent_factory import AgentFactory, LangGraphAgentFactory
from utils.config import get_config
from utils.llm import wrap_llm_with_headers
from utils.planning.schemas import TaskNode
from core.middleware import CleanThinkMiddleware, ContextEditingMiddleware, ClearToolUsesEdit
from utils.message.extract import extract_final_output
from executor.workflow.types import is_error_result
from .event_parser import LangGraphEventParser
from .task_context import (
    ExecutionEvent,
    ExecutionOptions,
    TaskContext,
    TaskResult,
    TaskStatus,
    TaskType,
)
from .tool_health_tracker import ToolHealthTracker
try:
    from langgraph.checkpoint.memory import MemorySaver
    CHECKPOINTER_AVAILABLE = True
except ImportError:
    CHECKPOINTER_AVAILABLE = False
    logger.warning("[LangGraphTaskExecutor] langgraph.checkpoint 不可用，step 监控禁用")
class LangGraphTaskExecutor:
    def __init__(
        self,
        enable_step_monitor: bool = True,
        agent_factory: Optional[AgentFactory] = None,
    ):
        self.enable_step_monitor = enable_step_monitor and CHECKPOINTER_AVAILABLE
        self._agent_factory = agent_factory or LangGraphAgentFactory()
        # LRU 缓存：OrderedDict + 容量上限，防止多 agent/多 workspace 场景下
        # _compiled_graphs 无限增长（模块单例被两入口共享后风险更高）
        self._compiled_graphs: "OrderedDict[str, Any]" = OrderedDict()
        self._cache_max_entries: int = int(get_config('agent.execution.graph_cache.max_entries', 64))
        self._checkpointer_cache: Dict[str, MemorySaver] = {}
        if self.enable_step_monitor:
            logger.info("[LangGraphTaskExecutor] Step 监控启用（MemorySaver）")
        else:
            logger.debug("[LangGraphTaskExecutor] Step 监控禁用")

    def _touch_cache(self, key: str) -> None:
        """缓存命中时移到末尾（LRU 语义：最近用过的不先淘汰）。"""
        if key in self._compiled_graphs:
            self._compiled_graphs.move_to_end(key)

    def _evict_if_needed(self) -> None:
        """超 _cache_max_entries 时淘汰最旧条目。"""
        while len(self._compiled_graphs) > self._cache_max_entries:
            evicted_key, _ = self._compiled_graphs.popitem(last=False)
            logger.debug(f"[LangGraphTaskExecutor] LRU evict: {evicted_key}")

    def _log_traceback(self, task_id: str) -> None:
        """将当前异常的 traceback 输出到 logger.error。

        execute_task 和 execute_task_stream 的 except 块共用，
        避免重复 8 行 traceback 格式化 + 遍历代码。
        """
        import traceback as _tb
        tb_lines = _tb.format_exc().splitlines()
        for line in tb_lines:
            logger.error(f"[LangGraphTaskExecutor] {line}")
        for line in reversed(tb_lines):
            if line.strip().startswith("File"):
                logger.error(f"[LangGraphTaskExecutor] : {line.strip()}")
                break

    def _log_step_usage(self, checkpointer, thread_id: str,
                        task_id: str, recursion_limit: int) -> None:
        """记录 checkpoint step 使用率（total_steps / recursion_limit）。

        execute_task 和 execute_task_stream 的最终 step 监控共用，
        避免重复 checkpoint_config 构造 + list + len + logger.info 模板。
        """
        try:
            checkpoint_config = {"configurable": {"thread_id": thread_id}}
            checkpoints = list(checkpointer.list(checkpoint_config))
            final_step = len(checkpoints)
            logger.info(
                f"[LangGraphTaskExecutor] Step | task={task_id} | "
                f"total_steps={final_step} / {recursion_limit} | "
                f"usage={final_step / recursion_limit * 100:.1f}%"
            )
        except Exception as e:
            logger.debug(f"[LangGraphTaskExecutor] step monitor error: {e}")

    async def execute_task(
        self,
        task: TaskNode,
        context: TaskContext,
        options: ExecutionOptions,
    ) -> TaskResult:
        start_time = time.time()
        thread_id = f"{task.id}_{uuid.uuid4().hex[:8]}"
        try:
            graph, checkpointer = await self._get_or_build_graph(task, context)
            initial_state = {
                "messages": [HumanMessage(content=self._build_input(task, context))],
            }
            recursion_limit = get_config('agent.recursion_limit', 25)
            from utils.observability.langfuse_handler import attach_callbacks
            config = attach_callbacks({
                "configurable": {"thread_id": thread_id},
                "recursion_limit": recursion_limit,
            })
            logger.info(f"[LangGraphTaskExecutor] 开始执行: {task.id}, thread_id={thread_id}")
            final_state = await asyncio.wait_for(
                graph.ainvoke(initial_state, config=config),
                timeout=options.timeout,
            )
            if checkpointer and self.enable_step_monitor:
                self._log_step_usage(checkpointer, thread_id, task.id, config['recursion_limit'])
            output = extract_final_output(final_state)
            duration = time.time() - start_time
            logger.info(f"[LangGraphTaskExecutor] 执行完成: {task.id}, 耗时: {duration:.2f}s")
            return TaskResult(
                task_id=task.id,
                task_name=task.agent,
                status=TaskStatus.COMPLETED,
                task_type=TaskType.AGENT,
                duration=duration,
                output=output,
            )
        except asyncio.TimeoutError:
            duration = time.time() - start_time
            logger.error(f"[LangGraphTaskExecutor] 任务超时: {task.id}（timeout={options.timeout}s）")
            return TaskResult(
                task_id=task.id,
                task_name=task.agent,
                status=TaskStatus.FAILED,
                task_type=TaskType.AGENT,
                duration=duration,
                output="",
                error=f"{options.timeout}",
            )
        except Exception as e:
            duration = time.time() - start_time
            self._log_traceback(task.id)
            logger.error(f"[LangGraphTaskExecutor] 任务失败: {task.id}, 错误: {e}")
            return TaskResult(
                task_id=task.id,
                task_name=task.agent,
                status=TaskStatus.FAILED,
                task_type=TaskType.AGENT,
                duration=duration,
                output="",
                error=str(e),
            )
    async def execute_task_stream(
        self,
        task: TaskNode,
        context: TaskContext,
        options: ExecutionOptions,
    ) -> AsyncGenerator[ExecutionEvent, None]:
        from executor.workflow.types import ExecutionEvent as WfEvent, ExecutionEventType
        start_time = time.time()
        final_output = None
        all_messages = []
        thread_id = f"{task.id}_{uuid.uuid4().hex[:8]}"
        checkpointer = None
        try:
            graph, checkpointer = await self._get_or_build_graph(task, context)
            user_input = self._build_input(task, context)
            logger.info(f"[LangGraphTaskExecutor] ========== [{task.id}] User Message ==========")
            logger.info(user_input)
            logger.info(f"[LangGraphTaskExecutor] ========== User Message 结束 (长度: {len(user_input)}) ==========")
            initial_state = {
                "messages": [HumanMessage(content=user_input)],
            }
            recursion_limit = get_config('agent.recursion_limit', 25)
            from utils.observability.langfuse_handler import attach_callbacks
            config = attach_callbacks({
                "configurable": {"thread_id": thread_id},
                "recursion_limit": recursion_limit,
            })
            logger.info(f"[LangGraphTaskExecutor] : {task.id}, thread_id={thread_id}, recursion_limit={config['recursion_limit']}")
            event_parser = LangGraphEventParser(task.id)
            health_tracker = ToolHealthTracker()
            final_state = None
            step_counter = 0
            async for event in graph.astream(initial_state, config=config):
                final_state = event
                if checkpointer and self.enable_step_monitor:
                    try:
                        checkpoint_config = {"configurable": {"thread_id": thread_id}}
                        # P3-1: 用计数生成器替代 list() 物化——仅需步数计数，无需持有
                        # checkpoint 对象列表（每个 checkpoint 含完整图状态，长任务下 list() 每事件
                        # 全量载入内存开销大）。高 step 生产任务可关闭 agent.langgraph.step_monitor。
                        current_step = sum(1 for _ in checkpointer.list(checkpoint_config))
                        if current_step > step_counter:
                            step_counter = current_step
                            node_names = list(event.keys()) if isinstance(event, dict) else []
                            node_info = node_names[0] if node_names else "unknown"
                            logger.info(f"[LangGraphTaskExecutor] 📊 Step | task={task.id} | step={step_counter} | node={node_info}")
                    except Exception as e:
                        logger.debug(f"[LangGraphTaskExecutor] step monitor 读取 checkpoint 失败: {e}")
                for node_name, node_output in event.items():
                    if isinstance(node_output, dict) and "messages" in node_output:
                        msg_val = node_output["messages"]
                        if hasattr(msg_val, 'value'):
                            msg_val = msg_val.value
                        if isinstance(msg_val, (list, tuple)):
                            all_messages.extend(msg_val)
                async for evt in event_parser.parse_event(event):
                    health_tracker.on_event(evt)
                    yield evt
            if not all_messages and final_state:
                for node_output in final_state.values():
                    if isinstance(node_output, dict) and "messages" in node_output:
                        msg_val = node_output["messages"]
                        if hasattr(msg_val, 'value'):
                            msg_val = msg_val.value
                        if isinstance(msg_val, (list, tuple)):
                            all_messages.extend(msg_val)
            effective_state = {"messages": all_messages} if all_messages else (final_state or {})
            if final_state and not all_messages:
                effective_state = final_state
            if effective_state:
                final_output = extract_final_output(effective_state)
            duration = time.time() - start_time
            if checkpointer and self.enable_step_monitor:
                self._log_step_usage(checkpointer, thread_id, task.id, config['recursion_limit'])
            if final_output:
                yield WfEvent(
                    type=ExecutionEventType.CONTENT_CHUNK,
                    data=final_output,
                    metadata={"task_id": task.id, "is_final": True}
                )
            else:
                logger.warning(f"[LangGraphTaskExecutor] 任务输出为空: {task.id}")
                logger.warning(f"[LangGraphTaskExecutor] 所有消息: {all_messages}")
                yield WfEvent(
                    type=ExecutionEventType.CONTENT_CHUNK,
                    data="",
                    metadata={"task_id": task.id, "is_final": True, "warning": ""}
                )
            tool_health = health_tracker.get_health()
            yield WfEvent(
                type=ExecutionEventType.TASK_COMPLETED,
                data={"task_id": task.id, "result": final_output or ""},
                metadata={"tool_health": tool_health}
            )
            logger.info(f"[LangGraphTaskExecutor] 流式完成: {task.id}, 耗时={duration:.2f}s, output_len={len(final_output) if final_output else 0}")
        except Exception as e:
            duration = time.time() - start_time
            self._log_traceback(task.id)
            logger.error(f"[LangGraphTaskExecutor] 流式失败: {task.id}, 错误: {e}")
            yield WfEvent(
                type=ExecutionEventType.TASK_FAILED,
                data={"task_id": task.id},
                metadata={"error": str(e)}
            )
            yield WfEvent(
                type=ExecutionEventType.ERROR,
                data=str(e),
                metadata={"task_id": task.id}
            )
    async def _get_or_build_graph(
        self,
        task: TaskNode,
        context: TaskContext,
    ) -> tuple:
        cache_key = self._build_cache_key(task, context)
        if cache_key in self._compiled_graphs:
            logger.debug(f"[LangGraphTaskExecutor] 缓存命中: {cache_key}")
            self._touch_cache(cache_key)
            cached = self._compiled_graphs[cache_key]
            if isinstance(cached, tuple):
                return cached
            return (cached, None)
        logger.debug(f"[LangGraphTaskExecutor] 缓存未命中，构建图: {cache_key}")
        if not context.llm_model:
            raise ValueError(f" LLM : {task.agent}")
        llm = context.llm_model
        parallel_tool_calls = getattr(llm, 'model_kwargs', {}).get('parallel_tool_calls', 'N/A')
        logger.info(f"[LangGraphTaskExecutor] LLM  | model={llm.model_name if hasattr(llm, 'model_name') else llm.model if hasattr(llm, 'model') else 'unknown'} | "
                   f"parallel_tool_calls={parallel_tool_calls} | tools_count={len(context.tools)}")
        debug_mode = get_config('agent.debug', False)
        step_monitor_enabled = get_config('agent.langgraph.step_monitor', True) and self.enable_step_monitor
        edit_trigger = get_config('context.edit_trigger', 50000)
        edit_keep = get_config('context.edit_keep', 3)
        checkpointer = None
        if step_monitor_enabled and CHECKPOINTER_AVAILABLE:
            # L6a: 与外层 StateGraphBuilder 统一用 MysqlSaverFactory.get_saver()（共享单例），
            # 消除内层 MysqlSaver.create 与外层两套 checkpoint 实例/配置路径的分歧
            try:
                from utils.checkpoint import MysqlSaverFactory
                checkpointer = await MysqlSaverFactory.get_saver() or MemorySaver()
            except Exception as e:
                logger.warning(f"[LangGraphTaskExecutor] checkpoint init failed: {e}, fallback to MemorySaver")
                checkpointer = MemorySaver()
            logger.debug(f"[LangGraphTaskExecutor] Checkpointer: {type(checkpointer).__name__}")
        middlewares = []
        context_middleware = ContextEditingMiddleware(
            edits=[ClearToolUsesEdit(trigger=edit_trigger, keep=edit_keep)],
            default_trigger=edit_trigger,
            default_keep=edit_keep,
        )
        middlewares.append(context_middleware)
        logger.debug(f"[LangGraphTaskExecutor] 上下文编辑 middleware: trigger={edit_trigger}, keep={edit_keep}")
        clean_think = CleanThinkMiddleware(
            subagent_name=task.agent or "default",
            system_prompt=context.system_prompt or ""
        )
        middlewares.append(clean_think)
        wrapped_model = wrap_llm_with_headers(context.llm_model)
        tools = list(context.tools)
        # ToolExecutionGuard: 在 graph 构建前注入审批守卫
        try:
            agent_id = getattr(context, 'agent_id', task.agent or '')
            from core.guard.tool_guard_integration import wrap_tools_with_guard
            tools = wrap_tools_with_guard(tools, agent_id=agent_id)
        except Exception as e:
            logger.debug(f"[LangGraphTaskExecutor] Tool guard 注入失败（非致命）: {e}")
        try:
            from infrastructure.sandbox import is_sandbox_enabled
            if is_sandbox_enabled():
                from tools.sandbox_tools import get_sandbox_tools
                sandbox_tools = get_sandbox_tools()
                tools.extend(sandbox_tools)
                logger.debug(
                    f"[LangGraphTaskExecutor] 已注入 {len(sandbox_tools)} 个沙箱工具"
                )
        except Exception as e:
            logger.debug(f"[LangGraphTaskExecutor] 沙箱工具加载失败: {e}")
        factory_kwargs = {
            'model': wrapped_model,
            'tools': tools,
            'system_prompt': context.system_prompt,
            'middleware': middlewares,
        }
        if debug_mode:
            factory_kwargs['debug'] = True
            logger.info("[LangGraphTaskExecutor] LangGraph debug 模式已启用")
        if checkpointer:
            factory_kwargs['checkpointer'] = checkpointer
        skill_prompt_generator = getattr(context, 'skill_prompt_generator', None)
        if skill_prompt_generator:
            factory_kwargs['skill_prompt_generator'] = skill_prompt_generator
            logger.debug(
                f"[LangGraphTaskExecutor] skill_prompt_generator 已注入 factory"
            )
        compiled_graph = self._agent_factory.create(**factory_kwargs)
        self._compiled_graphs[cache_key] = (compiled_graph, checkpointer)
        self._evict_if_needed()
        return (compiled_graph, checkpointer)
    def _build_cache_key(
        self,
        task: TaskNode,
        context: TaskContext,
    ) -> str:
        # N4: cache 是 content-addressed（agent+tools+prompt）——同配置 agent 跨 workspace
        # 共享编译图是正确且高效的（非 bug）。workspace_id 仅在显式设置时入 key，
        # 用于多租户缓存压力场景按 workspace 分桶防互相淘汰；默认 None → 不分桶（全局 LRU）。
        tool_names = sorted([t.name for t in context.tools])
        tool_hash = hashlib.md5("_".join(tool_names).encode()).hexdigest()[:8]
        tool_count = len(context.tools)
        # P2-2: 对完整 system_prompt 取哈希（原仅 [:100]，同 agent 同 tools 但 prompt
        # 在 100 字符后才不同会碰撞命中错误缓存图——system_prompt 是编译期 bake 进 agent 的）
        prompt_hash = hashlib.md5(
            (context.system_prompt or "").encode()
        ).hexdigest()[:8]
        key_parts = [
            task.agent,
            f"{tool_count}tools",
            tool_hash,
            prompt_hash,
            "dt" if context.deep_thinking else "st",
            "sp" if getattr(context, 'skill_prompt_generator', None) else "nsp",
        ]
        ws = getattr(context, 'workspace_id', None)
        if ws:
            key_parts.append(f"ws{ws}")
        return "_".join(key_parts)

    def _truncate_dep_result(self, text: str, max_chars: int) -> str:
        """截断 dep_result 到 max_chars 以内，保留首 70% + 尾 30%，中间插标记。

        L2 前向兼容：result 可能是 str 或 TaskResultEnvelope，先经 result_to_text 归一。

        Args:
            text: 上游 task 结果文本（str 或 TaskResultEnvelope）
            max_chars: 字符上限；0 或负数表示不截断（兼容旧行为）
        Returns:
            截断后的文本（含标记）或原文本
        """
        from executor.workflow.types import result_to_text
        if not isinstance(text, str):
            text = result_to_text(text)
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        try:
            head = int(max_chars * 0.7)
            tail = max_chars - head
            omitted = len(text) - max_chars
            return (
                f"{text[:head]}"
                f"\n...[已截断 {omitted} 字符]...\n"
                f"{text[-tail:]}"
            )
        except Exception as e:
            logger.warning(f"[LangGraphTaskExecutor] dep_result 截断失败，原样返回: {e}")
            return text

    def _build_input(
        self,
        task: TaskNode,
        context: TaskContext,
    ) -> str:
        input_parts = []
        if hasattr(context, 'session_history') and context.session_history:
            input_parts.append(f"\n{context.session_history}")
            input_parts.append("")
        input_parts.append(task.description)
        if context.dependencies:
            max_chars = get_config('context.dep_result_max_chars', 6000)
            input_parts.append("\n")
            has_dep = False
            for dep_id, dep_result in context.dependencies.items():
                if is_error_result(dep_result):
                    continue
                truncated = self._truncate_dep_result(dep_result, max_chars)
                input_parts.append(f"---  {dep_id}  ---\n{truncated}\n")
                has_dep = True
            if not has_dep:
                input_parts.append("()\n")
            else:
                # W1: 提示 agent 可用 get_upstream_result 工具获取完整（未截断）上游结果
                input_parts.append(
                    "\n注：以上上游结果可能已截断，如需完整内容可调用 get_upstream_result(task_id) 工具。\n"
                )
        if context.original_query and context.original_query.strip() != task.description.strip():
            input_parts.append(f"\n\n{context.original_query}")
        return "\n".join(input_parts)
    def clear_cache(self, pattern: Optional[str] = None) -> int:
        if pattern is None:
            count = len(self._compiled_graphs)
            self._compiled_graphs.clear()
            logger.info(f"[LangGraphTaskExecutor] 清空图缓存: {count} 个")
            return count
        keys_to_remove = [k for k in self._compiled_graphs if pattern in k]
        for key in keys_to_remove:
            del self._compiled_graphs[key]
        logger.info(f"[LangGraphTaskExecutor] 按模式清理图缓存: {pattern}: {len(keys_to_remove)} 个")
        return len(keys_to_remove)
    def get_cache_stats(self) -> Dict[str, Any]:
        return {
            "cache_size": len(self._compiled_graphs),
            "cache_keys": list(self._compiled_graphs.keys()),
        }