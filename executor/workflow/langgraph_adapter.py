from __future__ import annotations
import asyncio
from typing import Any, AsyncGenerator, Dict, Optional
from loguru import logger
from utils.planning.schemas import TaskNode, ExecutionPlan
from utils.config import get_config
from utils.planning.prompt_builder import build_workflow_prompt
from .types import is_error_result
try:
    from executor.langgraph import (
        LangGraphTaskExecutor,
        TaskContext as LangGraphTaskContext,
        ExecutionOptions as LangGraphExecutionOptions,
        TaskResult as LangGraphTaskResult,
    )
    from executor.langgraph.task_context import ExecutionEvent as LangGraphExecutionEvent
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    # fallback 定义，避免运行时 NameError（循环 import 时 try 失败）
    LangGraphTaskExecutor = None
    LangGraphTaskContext = None
    LangGraphExecutionOptions = None
    LangGraphTaskResult = None
    LangGraphExecutionEvent = None
    logger.warning("[LangGraphAdapter] LangGraph 不可用")
class LangGraphWorkflowAdapter:
    def __init__(
        self,
        langgraph_executor: LangGraphTaskExecutor,
        subagent_getter: callable,
        tools_getter: callable,
        llm_model: Optional[Any] = None,
        response_mode_getter: Optional[callable] = None,
        messages_getter: Optional[callable] = None,
    ):
        self._langgraph_executor = langgraph_executor
        self._get_subagent_config = subagent_getter
        self._get_subagent_tools = tools_getter
        self._llm_model = llm_model
        self._get_response_mode = response_mode_getter
        self._get_messages = messages_getter
    async def execute_task(
        self,
        task: TaskNode,
        plan: ExecutionPlan,
        context: Dict[str, Any],
        deep_thinking: bool = False,
        options: Optional[LangGraphExecutionOptions] = None,
        context_health: Optional[Dict[str, dict]] = None,
    ) -> Any:
        try:
            task_context = await self._build_task_context(task, plan, context, deep_thinking, context_health)
            if options is None:
                options = self._create_default_options()
            result = await self._langgraph_executor.execute_task(
                task=task,
                context=task_context,
                options=options,
            )
            if result.status.value == "completed":
                return result.output
            else:
                error_msg = result.error or ""
                logger.error(f"[LangGraphAdapter] 任务执行失败 {task.id}: {error_msg}")
                return f"error: {error_msg}"
        except Exception as e:
            logger.error(f"[LangGraphAdapter] 任务执行异常 {task.id}: {e}", exc_info=True)
            return f"error: {str(e)}"
    async def execute_task_stream(
        self,
        task: TaskNode,
        plan: ExecutionPlan,
        context: Dict[str, Any],
        deep_thinking: bool = False,
        options: Optional[LangGraphExecutionOptions] = None,
        context_health: Optional[Dict[str, dict]] = None,
    ) -> AsyncGenerator[Any, None]:
        try:
            task_context = await self._build_task_context(task, plan, context, deep_thinking, context_health)
            if options is None:
                options = self._create_default_options()
            async for event in self._langgraph_executor.execute_task_stream(
                task=task,
                context=task_context,
                options=options,
            ):
                yield event
        except Exception as e:
            logger.error(f"[LangGraphAdapter] 任务执行异常 {task.id}: {e}", exc_info=True)
            from executor.langgraph.task_context import ExecutionEvent as _ExecEvent
            yield _ExecEvent(
                type="error",
                data=str(e),
                metadata={"task_id": task.id}
            )
    async def _build_task_context(
        self,
        task: TaskNode,
        plan: ExecutionPlan,
        context: Dict[str, Any],
        deep_thinking: bool,
        context_health: Optional[Dict[str, dict]] = None,
    ) -> LangGraphTaskContext:
        subagent_getter = self._get_subagent_config
        # P2-10: 若 getter 是协程函数则 await，避免同步 DB 阻塞事件循环
        if asyncio.iscoroutinefunction(subagent_getter):
            subagent_config = await subagent_getter(task.agent)
        else:
            subagent_config = subagent_getter(task.agent)
        if not subagent_config:
            raise ValueError(f" Agent: {task.agent}")
        if asyncio.iscoroutinefunction(self._get_subagent_tools):
            tools, skill_index_text, _, kb_stats = await self._get_subagent_tools(task.agent, subagent_config)
        else:
            tools, skill_index_text, _, kb_stats = self._get_subagent_tools(task.agent, subagent_config)
        base_prompt = subagent_config.get("system_prompt", "")
        if skill_index_text:
            base_prompt = f"{base_prompt}\n\n{skill_index_text}"
        kb_details = kb_stats.get('details', [])
        if kb_details:
            kb_overview = "## \n" + "\n".join(f"- {d}" for d in kb_details)
            base_prompt = f"{base_prompt}\n\n{kb_overview}"
        response_mode = self._get_response_mode() if self._get_response_mode else None
        system_prompt = build_workflow_prompt(
            base_prompt=base_prompt,
            response_mode=response_mode,
            context_focus=task.context_focus,
            disable_thinking=False
        )
        logger.info(f"[LangGraphAdapter] ========== [{task.id}] SubAgent [{task.agent}] System Prompt ==========")
        logger.info(system_prompt)
        logger.info(f"[LangGraphAdapter] ========== System Prompt 结束 (长度: {len(system_prompt)}) ==========")
        llm_model = self._llm_model
        if llm_model is None:
            from utils.llm import get_default_llm
            llm_model = get_default_llm()
            if llm_model is None:
                raise ValueError(f" LLM : {task.agent}")
        from utils.llm.llm_factory import resolve_llm_by_model_id
        llm_model = resolve_llm_by_model_id(subagent_config, llm_model)
        dependencies = {}
        for dep_id in task.dependencies:
            if dep_id in context:
                dep_result = context[dep_id]
                if is_error_result(dep_result):
                    continue
                if context_health:
                    health = context_health.get(dep_id, {})
                    if health.get("status") == "degraded":
                        failed_tools = health.get("failed_tools", [])
                        dep_result = f"[ {failed_tools} ]\n{dep_result}"
                dependencies[dep_id] = dep_result
        skill_prompt_generator = None
        try:
            from core.builder.skill_backend import should_use_skill_backend
            use_skills_path = should_use_skill_backend()
        except ImportError:
            use_skills_path = False
        if use_skills_path:
            try:
                from domain.skill.registry import get_skill_registry
                registry = await get_skill_registry()
                skill_prompt_generator = registry.get_prompt_generator()
                if skill_prompt_generator:
                    logger.info(
                        "[LangGraphAdapter] SkillPromptGenerator 已获取"
                    )
                else:
                    logger.warning(
                        "[LangGraphAdapter] SkillPromptGenerator 为 None"
                    )
            except Exception as e:
                logger.warning(f"[LangGraphAdapter] SkillPromptGenerator 初始化失败: {e}")
        else:
            logger.debug("[LangGraphAdapter] Skills 中间件跳过 (use_skill_backend=false)")
        if use_skills_path and skill_prompt_generator:
            try:
                from tools.skill_file_tool import read_file
                from domain.skill.skill_file_reader import SkillFileReader
                from domain.skill.storage.local import LocalSkillStorage
                from domain.skill.storage.database import DatabaseSkillStorage
                from tools.skill_file_tool import get_skill_file_reader
                if get_skill_file_reader() is None:
                    from pathlib import Path
                    storages = []
                    try:
                        db_storage = DatabaseSkillStorage()
                        storages.append(db_storage)
                    except Exception:
                        db_storage = None
                    disk_storage = None
                    skills_dir_cfg = get_config('agent.skills_dir')
                    if skills_dir_cfg:
                        skills_dir = Path(skills_dir_cfg)
                        if not skills_dir.is_absolute():
                            app_dir = Path(__file__).resolve().parent.parent.parent
                            skills_dir = app_dir / skills_dir_cfg
                        if skills_dir.is_dir():
                            disk_storage = LocalSkillStorage(skills_dir)
                            storages.append(disk_storage)
                    reader = SkillFileReader(
                        disk_storage=disk_storage,
                        db_storage=db_storage,
                    )
                    reader.load_skills()
                    from tools.skill_file_tool import set_skill_file_reader
                    set_skill_file_reader(reader)
                tools = list(tools) + [read_file]
                logger.info("[LangGraphAdapter] 已注入 read_file 工具")
            except Exception as e:
                logger.warning(f"[LangGraphAdapter] read_file 工具注入失败: {e}")
        session_history = None
        logger.info(f"[LangGraphAdapter] _get_messages is {'set' if self._get_messages else 'None'}")
        if self._get_messages:
            from utils.message.history_helper import extract_session_history
            messages = self._get_messages()
            if messages and len(messages) > 1:
                session_history = extract_session_history(messages)
                if session_history:
                    logger.info(f"[LangGraphAdapter] 注入会话历史 {task.id} (长度: {len(session_history)})")
            # 提取 KB 上下文 SystemMessage（如 kb_refs 生成的【参考知识库】），
            # 注入到 system_prompt，否则 planning 模式下 task 执行时丢失引用片段
            if messages:
                from langchain_core.messages import SystemMessage as _SysMsg
                kb_parts = [str(m.content) for m in messages
                            if isinstance(m, _SysMsg) and '参考知识库' in str(m.content)]
                if kb_parts:
                    kb_context = '\n\n'.join(kb_parts)
                    system_prompt = f"{system_prompt}\n\n{kb_context}" if system_prompt else kb_context
                    logger.info(f"[LangGraphAdapter] 注入 KB 上下文到 system_prompt {task.id} (长度: {len(kb_context)})")
        from executor.langgraph.task_context import TaskContext as _TaskCtx
        return _TaskCtx(
            session_id="workflow",
            task_id=task.id,
            llm_model=llm_model,
            tools=tools,
            system_prompt=system_prompt,
            dependencies=dependencies,
            deep_thinking=deep_thinking,
            original_query=plan.original_query,
            context_focus=task.context_focus,
            skill_prompt_generator=skill_prompt_generator,
            session_history=session_history,
        )
    def _create_default_options(self):
        from executor.langgraph.task_context import ExecutionOptions as _ExecOpt
        return _ExecOpt(
            enable_streaming=True,
            timeout=get_config('agent.execution.timeout.task_timeout', 300),
            retry_on_error=True,
            max_retries=get_config('agent.execution.retry.max_attempts', 3),
            deep_thinking=False,
        )
def create_langgraph_adapter(
    langgraph_executor: LangGraphTaskExecutor,
    subagent_getter: callable,
    tools_getter: callable,
    llm_model: Optional[Any] = None,
    response_mode_getter: Optional[callable] = None,
    messages_getter: Optional[callable] = None,
) -> LangGraphWorkflowAdapter:
    return LangGraphWorkflowAdapter(
        langgraph_executor=langgraph_executor,
        subagent_getter=subagent_getter,
        tools_getter=tools_getter,
        llm_model=llm_model,
        response_mode_getter=response_mode_getter,
        messages_getter=messages_getter,
    )