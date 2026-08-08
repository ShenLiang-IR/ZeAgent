from loguru import logger
from typing import List, Optional, Any, Dict, AsyncGenerator
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from utils.message import create_request_id
from utils.config import get_config
import asyncio
import time
import re as _re
logger.propagate = True

# 匹配文件上传格式：【用户上传了文件「{filename}」，内容如下】\n\n{content}
_FILE_UPLOAD_HEADER = _re.compile(r'【用户上传了文件「(.+?)」，内容如下】\n\n')


async def _process_uploaded_files(user_input: str, session_id: str) -> str:
    """检测并处理内嵌文件上传：将文件内容写入沙箱，在消息末尾附加 sandbox 路径提示。

    当前端以「【用户上传了文件「xxx」，内容如下】」格式嵌入文件内容时，
    自动解析文件名与内容写入沙箱工作区，使 Agent 的 read_file 工具可直接读取。
    同时保留原嵌入内容作为兜底（沙箱不可用时 LLM 仍可直接从消息中读取）。

    Returns:
        处理后的 user_input（可能附加了沙箱路径提示），或原样返回。
    """
    if not _FILE_UPLOAD_HEADER.search(user_input):
        return user_input

    try:
        from infrastructure.sandbox import get_sandbox_provider
        provider = get_sandbox_provider()
        if provider is None:
            logger.info("[AgentService] 沙箱不可用，文件内容保留在消息中")
            return user_input
        sandbox = provider.acquire(session_id=session_id)
        # 同步设置全局 session_id，确保 Agent 的 read_file 工具获取同一个沙箱实例
        from tools.skill_file_tool import set_current_session_id
        set_current_session_id(session_id)

        # 解析每个文件块：header → 提取 filename + content → 写入沙箱
        files_written: list[tuple[str, str, int]] = []

        for m in _FILE_UPLOAD_HEADER.finditer(user_input):
            filename = m.group(1)
            content_start = m.end()
            remaining = user_input[content_start:]

            # 内容结束位置：下一个文件头 或 问题分隔符
            next_header = _FILE_UPLOAD_HEADER.search(remaining)
            question_idx = remaining.find('\n\n---\n\n【用户的问题】\n')

            if next_header and (question_idx < 0 or next_header.start() < question_idx):
                content_end = next_header.start()
            elif question_idx >= 0:
                content_end = question_idx
            else:
                content_end = len(remaining)

            file_content = remaining[:content_end].strip()
            sandbox_path = f"/mnt/workspace/{filename}"

            try:
                sandbox.write_file(sandbox_path, file_content)
                files_written.append((filename, sandbox_path, len(file_content)))
                logger.info(
                    f"[AgentService] 文件已写入沙箱: {sandbox_path} "
                    f"({len(file_content)} chars)"
                )
            except Exception as e:
                logger.warning(f"[AgentService] 文件写入沙箱失败: {filename} - {e}")

        if not files_written:
            return user_input

        # 在消息末尾附加沙箱路径提示（Agent 可通过 read_file 工具读取）
        lines = [
            f"  - {fname} → {fpath}"
            for fname, fpath, _ in files_written
        ]
        hint = (
            f"\n\n---\n"
            f"💡 提示：上传的文件已同步到沙箱工作区，你可以使用 read_file 工具读取：\n"
            + "\n".join(lines)
        )
        logger.info(
            f"[AgentService] 文件上传处理完成: {len(files_written)} 个文件已写入沙箱"
        )
        return user_input + hint

    except Exception as e:
        logger.warning(f"[AgentService] 处理文件上传异常: {e}")
        return user_input


class AgentService:
    def __init__(
        self,
        session_id: str = "default",
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        llm_model: Optional[Any] = None,
        enable_context_optimization: bool = True,
        skip_memory: bool = False
    ):
        self.session_id = self._normalize_session_id(session_id)
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.llm_model = llm_model
        self.enable_context_optimization = enable_context_optimization
        self._skip_memory = skip_memory
        if enable_context_optimization:
            from utils.common.context_manager import ContextManager
            self._context_manager = ContextManager(session_id=self.session_id)
            logger.debug(f"[AgentService] : session_id={self.session_id}")
        else:
            self._context_manager = None
        if not self._skip_memory and get_config('memory.enabled', True):
            from memory import get_memory_manager
            use_hybrid_search = get_config('memory.use_hybrid_search', True)
            hybrid_config_dict = get_config('memory.hybrid_config', {
                "mode": "hybrid",
                "bm25_weight": 0.3,
                "vector_weight": 0.7,
                "rrf_k": 60,
                "similarity_threshold": 0.5,
                "reranking_enabled": False
            })
            vector_backend = get_config('memory.vector_backend', None)
            vector_config = get_config('memory.vector_config', {})
            self._memory_manager = get_memory_manager(
                vector_backend=vector_backend if vector_backend else None,
                vector_config=vector_config if vector_backend else None,
                use_hybrid_search=use_hybrid_search,
                hybrid_config=hybrid_config_dict
            )
            logger.debug(f"[AgentService]  | hybrid_search={use_hybrid_search}")
        else:
            self._memory_manager = None
            reason = "" if self._skip_memory else ""
            logger.debug(f"[AgentService]  | : {reason}")
    @staticmethod
    def _normalize_session_id(session_id: str) -> str:
        if session_id and '-' in session_id:
            return session_id.replace('-', '')
        return session_id
    def set_session_id(self, session_id: str):
        normalized_id = self._normalize_session_id(session_id)
        if normalized_id != self.session_id:
            self.session_id = normalized_id
            if self._context_manager:
                self._context_manager.set_session_id(normalized_id)
            logger.debug(f"[AgentService]  ID : {normalized_id}")
    def _load_conversation_history(self) -> List[BaseMessage]:
        if self.session_id and self.session_id.startswith('preview_'):
            return []
        try:
            from utils.db import get_chat_db
            from utils.config import get_config
            chat_db = get_chat_db()
            user_id = str(self.user_id) if self.user_id else 'guest'

            def _to_msgs(msgs):
                out = []
                for msg in msgs:
                    role = msg.get('role')
                    content = msg.get('content', '')
                    if isinstance(content, dict):
                        content = content.get('text', '') or content.get('content', str(content))
                    if role in ('1', 'user'):
                        out.append(HumanMessage(content=str(content)))
                    elif role in ('2', 'assistant'):
                        out.append(AIMessage(content=str(content)))
                return out

            db_messages = chat_db.get_messages(user_id, self.session_id)
            history = _to_msgs(db_messages)
            # 跨 session 对话历史加载（开关控制，默认 false 新会话隔离）
            if get_config('memory.cross_session_history', False) and self.user_id:
                limit = int(get_config('memory.cross_session_history_limit', 10))
                cross_msgs = chat_db.get_recent_messages_across_sessions(
                    user_id=user_id, limit=limit, exclude_session_id=self.session_id)
                cross_history = _to_msgs(cross_msgs)
                if cross_history:
                    # 跨 session 历史在当前 session 历史之前（更早的上下文）
                    history = cross_history + history
                    logger.info(f"[AgentService] 跨session历史 {len(cross_history)} + 当前session {len(db_messages)}")
            logger.info(f"[AgentService] 对话历史 {len(history)} 条")
            return history
        except Exception as e:
            logger.warning(f"[AgentService] 加载对话历史失败: {e}")
            return []
    async def _build_memory_context(self, user_input: str) -> Optional[str]:
        """召回相关记忆 + 用户偏好，拼装 memory_context（注入 LLM 上下文）。

        - 用户偏好：按 user_id 跨 session 召回长期 preference（个性化）
        - 相关记忆：session 内 + 跨 session fact
        """
        if not self._memory_manager:
            return None
        try:
            parts = []
            # 用户偏好：按当前问题相关性召回，只注入与 query 相关的 preference
            # （避免无关问题如"首都"被偏好"吃辣"带偏）
            prefs_raw = await self._memory_manager.recall(
                query=user_input, limit=10,  # 提高召回数（limit=3 时 chromadb 向量 top3 可能都是 fact/event，preference 排后面进不来）
                user_id=self.user_id, workspace_id=self.workspace_id, tiers=["long_term"]
            )
            prefs_pref = [m for m in prefs_raw if m.type and getattr(m.type, "value", str(m.type)) == "preference"]
            # 信任 recall 相关性排序：recall 已按 query 召回 top_k 最相关记忆，
            # preference 过滤后直接注入 top3（不再用固定 hybrid_score/similarity 阈值，
            # 因 cross_session 走 BM25+向量 RRF 后 score 范围 ~0.01~0.1，与原 vector similarity 0.7+ 不可比）
            prefs = prefs_pref[:3]
            logger.info(f"[AgentService] recall preference: raw={len(prefs_raw)} pref={len(prefs_pref)} injected={len(prefs)}")
            if prefs:
                parts.append("用户偏好:\n" + "\n".join(f"- {p.content[:100]}" for p in prefs))
            # 相关记忆（session 内 + 跨 session fact；排除 preference，已在上面按相关性处理）
            relevant = await self._memory_manager.recall(
                query=user_input, limit=3,
                session_id=self.session_id, user_id=self.user_id,
                workspace_id=self.workspace_id
            )
            relevant = [m for m in relevant if not (m.type and getattr(m.type, "value", str(m.type)) == "preference")]
            if relevant:
                parts.append("相关记忆:\n" + "\n".join(f"- {m.content[:200]}" for m in relevant[:3]))
                logger.info(f"[AgentService] 召回 {len(relevant)} 条相关记忆")
            return "\n\n".join(parts) if parts else None
        except Exception as e:
            logger.warning(f"[AgentService] 召回记忆失败: {e}")
            return None

    async def chat(
        self,
        messages: List[BaseMessage],
        agent: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
        response_mode: Optional[str] = None,
        deep_thinking: bool = False,
        **kwargs
    ) -> List[BaseMessage]:
        compression_stats = {}
        user_input = self._extract_user_input(messages)
        if not user_input:
            raise ValueError("")
        # 处理文件上传：将文件内容写入沙箱，使 Agent 的 read_file 工具可读取
        processed_input = await _process_uploaded_files(user_input, self.session_id)
        if processed_input != user_input:
            user_input = processed_input
            for i in range(len(messages) - 1, -1, -1):
                if isinstance(messages[i], HumanMessage):
                    messages[i] = HumanMessage(content=user_input)
                    break
        history_messages = self._load_conversation_history()
        if history_messages:
            # 保留当前请求携带的上下文型 SystemMessage（如 kb_refs 生成的【参考知识库】），
            # 否则历史重建会丢弃知识库引用，LLM 只见 #占位符# 文本而无引用内容
            request_context = [msg for msg in messages if isinstance(msg, SystemMessage)]
            messages = request_context + history_messages + [HumanMessage(content=user_input)]
        else:
            messages = [msg for msg in messages
                        if not (isinstance(msg, AIMessage) and not (msg.content or '').strip())]
        if self._context_manager and len(messages) > 1:
            logger.debug(
                f"[AgentService.chat]  llm_model : "
                f"type={type(self.llm_model).__name__ if self.llm_model else 'None'}, "
                f"is_none={self.llm_model is None}"
            )
            messages, compression_stats = self._context_manager.optimize_messages(
                messages=messages,
                current_input=user_input,
                llm_model=self.llm_model
            )
            logger.debug(
                f"[AgentService.chat] : "
                f"summary={'(:' + str(len(compression_stats.get('summary', ''))) + ')' if compression_stats.get('summary') else ''}, "
                f"strategies={compression_stats.get('strategies_applied', [])}"
            )
            if compression_stats.get('compression_ratio', 0) > 0:
                logger.info(
                    f"[AgentService] : {compression_stats['original_tokens']} -> "
                    f"{compression_stats['final_tokens']} tokens "
                    f"(: {compression_stats['compression_ratio']:.1%})"
                )
        # 首次调用时回灌即时/短期记忆（幂等，须在 recall 之前，否则重启后首次 recall 查不到旧记忆）
        if self._memory_manager and not getattr(self._memory_manager, '_tiers_loaded', True):
            try:
                await self._memory_manager.initialize()
            except Exception as e:
                logger.warning(f"[AgentService] 记忆回灌 initialize 失败: {e}")
        memory_context = await self._build_memory_context(user_input)
        if memory_context:
            kwargs['memory_context'] = memory_context
        from executor.factory import ExecutorFactory, ExecutionMode
        # agent.auto_plan=true → 走 LLM 自主规划（PlanExecutor），与 backend 正交
        if get_config('agent.auto_plan', False):
            execution_mode = ExecutionMode.PLANNING
        else:
            backend = get_config('agent.backend', 'langgraph')
            if backend == 'deepagents':
                execution_mode = ExecutionMode.DEEP_AGENT
            elif backend == 'planning':
                execution_mode = ExecutionMode.PLANNING
            else:
                execution_mode = ExecutionMode.REACT
        # 修复：前端"深度思考"勾选（deep_thinking=True）强制走 DeepAgentExecutor，
        # 覆盖默认 react 模式（原默认 langgraph 下勾选无效果）；
        # planning（auto_plan/显式自主规划）不被覆盖——规划模式内部每 task 自行决定
        if deep_thinking and execution_mode == ExecutionMode.REACT:
            execution_mode = ExecutionMode.DEEP_AGENT
        logger.info(
            f"[AgentService.chat]  - "
            f"session_id={self.session_id}, "
            f"user_input_length={len(user_input)}, "
            f"execution_mode={execution_mode.value}, "
            f"agent={agent}, "
            f"deep_thinking={deep_thinking}, "
            f"response_mode={response_mode}"
        )
        request_id = await self._save_user_input(messages)
        if agent:
            kwargs['agent'] = agent
        if agent_config:
            kwargs['agent_config'] = agent_config
        kwargs['deep_thinking'] = deep_thinking
        if response_mode:
            kwargs['response_mode'] = response_mode
        executor = ExecutorFactory.create_executor(
            execution_mode=execution_mode,
            session_id=self.session_id,
            llm_model=self.llm_model,
            workspace_id=int(self.workspace_id) if self.workspace_id and str(self.workspace_id).isdigit() else None
        )
        result_messages = await executor.execute(messages, **kwargs)
        # AI 回复由 chat_routes chat endpoint 统一保存（含 workflow metadata），
        # 此处不再 _save_ai_response，避免双重保存导致历史加载重复 AI 消息
        if self._memory_manager and result_messages:
            if get_config('memory.auto_store_conversation', True):
                # 异步提取：避免阻塞用户问答主流程（提取失败仅记日志，不影响对话）
                _task = asyncio.create_task(self._store_conversation_to_memory(
                    user_input=user_input,
                    response_messages=result_messages,
                ))
                _task.add_done_callback(self._on_extract_done)
        if result_messages and request_id:
            last_message = result_messages[-1]
            if isinstance(last_message, AIMessage):
                metadata = last_message.response_metadata or {}
                if not metadata.get('request_id'):
                    metadata['request_id'] = request_id
                    last_message.response_metadata = metadata
        logger.info(
            f"[AgentService] : session_id={self.session_id}, "
            f"result_messages_count={len(result_messages)}"
        )
        return result_messages
    @staticmethod
    def _on_extract_done(task: "asyncio.Task") -> None:
        """异步记忆提取完成回调：仅记日志，不抛异常影响主流程。"""
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc:
            logger.warning(f"[AgentService] 异步记忆提取失败: {exc}")

    async def remember(
        self,
        content: str,
        memory_type: str = "note",
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
        metadata: Optional[dict] = None
    ) -> str:
        if not self._memory_manager:
            logger.warning("[AgentService] ")
            return ""
        memory = await self._memory_manager.remember(
            content=content,
            type=memory_type,
            importance=importance,
            session_id=self.session_id,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            tags=tags,
            metadata=metadata
        )
        logger.debug(f"[AgentService] : {memory.id}")
        return memory.id
    async def recall(
        self,
        query: str,
        limit: int = 5
    ) -> List[dict]:
        if not self._memory_manager:
            logger.warning("[AgentService] ")
            return []
        memories = await self._memory_manager.recall(
            query=query,
            limit=limit,
            session_id=self.session_id,
            workspace_id=self.workspace_id
        )
        return [m.to_dict() for m in memories]
    async def get_context_memories(self, limit: int = 5) -> List[dict]:
        if not self._memory_manager:
            logger.warning("[AgentService] ")
            return []
        memories = await self._memory_manager.get_context_memories(
            session_id=self.session_id,
            limit=limit
        )
        return [m.to_dict() for m in memories]
    async def forget(self, memory_id: str) -> bool:
        if not self._memory_manager:
            logger.warning("[AgentService] ")
            return False
        return await self._memory_manager.forget(memory_id)
    async def get_memory_stats(self) -> dict:
        if not self._memory_manager:
            return {"enabled": False, "message": ""}
        stats = await self._memory_manager.get_stats()
        stats["enabled"] = True
        return stats
    async def chat_stream(
        self,
        messages: List[BaseMessage],
        agent: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
        response_mode: Optional[str] = None,
        deep_thinking: bool = False,
        event_sender: Optional[Any] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        total_start = time.time()
        compression_stats = {}
        user_input = self._extract_user_input(messages)
        if not user_input:
            from utils.sse import send_sse_data
            yield send_sse_data({'error': ""})
            return
        # 处理文件上传：将文件内容写入沙箱，使 Agent 的 read_file 工具可读取
        processed_input = await _process_uploaded_files(user_input, self.session_id)
        if processed_input != user_input:
            user_input = processed_input
            for i in range(len(messages) - 1, -1, -1):
                if isinstance(messages[i], HumanMessage):
                    messages[i] = HumanMessage(content=user_input)
                    break
        history_messages = self._load_conversation_history()
        if history_messages:
            # 保留当前请求携带的上下文型 SystemMessage（如 kb_refs 生成的【参考知识库】），
            # 否则历史重建会丢弃知识库引用，LLM 只见 #占位符# 文本而无引用内容
            request_context = [msg for msg in messages if isinstance(msg, SystemMessage)]
            messages = request_context + history_messages + [HumanMessage(content=user_input)]
        else:
            messages = [msg for msg in messages
                        if not (isinstance(msg, AIMessage) and not (msg.content or '').strip())]
        if self._context_manager and len(messages) > 1:
            logger.debug(
                f"[AgentService.chat_stream]  llm_model : "
                f"type={type(self.llm_model).__name__ if self.llm_model else 'None'}, "
                f"is_none={self.llm_model is None}"
            )
            messages, compression_stats = self._context_manager.optimize_messages(
                messages=messages,
                current_input=user_input,
                llm_model=self.llm_model
            )
            logger.debug(
                f"[AgentService.chat_stream] : "
                f"summary={'(:' + str(len(compression_stats.get('summary', ''))) + ')' if compression_stats.get('summary') else ''}, "
                f"strategies={compression_stats.get('strategies_applied', [])}"
            )
            if compression_stats.get('compression_ratio', 0) > 0:
                logger.info(
                    f"[AgentService] : {compression_stats['original_tokens']} -> "
                    f"{compression_stats['final_tokens']} tokens "
                    f"(: {compression_stats['compression_ratio']:.1%})"
                )
        # 首次调用时回灌即时/短期记忆（幂等，须在 recall 之前，否则重启后首次 recall 查不到旧记忆）
        if self._memory_manager and not getattr(self._memory_manager, '_tiers_loaded', True):
            try:
                await self._memory_manager.initialize()
            except Exception as e:
                logger.warning(f"[AgentService] 记忆回灌 initialize 失败: {e}")
        memory_context = await self._build_memory_context(user_input)
        if memory_context:
            kwargs['memory_context'] = memory_context
        from executor.factory import ExecutorFactory, ExecutionMode
        # agent.auto_plan=true → 走 LLM 自主规划（PlanExecutor），与 backend 正交
        if get_config('agent.auto_plan', False):
            execution_mode = ExecutionMode.PLANNING
        else:
            backend = get_config('agent.backend', 'langgraph')
            if backend == 'deepagents':
                execution_mode = ExecutionMode.DEEP_AGENT
            elif backend == 'planning':
                execution_mode = ExecutionMode.PLANNING
            else:
                execution_mode = ExecutionMode.REACT
        # 修复：前端"深度思考"勾选强制走 DeepAgentExecutor（覆盖 react；planning 不被覆盖）
        if deep_thinking and execution_mode == ExecutionMode.REACT:
            execution_mode = ExecutionMode.DEEP_AGENT
        logger.info(
            f"[AgentService.chat_stream]  - "
            f"session_id={self.session_id}, "
            f"user_input_length={len(user_input)}, "
            f"execution_mode={execution_mode.value}, "
            f"agent={agent}, "
            f"deep_thinking={deep_thinking}, "
            f"response_mode={response_mode}"
        )
        save_input_start = time.time()
        request_id = await self._save_user_input(messages)
        save_input_duration = time.time() - save_input_start
        if request_id:
            kwargs['request_id'] = request_id
        logger.info(f"[AgentService] ⏱️ : {save_input_duration:.2f}")
        if agent:
            kwargs['agent'] = agent
        if agent_config:
            kwargs['agent_config'] = agent_config
        kwargs['deep_thinking'] = deep_thinking
        if response_mode:
            kwargs['response_mode'] = response_mode
        from utils.sse import send_sse_data
        if event_sender:
            yield event_sender.send_config()
        yield send_sse_data({'status': 'started'})
        create_executor_start = time.time()
        executor = ExecutorFactory.create_executor(
            execution_mode=execution_mode,
            session_id=self.session_id,
            llm_model=self.llm_model,
            workspace_id=int(self.workspace_id) if self.workspace_id and str(self.workspace_id).isdigit() else None
        )
        create_executor_duration = time.time() - create_executor_start
        logger.info(f"[AgentService] ⏱️ : {create_executor_duration:.2f}")
        execute_start = time.time()
        collected_content = []
        import json as _json
        # 诊断：记录传给执行器的消息详情（排查 KB 上下文丢失）
        _msg_types = [type(m).__name__ for m in messages]
        _has_kb = any(isinstance(m, SystemMessage) and "参考知识库" in (m.content or "") for m in messages)
        logger.info(f"[AgentService.chat_stream] 传给执行器: {len(messages)} 条消息, "
                    f"types={_msg_types}, 含KB上下文={_has_kb}")
        async for data in executor.execute_stream(
            messages=messages,
            event_sender=event_sender,
            **kwargs
        ):
            # 收集 AI 回复 content（供 _store 提取 fact/relation，否则 _store 拿不到 AI 回复）
            if isinstance(data, str) and data.startswith('data: '):
                try:
                    _sse = _json.loads(data[6:])
                    if isinstance(_sse, dict) and _sse.get('content'):
                        collected_content.append(_sse['content'])
                except (ValueError, TypeError):
                    pass
            yield data
        execute_duration = time.time() - execute_start
        logger.info(f"[AgentService] ⏱️ : {execute_duration:.2f}")
        final_ai_content = ''.join(collected_content)
        # AI 输出安全审查
        if final_ai_content:
            from core.security.content_filter import filter_content as _ai_filter
            _ai_fr = _ai_filter(final_ai_content)
            if _ai_fr.blocked:
                logger.warning(f"[AgentService] AI 输出命中敏感词: {_ai_fr.matched}")
                from core.security.content_filter import log_filter_event
                log_filter_event(final_ai_content, _ai_fr.matched, "output",
                                str(self.user_id), "", int(self.workspace_id) if self.workspace_id else None)
                final_ai_content = f"[内容安全] AI 输出被拦截（匹配词: {','.join(_ai_fr.matched[:3])}）"
                from utils.sse import send_sse_data
                yield send_sse_data({'content': final_ai_content, 'filtered': True, 'done': True})
        # AI 回复由 chat_routes generate 统一保存（含 reasoning/workflow metadata），
        # 此处不再 _save_ai_response，避免双重保存导致历史加载重复 AI 消息
        if self._memory_manager:
            if get_config('memory.auto_store_conversation', True):
                # 后台任务执行：避免 client 读完 SSE 断开后 chat_stream aclose 中断 _store（记忆写入）
                import asyncio as _aio
                _aio.create_task(self._store_conversation_to_memory(
                    user_input=user_input,
                    response_messages=[AIMessage(content=final_ai_content)] if final_ai_content else None,
                ))
        total_duration = time.time() - total_start
        logger.info(f"[AgentService] ⏱️ chat_stream: {total_duration:.2f} (save_input: {save_input_duration:.2f}s, create_executor: {create_executor_duration:.2f}s, execute: {execute_duration:.2f}s)")
    def _extract_user_input(self, messages: List[BaseMessage]) -> str:
        from utils.message.message_helper import extract_user_input_from_messages
        return extract_user_input_from_messages(messages)
    async def _save_user_input(self, messages: List[BaseMessage]) -> Optional[str]:
        if self.session_id and self.session_id.startswith('preview_'):
            logger.debug(f"[AgentService] : session_id={self.session_id}")
            return create_request_id(self.session_id)
        user_input = self._extract_user_input(messages)
        if not user_input or not user_input.strip():
            return None
        try:
            request_id = create_request_id(self.session_id)
            from utils.db import get_chat_db
            chat_db = get_chat_db()
            user_id = str(self.user_id) if self.user_id else 'guest'
            logger.debug(f"[_save_user_input]  - self.user_id={self.user_id}, user_id={user_id}, session_id={self.session_id}")
            session = chat_db.get_session(user_id, self.session_id)
            if not session:
                logger.warning(f"[_save_user_input] : session_id={self.session_id}")
                return None
            existing_messages = chat_db.get_messages(user_id, self.session_id)
            message_order = len(existing_messages)
            success = chat_db.save_message(
                user_id=user_id,
                session_id=self.session_id,
                role='1',
                content=user_input,
                message_order=message_order
            )
            if success:
                logger.debug(f"Agent 会话: session_id={self.session_id}, request_id={request_id}")
                try:
                    if session and (not session.get('title') or session.get('title') == ''):
                        auto_title = user_input[:50].strip()
                        if not auto_title:
                            auto_title = ''
                        updated_session = chat_db.update_session(
                            user_id=user_id,
                            pr_key_id=self.session_id,
                            title=auto_title
                        )
                        if updated_session:
                            logger.debug(f"[AgentService] : session_id={self.session_id}, title={auto_title}")
                except Exception as title_error:
                    logger.warning(f"[AgentService] : {title_error}")
                return request_id
        except Exception as e:
            logger.warning(f"Agent 服务异常: {e}")
        return None
    async def _save_ai_response(self, ai_content: str) -> None:
        """保存 AI 回复到聊天数据库（role='2'），与用户消息配对。

        无此方法时 _load_conversation_history 只能加载用户消息，
        导致 LLM 缺少上下文（如用户前说"喜欢吃辣"，后问"推荐菜"时无法关联）。
        """
        if not ai_content or not ai_content.strip():
            return
        if self.session_id and self.session_id.startswith('preview_'):
            return
        try:
            from utils.db import get_chat_db
            chat_db = get_chat_db()
            user_id = str(self.user_id) if self.user_id else 'guest'
            session = chat_db.get_session(user_id, self.session_id)
            if not session:
                logger.warning(f"[_save_ai_response] session not found: session_id={self.session_id}")
                return
            existing_messages = chat_db.get_messages(user_id, self.session_id)
            message_order = len(existing_messages)
            chat_db.save_message(
                user_id=user_id,
                session_id=self.session_id,
                role='2',
                content=ai_content,
                message_order=message_order
            )
            logger.debug(f"[AgentService] AI回复已保存: session_id={self.session_id}, order={message_order}")
        except Exception as e:
            logger.warning(f"[AgentService] AI回复保存失败: {e}")
    async def _store_conversation_to_memory(
        self,
        user_input: str,
        response_messages: Optional[List[BaseMessage]] = None,
    ) -> None:
        if not self.llm_model:
            return
        try:
            assistant_response = ""
            if response_messages:
                for msg in reversed(response_messages):
                    if hasattr(msg, 'content') and msg.content:
                        assistant_response = str(msg.content)[:500]
                        break
            extract_prompt = self._get_extract_prompt(user_input, assistant_response)
            if not extract_prompt:
                return  # 无记忆提取模板（提示词管理未配置/被禁用），跳过提取
            response = await self.llm_model.ainvoke([HumanMessage(content=extract_prompt)])
            result = response.content if hasattr(response, 'content') else str(response)
            result = result.strip()
            # 兼容 LLM 用 ```json ... ``` markdown 包裹 JSON
            import re as _re
            _m = _re.search(r'```(?:json)?\s*(.*?)```', result, _re.DOTALL)
            if _m:
                result = _m.group(1).strip()
            # 兼容 LLM 前后带说明文字，提取首个 JSON 数组
            if not result.startswith('['):
                _arr = _re.search(r'\[.*\]', result, _re.DOTALL)
                if _arr:
                    result = _arr.group(0)
            import json as _json
            try:
                items = _json.loads(result)
            except Exception:
                items = [{"type": "fact", "content": result[:500], "importance": 0.6}] if result else []
            if not isinstance(items, list) or not items:
                return
            stored_types = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                content = str(it.get("content", "")).strip()
                if not content or len(content) < 5:
                    continue
                mtype = it.get("type", "fact")
                try:
                    importance = float(it.get("importance", 0.6))
                except (TypeError, ValueError):
                    importance = 0.6
                try:
                    await self._memory_manager.remember(
                        content=content,
                        type=mtype,
                        importance=importance,
                        session_id=self.session_id,
                        user_id=self.user_id,
                        workspace_id=self.workspace_id,
                        tags=["extracted", "auto_stored", mtype],
                        source_session_id=self.session_id,
                    )
                    stored_types.append(mtype)
                except Exception as item_e:
                    logger.warning(f"[AgentService] 单条记忆存储失败(type={mtype}): {item_e}")
            if stored_types:
                logger.info(f"[AgentService] 已存储 {len(stored_types)} 条结构化记忆: {stored_types}")
        except Exception as e:
            logger.warning(f"[AgentService] : {e}")

    def _get_extract_prompt(self, user_input: str, assistant_response: str) -> Optional[str]:
        """读取记忆提取 prompt：完全由提示词管理 DB 驱动，无模板则返回 None。

        提示词管理（系统管理 > 提示词管理）编辑 name=memory_extract_prompt 的模板，
        content 支持 {{user_input}} / {{assistant_response}} 变量占位。
        无模板/被禁用/读取失败 → 返回 None，_store 跳过提取（不影响对话）。
        """
        try:
            from infrastructure.database.repositories.prompt_template_repository import PromptTemplateRepository
            tpl = PromptTemplateRepository().get_by_name("memory_extract_prompt")
            if tpl and tpl.get('content') and tpl.get('enabled') != '0':
                prompt = tpl['content'].replace(
                    '{{user_input}}', user_input).replace(
                    '{{assistant_response}}', assistant_response or '（无）')
                logger.info(f"[AgentService] 记忆提取用DB模板(v{tpl.get('version', '?')})")
                return prompt
            logger.warning("[AgentService] 提示词管理无 memory_extract_prompt 模板或已禁用，跳过记忆提取（请到系统管理>提示词管理创建）")
        except Exception as e:
            logger.warning(f"[AgentService] 读取记忆提取模板失败，跳过提取: {e}")
        return None