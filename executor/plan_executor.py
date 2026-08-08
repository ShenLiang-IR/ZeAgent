from __future__ import annotations
import time
import asyncio
from typing import List, Dict, Any, Optional, AsyncGenerator
from langchain_core.messages import BaseMessage, AIMessage
from loguru import logger
from .base_executor import BaseExecutor
from .stream_helper import StreamResponseHelper
# P2-2: SSE 格式化真相源在 utils.sse，executor 层不再反向依赖 api.chat 层
# P1-4: 兜底返回空串而非 None，避免被 yield 进 SSE 流后产出 data: null
try:
    from utils.sse import _send_execution_event
except ImportError:
    def _send_execution_event(*args, **kwargs):
        return ""
from utils.planning.generator import generate_execution_plan
from utils.planning.schemas import ExecutionPlan, TaskNode, PlanMode
from utils.config import get_config_db, get_config
from utils.config.config_loader import get_agent_config
from utils.config.mode_helper import get_mode_prompt_suffix
from core.builder import collect_subagent_tools_async
from utils.message.history_helper import extract_session_history
try:
    from executor.langgraph import (
        LangGraphTaskExecutor,
        ExecutionOptions as LangGraphExecutionOptions,
        TaskResult as LangGraphTaskResult,
        TaskStatus as LangGraphTaskStatus,
        TaskType as LangGraphTaskType,
    )
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    logger.warning("[PlanExecutor] LangGraph  AgentExecutor")
try:
    from executor.workflow import (
        create_workflow_adapter,
        ExecutionEvent as WorkflowExecutionEvent,
        ExecutionEventType as WorkflowExecutionEventType,
    )
    WORKFLOW_AVAILABLE = True
except ImportError:
    WORKFLOW_AVAILABLE = False
    logger.warning("[PlanExecutor] ")
from executor.workflow.types import is_error_result

# P2-19: 集中 task 描述预览截断长度，消除散落的魔法数字 57/60/77/80
_DESC_PREVIEW_LEN = 60
_DESC_PREVIEW_LEN_WIDE = 80

# ─── VOTE 模式辅助函数 ───

def _extract_vote_choice(text: str) -> str:
    """从投票者输出中提取明确的选择/立场。

    策略：查找关键词后的内容，取第一段。
    """
    import re
    # 匹配 "结论/选择/推荐/投票: ..." 或 "支持/赞同/推荐 XXX"
    patterns = [
        r'(?:结论|选择|推荐|投票|最终决定)\s*[：:]\s*(.+?)(?:[。\n]|$)',
        r'(?:支持|赞同|推荐|选择)\s*[：:]*\s*["""]?(.+?)[""」]?(?:[。\n,，]|$)',
        r'(?:最佳|最优|首选)\s*(?:方案|选项|是)\s*[：:]*\s*(.+?)(?:[。\n]|$)',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()[:50]
    return ""


def _normalize_choice(choice: str) -> str:
    """归一化投票选择：去前缀修饰。"""
    c = choice.strip().strip('"""\'「」""')
    for prefix in ["支持", "赞同", "推荐", "选择", "认为"]:
        if c.startswith(prefix):
            c = c[len(prefix):].strip("：: ")
    return c or choice[:40]


def _merge_similar_choices(votes: dict[str, list[str]]) -> dict[str, list[str]]:
    """合并相似的投票选择（如 "方案A" 和 "方案A更优"）。"""
    keys = sorted(votes.keys(), key=len)  # 短键优先
    merged: dict[str, list[str]] = {}
    consumed: set[str] = set()

    for short_key in keys:
        if short_key in consumed:
            continue
        merged[short_key] = list(votes[short_key])
        consumed.add(short_key)
        # 查找以此为前缀的更长的键并合并
        for long_key in keys:
            if long_key in consumed:
                continue
            if long_key.startswith(short_key):
                merged[short_key].extend(votes[long_key])
                consumed.add(long_key)

    return merged


class PlanExecutor(BaseExecutor):
    def __init__(
        self,
        session_id: str = "default",
        llm_model: Optional[Any] = None,
        workspace_id: Optional[int] = None,
    ):
        super().__init__(session_id, llm_model)
        self.workspace_id = workspace_id
        self._tools_cache: Dict[str, tuple] = {}  # 实际存 (tools, skill_index_text, skill_ids, kb_stats) 四元组
        self._subagent_config_cache: Dict[str, Dict[str, Any]] = {}
        self._direct_agent_config: Optional[Dict[str, Any]] = None
        self._original_messages: List[BaseMessage] = []
        self._response_mode: Optional[str] = None
        self._mode_suffix: Optional[str] = None
        self._langgraph_executor: Optional[LangGraphTaskExecutor] = None
        self._use_langgraph: bool = get_config('agent.execution.type', 'legacy') == 'langgraph'
        self._use_workflow: bool = get_config('agent.execution.use_workflow', True) and WORKFLOW_AVAILABLE
        self._adapter: Optional[Any] = None
        self._perf_logger: Optional[Any] = None
        if self._use_langgraph and LANGGRAPH_AVAILABLE:
            self._init_langgraph_executor()
        elif self._use_langgraph:
            logger.warning("[PlanExecutor]  LangGraph legacy ")
            self._use_langgraph = False
        if self._use_workflow and WORKFLOW_AVAILABLE and self._langgraph_executor:
            self._init_adapter()
        elif self._use_workflow:
            logger.warning("[PlanExecutor] ")
            self._use_workflow = False
    def _init_langgraph_executor(self):
        """复用模块级单例 LangGraphTaskExecutor（图缓存跨 execute/dispatch 共享）。

        注意：原实现传 enable_parallel_tools=...，但 LangGraphTaskExecutor.__init__
        无此参数 → TypeError 被下方 except 吞掉 → _use_langgraph/_use_workflow 全 False
        → planning 模式抛 RuntimeError。parallel_tool 行为由 LLM model_kwargs 控制，
        与本参数无关，故直接删除。
        """
        try:
            from executor.langgraph import get_langgraph_executor
            self._langgraph_executor = get_langgraph_executor()
            logger.info("[PlanExecutor] LangGraph executor (singleton)")
        except Exception as e:
            logger.error(f"[PlanExecutor] LangGraph init failed, fallback: {e}")
            self._use_langgraph = False
            self._langgraph_executor = None
    def _init_adapter(self):
        """B-4: 替代 _init_workflow_executors——只创建 adapter，不再实例化旧 executor。

        使用 create_workflow_adapter：默认返回本地 LangGraphWorkflowAdapter（零行为变更），
        当 config agent.execution.remote_a2a.endpoints 命中 task.agent 时启用远程 A2A（预留）。
        """
        try:
            self._adapter = create_workflow_adapter(
                langgraph_executor=self._langgraph_executor,
                subagent_getter=self._get_subagent_config_async,
                tools_getter=self._get_subagent_tools,
                llm_model=self.llm_model,
                response_mode_getter=lambda: self._response_mode,
                messages_getter=lambda: self._original_messages,
            )
            logger.info("[PlanExecutor] adapter initialized (StateGraphBuilder path)")
        except Exception as e:
            logger.error(f"[PlanExecutor] adapter init failed: {e}")
            self._use_workflow = False
            self._adapter = None
    def set_response_mode(self, response_mode: Optional[str]):
        self._response_mode = response_mode
        if response_mode:
            self._mode_suffix = get_mode_prompt_suffix(response_mode)
            if self._mode_suffix:
                logger.info(f"[PlanExecutor]  response_mode: {response_mode},  mode_suffix")
        else:
            self._mode_suffix = None

    @staticmethod
    def _extract_kb_context(messages: List[BaseMessage]) -> str:
        """从消息列表中提取 KB 上下文（【参考知识库】SystemMessage）。"""
        from langchain_core.messages import SystemMessage
        parts = []
        for m in (messages or []):
            if isinstance(m, SystemMessage) and '参考知识库' in str(m.content):
                parts.append(str(m.content))
        return '\n\n'.join(parts) if parts else ''

    async def _get_subagent_config_async(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """P2-10: async 版本，用 to_thread 包装同步 DB 查询，避免阻塞事件循环。

        供 adapter 在 async 上下文优先调用（iscoroutinefunction 判断后 await）。
        """
        if self._direct_agent_config and self._direct_agent_config.get('agent_name') == agent_name:
            self._subagent_config_cache[agent_name] = self._direct_agent_config
            return self._direct_agent_config
        if agent_name not in self._subagent_config_cache:
            config_db = get_config_db()
            # 同步 DB 调用卸载到线程池
            config = await asyncio.to_thread(config_db.subagents.get_by_name, agent_name)
            if config:
                self._subagent_config_cache[agent_name] = config
                logger.debug(f"[PlanExecutor] async 加载 SubAgent 配置: {agent_name}")
        return self._subagent_config_cache.get(agent_name)
    async def _get_subagent_tools(self, agent_name: str, subagent_config: Dict[str, Any]) -> tuple:
        if agent_name not in self._tools_cache:
            agent_pr_key_id = subagent_config.get('pr_key_id')
            tools, skill_index_text, skill_ids, kb_stats = await collect_subagent_tools_async(
                subagent_config, agent_pr_key_id, return_skill_ids=True, return_kb_stats=True
            )
            self._tools_cache[agent_name] = (tools, skill_index_text, skill_ids, kb_stats)
            logger.info(
                f"[PlanExecutor] agent={agent_name}: tools={len(tools)}, "
                f"skills={len(skill_ids)}, structured_kb={kb_stats['structured']}, "
                f"unstructured_kb={kb_stats['unstructured']}, agent_pr_key_id={agent_pr_key_id}"
            )
        return self._tools_cache[agent_name]
    async def _prepare_plan(
        self,
        messages: List[BaseMessage],
        user_input: str,
        agent_name: Optional[str],
        agent_config: Optional[Dict[str, Any]],
        response_mode: Optional[str],
        memory_context: Optional[str],
        deep_thinking: bool
    ) -> ExecutionPlan:
        """提取 execute() 与 execute_stream() 中重复的计划准备逻辑。

        Returns: ExecutionPlan（AGENT 直连模式或 LLM 规划模式）。"""
        self._original_messages = messages
        # 提取 KB 上下文 SystemMessage（如 kb_refs 生成的【参考知识库】），
        # 注入到 user_input，否则 planning 模式下 task 执行时丢失引用片段
        kb_context = self._extract_kb_context(messages)
        if kb_context:
            user_input = f"{kb_context}\n\n{user_input}"
            logger.info(f"[PlanExecutor] 注入 KB 上下文到 user_input (长度: {len(kb_context)})")
        self.set_response_mode(response_mode)
        self._direct_agent_config = agent_config
        if agent_name and agent_name.lower() != 'default':
            plan = ExecutionPlan(
                mode=PlanMode.AGENT,
                tasks=[TaskNode(id="direct_agent", agent=agent_name, description=user_input)],
                original_query=user_input
            )
            logger.info(f"[PlanExecutor]  agent={agent_name}")
        else:
            plan = await self._generate_plan(
                user_input, messages,
                deep_thinking=deep_thinking,
                response_mode=response_mode,
                memory_context=memory_context
            )
        return plan

    async def execute(
        self,
        messages: List[BaseMessage],
        **kwargs
    ) -> List[BaseMessage]:
        user_input = self._extract_user_input(messages)
        deep_thinking = kwargs.get('deep_thinking', False)
        plan = await self._prepare_plan(
            messages=messages,
            user_input=user_input,
            agent_name=kwargs.get('agent'),
            agent_config=kwargs.get('agent_config'),
            response_mode=kwargs.get('response_mode'),
            memory_context=kwargs.get('memory_context'),
            deep_thinking=deep_thinking
        )
        context = {}
        context_health = {}
        execution_error: Optional[str] = None
        # P1-2: 捕获工作流执行错误，不再静默吞掉；反映到 metadata 供调用方感知
        try:
            async for _ in self._execute_plan(plan, context_out=context, context_health_out=context_health, deep_thinking=deep_thinking):
                pass
        except Exception as e:
            logger.error(f"[PlanExecutor] execute() 工作流执行失败: {e}", exc_info=True)
            execution_error = str(e)
        final_response = await self._summarize_results(plan, context, context_health)
        summary = self._calculate_summary(plan, context)
        # 失败时若 final 为空，给出明确错误而非空回复
        if execution_error and not final_response:
            final_response = f"工作流执行失败：{execution_error}"
        metadata = {
            "workflow_tasks": [
                {
                    **(task.model_dump() if hasattr(task, 'model_dump') else task.dict()), 
                    "status": context.get(task.id, {}).get('status', 'completed') if isinstance(context.get(task.id), dict) else ('completed' if task.id in context else 'pending'),
                    "result": context.get(task.id) if isinstance(context.get(task.id), str) else (context.get(task.id, {}).get('output') if isinstance(context.get(task.id), dict) else "")
                } for task in plan.tasks
            ],
            "workflow_mode": plan.mode.value if hasattr(plan.mode, 'value') else str(plan.mode),
            "workflow_summary": summary,
        }
        if execution_error:
            metadata["error"] = execution_error
            metadata["success"] = False
        return [AIMessage(content=final_response, response_metadata=metadata)]
    def _calculate_summary(self, plan: ExecutionPlan, context: Dict[str, Any]) -> Dict[str, Any]:
        success_count = len([t for t in plan.tasks if t.id in context and not is_error_result(context[t.id])])
        return {
            'total_tasks': len(plan.tasks),
            'completed': success_count,
            'failed': len(plan.tasks) - success_count,
            'success_rate': int(success_count / len(plan.tasks) * 100) if plan.tasks else 0,
            'total_duration': 0
        }
    def _should_skip_final(self, content_streamed: bool, plan: ExecutionPlan) -> bool:
        """是否跳过 final_response 的流式补发（P2-14 修复重复回复）。

        - 未流式输出 → 必须发 final（不 skip）
        - AGENT/SEQUENTIAL/DAG 且已流式 → final 是同一 task 原文，skip
        - PARALLEL + auto_summary → final 是 LLM 汇总（新内容），不 skip
        - PARALLEL 非 auto_summary → final 是各 task 原文拼接，已流式，skip
        - DIRECT → 无流式输出，不 skip
        """
        if not content_streamed:
            return False
        if plan.mode == PlanMode.PARALLEL:
            return not getattr(plan, 'auto_summary', False)
        return plan.mode in (PlanMode.AGENT, PlanMode.SEQUENTIAL, PlanMode.DAG)
    def _is_dynamic_step_failed(self, result: Optional[str]) -> bool:
        """DYNAMIC 单步结果是否判定失败（P2-25 短路，避免空转烧 LLM）。

        空结果或 error: 前缀视为失败，应终止迭代而非回灌 planner。
        """
        if not result or not str(result).strip():
            return True
        return is_error_result(result)
    @staticmethod
    def _derive_round_thread_id(base_thread_id: str, replan_round: int, loop_round: int) -> str:
        """P2-11: 派生每轮独立 thread_id，避免 replan/loop 跨轮 checkpoint 污染。

        首轮（replan=0 且 loop=0）保持原 thread_id，与历史行为一致；
        后续轮次附加 #r{replan}-l{loop} 后缀，使 LangGraph 视为新会话从 initial_state 开始。
        """
        if replan_round == 0 and loop_round == 0:
            return base_thread_id
        return f"{base_thread_id}#r{replan_round}-l{loop_round}"
    async def execute_stream(
        self,
        messages: List[BaseMessage],
        event_sender: Optional[Any] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        from utils.logging.performance_logger import PerformanceLogger
        total_start = time.time()
        self._perf_logger = PerformanceLogger(self.session_id)
        user_input = self._extract_user_input(messages)
        deep_thinking = kwargs.get('deep_thinking', False)
        yield StreamResponseHelper.send_config()
        yield StreamResponseHelper.send_started()
        # P2-6: _prepare_plan 含 LLM 规划调用，须纳入 try，失败发统一 error 事件
        try:
            plan = await self._prepare_plan(
                messages=messages,
                user_input=user_input,
                agent_name=kwargs.get('agent'),
                agent_config=kwargs.get('agent_config'),
                response_mode=kwargs.get('response_mode'),
                memory_context=kwargs.get('memory_context'),
                deep_thinking=deep_thinking
            )
            if self._perf_logger:
                self._perf_logger.set_execution_mode(plan.mode.value, len(plan.tasks))
            mode_labels = {
                PlanMode.SEQUENTIAL: "顺序",
                PlanMode.PARALLEL: "并行",
                PlanMode.DAG: "DAG",
                PlanMode.AGENT: "直连Agent",
                PlanMode.DIRECT: "直接回复",
                PlanMode.DEBATE: "辩论对抗",
                PlanMode.VOTE: "共识投票",
            }
            friendly_mode = mode_labels.get(plan.mode, str(plan.mode))
            task_summaries = []
            for i, t in enumerate(plan.tasks, 1):
                desc = t.description if len(t.description) <= _DESC_PREVIEW_LEN else t.description[:_DESC_PREVIEW_LEN - 3] + "..."
                task_summaries.append(f"  {i}. [{t.agent}] {desc}")
            summary_text = "\n".join(task_summaries)
            yield StreamResponseHelper.send_thinking(f"模式: {friendly_mode}，共 {len(plan.tasks)} 个任务\n{summary_text}")
            if event_sender:
                yield event_sender.send_workflow_planning(plan, self.session_id)
            execution_start = time.time()
            context = {}
            context_health = {}
            async for chunk in self._execute_plan(plan, event_sender, context_out=context, context_health_out=context_health, deep_thinking=deep_thinking):
                yield chunk
            # R3: 不再对已序列化 SSE 做字符串嗅探 '"content_chunk"' in chunk（脆弱，字段名/顺序变即失效）；
            # 改由 _execute_with_workflow 在 content_chunk 分支设置 context['_content_streamed'] 标志位。
            content_streamed = bool(context.get('_content_streamed', False))
            execution_duration = time.time() - execution_start
            self._perf_logger.log_execution_end()
            self._perf_logger.log_summarize_start()
            summarize_start = time.time()
            final_response = await self._summarize_results(plan, context, context_health)
            summarize_duration = time.time() - summarize_start
            self._perf_logger.log_summarize_end(summarize_duration)
            # P2-14: skip_final 逻辑下沉到 _should_skip_final，修复 PARALLEL 非 auto_summary 重复输出
            skip_final = self._should_skip_final(content_streamed, plan)
            if not skip_final:
                async for chunk in StreamResponseHelper.send_content_chunks(final_response):
                    yield chunk
            yield StreamResponseHelper.send_done()
            total_duration = time.time() - total_start
            self._perf_logger.finalize()
        except Exception as e:
            logger.error(f"[PlanExecutor] : {e}", exc_info=True)
            yield StreamResponseHelper.send_error(str(e))
    async def _generate_plan(self, user_input: str, messages: List[BaseMessage], deep_thinking: bool = False, response_mode: Optional[str] = None, memory_context: Optional[str] = None) -> ExecutionPlan:
        config_db = get_config_db()
        subagents = config_db.subagents.get_all(enabled_only=True) or []
        history = extract_session_history(messages)
        if memory_context:
            if history:
                history = f":\n{memory_context}\n\n{history}"
            else:
                history = f":\n{memory_context}"
            logger.info(f"[PlanExecutor] ")
        disable_thinking = get_config('agent.planner.disable_thinking', False)
        if disable_thinking:
            logger.info("[PlanExecutor] Planner  /no_think")
        logger.info(f"[PlanExecutor]  (deep_thinking={deep_thinking}, disable_thinking={disable_thinking}, response_mode={response_mode})...")
        return await generate_execution_plan(
            user_input=user_input,
            subagents=subagents,
            session_history=history,
            llm_model=self.llm_model,
            disable_thinking=disable_thinking,
            response_mode=response_mode
        )
    async def _execute_plan(
        self,
        plan: ExecutionPlan,
        event_sender: Optional[Any] = None,
        context_out: Dict[str, str] = None,
        context_health_out: Dict[str, dict] = None,
        deep_thinking: bool = False
    ) -> AsyncGenerator[str, None]:
        plan_start = time.time()
        if self._perf_logger:
            self._perf_logger.log_execution_start()
        logger.info(f"[PlanExecutor] : {plan.mode}, : {len(plan.tasks)}, deep_thinking={deep_thinking}, use_workflow={self._use_workflow}")
        context = context_out if context_out is not None else {}
        context_health = context_health_out if context_health_out is not None else {}
        if event_sender:
            yield event_sender.send_execution_start(plan.mode.value)
        if plan.mode == PlanMode.DIRECT:
            if plan.direct_response:
                context["direct_response"] = plan.direct_response
                logger.info("[PlanExecutor] DIRECT ")
            else:
                logger.warning("[PlanExecutor] DIRECT  direct_response LLM ")
                try:
                    direct_response = await self._generate_direct_response(plan.original_query)
                    context["direct_response"] = direct_response
                    logger.info(f"[PlanExecutor] LLM : {direct_response[:50]}...")
                except Exception as e:
                    logger.error(f"[PlanExecutor] LLM : {e}")
                    context["direct_response"] = ""
            return
        if plan.mode == PlanMode.DYNAMIC:
            async for event in self._execute_dynamic(plan, context, event_sender, deep_thinking, context_health):
                yield event
            return
        if plan.mode == PlanMode.DEBATE:
            logger.info("[PlanExecutor] DEBATE 模式，开始辩论对抗")
            async for event in self._execute_debate(plan, context, event_sender, deep_thinking, context_health):
                yield event
            return
        if plan.mode == PlanMode.VOTE:
            logger.info(f"[PlanExecutor] VOTE 模式，{len(plan.tasks)} 个投票者")
            async for event in self._execute_vote(plan, context, event_sender, deep_thinking, context_health):
                yield event
            return
        if plan.mode == PlanMode.AGENT:
            if not plan.tasks:
                raise ValueError("AGENT 模式要求至少 1 个 task")
            task = plan.tasks[0]
            async for event in self._execute_agent_mode(task, plan, context, event_sender, deep_thinking=deep_thinking, context_health=context_health):
                yield event
            return
        if self._use_workflow:
            async for event in self._execute_with_workflow(plan, context, event_sender, deep_thinking, context_health):
                yield event
        else:
            raise RuntimeError(
                f"Workflow executor not available for mode '{plan.mode.value}'. "
                f"Check configuration (agent.execution.use_workflow) and ensure LangGraph is installed."
            )
        if event_sender:
            summary = self._calculate_summary(plan, context)
            yield event_sender.send_workflow_summary(summary)
            yield event_sender.send_execution_complete(summary)
        plan_duration = time.time() - plan_start
        logger.info(f"[PlanExecutor] ⏱️ : {plan_duration:.2f}")

    async def _replan(self, trigger_task, trigger_result: str, plan: ExecutionPlan, context: dict) -> Optional[ExecutionPlan]:
        """调 LLM 重规划（委托共享 replan 模块，保留 4 参签名以兼容单测 mock）。"""
        from executor.workflow.replan import replan as _replan_fn
        return await _replan_fn(trigger_task, trigger_result, self.llm_model)

    async def _build_plan_review_event(self, plan: ExecutionPlan, context: dict) -> str:
        """构建 plan_review SSE 事件（spec §5.3，人工审核 pause 时 yield）。

        携带 agent_cards（每 task 的 agent 能力卡：name/desc/tools/mcp），
        供前端 PlanReviewDialog 用 AgentCard 展示选中的 agent。
        返回 SSE 字符串（data: {json}\\n\\n），而非 raw dict——修复前端收不到 plan_review 的根因。
        R2: 改为 async，_build_agent_cards 内部用 _get_subagent_config_async 避免同步 DB 阻塞。
        """
        from utils.sse import build_sse_event
        from .stream_helper import send_sse_data
        return send_sse_data(build_sse_event(
            "plan_review",
            dispatch_id=self.session_id or "default",
            plan=plan.to_dict(),
            results={k: v for k, v in context.items() if not k.startswith("_")},
            options=["approve", "modify", "reject"],
            agent_cards=await self._build_agent_cards(plan),
        ))

    async def _build_agent_cards(self, plan: ExecutionPlan) -> list:
        """为 plan 的每个 task 构建 agent 能力卡（供前端 AgentCard 展示）。

        R2: 用 _get_subagent_config_async（asyncio.to_thread 包装 DB）取 agent 配置，
        避免在流式路径中同步阻塞事件循环。
        """
        cards = []
        for t in plan.tasks:
            cfg = await self._get_subagent_config_async(t.agent) or {}
            cards.append({
                "agent_name": t.agent,
                "agent_description": cfg.get("agent_description", ""),
                "tools": cfg.get("tools", []) or [],
                "mcp_tools": cfg.get("mcp_tools", []) or [],
                "external_tools": cfg.get("external_tools", []) or [],
                "is_public": cfg.get("is_public"),
                "task_id": t.id,
                "task_description": t.description,
                "dependencies": t.dependencies or [],
            })
        return cards

    async def _execute_with_workflow(
        self,
        plan: ExecutionPlan,
        context: Dict[str, Any],
        event_sender: Optional[Any],
        deep_thinking: bool,
        context_health: Dict[str, dict] = None,
    ) -> AsyncGenerator[str, None]:
        """B-2: 迁移到 StateGraphBuilder + stream_mode="stream"。

        消费 astream(stream_mode=["updates","custom"])：
        - custom: adapter 事件（CONTENT_CHUNK/tool_call/TASK_STARTED/...）→ SSE 翻译
        - updates: task 最终结果 → context 传递
        """
        from executor.workflow.stategraph_builder import StateGraphBuilder
        from langgraph.checkpoint.memory import MemorySaver
        from utils.config import get_config

        if context_health is None:
            context_health = {}
        logger.info(f"[PlanExecutor] StateGraphBuilder mode: {plan.mode.value}")

        max_concurrency = get_config("agent.execution.parallel_tasks.max_concurrency", 5)
        semaphore = asyncio.Semaphore(max_concurrency)
        from utils.checkpoint import MysqlSaverFactory
        checkpointer = await MysqlSaverFactory.get_saver() or MemorySaver()

        builder = StateGraphBuilder(adapter=self._adapter, checkpointer=checkpointer)
        agent_rate_limits = get_config("agent.execution.parallel_tasks.rate_limits", {})
        graph = builder.build(
            plan=plan, semaphore=semaphore,
            deep_thinking=deep_thinking, stream_mode="stream",
            agent_rate_limits=agent_rate_limits,
        )
        from utils.observability import attach_callbacks
        config = attach_callbacks({
            "configurable": {"thread_id": self.session_id or "default"},
            "max_concurrency": max_concurrency,
        }, session_id=self.session_id or "default")

        # 动态重规划：max_replan_rounds（0=禁用，默认 3）
        max_replan_rounds = get_config("agent.execution.replan.max_rounds", 3)
        max_loop = get_config("agent.execution.replan.max_loop", 3)
        # A1：共享 WorkflowRunner 推进 replan/loop 轮次（消除与 dispatch 的编排重复 +
        # 修复 dispatch 缺 replan_round 上限的潜在无限重规划）
        from executor.workflow.runner import WorkflowRunner
        runner = WorkflowRunner(
            builder, semaphore,
            build_kwargs={"deep_thinking": deep_thinking, "stream_mode": "stream",
                          "agent_rate_limits": agent_rate_limits},
            max_replan_rounds=max_replan_rounds, max_loop=max_loop,
            llm_model=getattr(self, "llm_model", None),
            context_health=context_health, replan_fn=self._replan,
        )
        replan_round = 0
        loop_round = 0
        initial_state = {"results": {}, "errors": {}, "artifacts": {}, "blackboard": {}}
        _base_thread_id = self.session_id or "default"

        while True:
            # P2-11: replan/loop 多轮复用同一 thread_id 会使 LangGraph 从上轮 checkpoint 续接，
            # 与 runner 给的 initial_state（replan seed 旧结果 / loop fresh）合并导致跨轮状态污染。
            # 状态连续性由 initial_state 承载（见下方注释），故每轮派生独立 thread_id。
            _round_thread_id = self._derive_round_thread_id(_base_thread_id, replan_round, loop_round)
            config["configurable"]["thread_id"] = _round_thread_id
            try:
                async for event in graph.astream(
                    initial_state, config=config,
                    stream_mode=["updates", "custom"],
                ):
                    mode, data = event
                    if mode == "custom":
                        # custom stream: {"task_id": ..., "event": ExecutionEvent}
                        task_id = (data or {}).get("task_id")
                        adapter_event = (data or {}).get("event")
                        if adapter_event is None:
                            continue
                        ev_type = getattr(adapter_event, "type", None)
                        ev_data = getattr(adapter_event, "data", None)
                        ev_metadata = getattr(adapter_event, "metadata", {}) or {}

                        # 翻译 adapter event → SSE
                        ev_type_str = ev_type.value if hasattr(ev_type, "value") else str(ev_type)

                        if ev_type_str == "task_started":
                            task_node = next((t for t in plan.tasks if t.id == task_id), None)
                            if event_sender:
                                if task_node:
                                    desc = task_node.description if len(task_node.description) <= _DESC_PREVIEW_LEN_WIDE else task_node.description[:_DESC_PREVIEW_LEN_WIDE - 3] + "..."
                                    yield StreamResponseHelper.send_thinking(f" [{task_node.agent}]: {desc}")
                                else:
                                    yield StreamResponseHelper.send_thinking(f"task_id: {task_id}")
                            # 发送 execution_event 给前端时间轴
                            yield _send_execution_event('task_started',
                                {'task_id': task_id, 'parent_id': None},
                                {'task_id': task_id,
                                 'task_name': task_node.description if task_node else task_id,
                                 'agent': task_node.agent if task_node else ''})
                            if self._perf_logger and task_id:
                                task_node = next((t for t in plan.tasks if t.id == task_id), None)
                                if task_node:
                                    self._perf_logger.log_task_start(task_id, task_node.agent)

                        elif ev_type_str == "content_chunk":
                            # B-2 新增：CONTENT_CHUNK → content SSE（旧 PlanExecutor 忽略，迁移后产出 token 级）
                            # R3: 在 context 设标志位，供 execute_stream 判断是否已流式输出（替代字符串嗅探）
                            if ev_data:
                                context['_content_streamed'] = True
                                async for chunk in StreamResponseHelper.send_content_chunks(ev_data):
                                    yield chunk

                        elif ev_type_str == "task_completed":
                            result = ev_data.get("result", "") if isinstance(ev_data, dict) else ""
                            context[task_id] = result
                            # P2 修复：提取 tool_health 写入 context_health，激活降级健康追踪。
                            tool_health = ev_metadata.get("tool_health")
                            if tool_health and task_id:
                                context_health[task_id] = tool_health
                            # 发送 execution_event 给前端时间轴
                            duration = ev_metadata.get("duration", 0) if isinstance(ev_metadata, dict) else 0
                            yield _send_execution_event('task_completed',
                                {'task_id': task_id, 'parent_id': None},
                                {'task_id': task_id, 'status': 'done',
                                 'output': str(result)[:200] if result else '',
                                 'duration': round(duration, 1) if duration else None})
                            if self._perf_logger and task_id:
                                self._perf_logger.log_task_end(task_id, success=True)

                        elif ev_type_str == "task_failed":
                            error = ev_metadata.get("error", "")
                            # 发送 execution_event 给前端时间轴
                            duration = ev_metadata.get("duration", 0) if isinstance(ev_metadata, dict) else 0
                            yield _send_execution_event('task_failed',
                                {'task_id': task_id, 'parent_id': None},
                                {'task_id': task_id, 'status': 'failed',
                                 'error': str(error)[:200] if error else '',
                                 'duration': round(duration, 1) if duration else None})
                            if self._perf_logger and task_id:
                                self._perf_logger.log_task_end(task_id, success=False, error=str(error))
                            if event_sender:
                                yield StreamResponseHelper.send_thinking(f" : {error}")

                        elif ev_type_str == "tool_call":
                            if event_sender:
                                tool_calls_data = ev_data.get("tool_calls", []) if isinstance(ev_data, dict) else []
                                task_node = next((t for t in plan.tasks if t.id == task_id), None)
                                agent_name = task_node.agent if task_node else ""
                                for tc in tool_calls_data:
                                    tool_name = tc.get("name", "unknown")
                                    tool_args = tc.get("args", {})
                                    tdata = {'tool_name': tool_name, 'input': tool_args}
                                    if agent_name:
                                        tdata['agent_name'] = agent_name
                                    tmeta = {'run_id': tc.get("id", task_id or ""), 'parent_id': task_id}
                                    yield _send_execution_event('tool_start', tmeta, tdata)

                        elif ev_type_str == "message":
                            if self._perf_logger and task_id:
                                self._perf_logger.log_llm_call(
                                    model="unknown", duration=0,
                                    response_length=len(ev_data) if isinstance(ev_data, str) else 0,
                                    task_id=task_id,
                                )

                    elif mode == "updates":
                        # updates: task 最终结果（兜底 context 传递）
                        for _node, output in (data or {}).items():
                            if isinstance(output, dict) and "results" in output:
                                for tid, result in output["results"].items():
                                    if tid not in context:
                                        context[tid] = result

                # 人工审核检查（第三期，human_approval=true 时 pause 等审核）
                human_approval = get_config("agent.execution.replan.human_approval", False)
                # P2-8: 审核门控不应与 replan_round 挂钩（二者无逻辑关联）；
                # 改为首轮（replan_round==0）才暂停审核，避免无限审核循环。
                if human_approval and replan_round == 0:
                    from utils.review.registry import ReviewRegistry
                    review_id = self.session_id or "default"
                    review_timeout = get_config("agent.execution.replan.human_approval_timeout", 300)
                    yield await self._build_plan_review_event(plan, context)
                    logger.info(f"[PlanExecutor] 人工审核 pause，等待 {review_id} 审核")
                    # P2-7: try/finally 保证 register 必被 remove，避免异常/取消时注册表泄漏
                    try:
                        ReviewRegistry.register(review_id)
                        review_result = await ReviewRegistry.await_review(review_id, review_timeout)
                    finally:
                        ReviewRegistry.remove(review_id)
                    action = (review_result or {}).get("action", "reject")
                    if action == "reject":
                        logger.info("[PlanExecutor] 用户拒绝，终止执行")
                        break
                    elif action == "modify":
                        modified = (review_result or {}).get("modified_plan")
                        if modified:
                            try:
                                plan = ExecutionPlan(**modified)
                                replan_round += 1
                                graph = builder.build(plan=plan, semaphore=semaphore,
                                    deep_thinking=deep_thinking, stream_mode="stream",
                                    agent_rate_limits=agent_rate_limits)
                                logger.info("[PlanExecutor] 用户修改 plan，重建图继续")
                            except Exception as e:
                                logger.warning(f"[PlanExecutor] modified_plan 无效: {e}，用原 plan 继续")
                        continue
                    # approve: 继续 while（下一轮 astream / loop / replan / 结束）
                # A1：轮次决策下沉到 WorkflowRunner（loop/replan/done + 重建 + 计数）
                decision = await runner.advance(
                    plan, context, loop_round=loop_round, replan_round=replan_round)
                if decision.action == "done":
                    break  # 无需循环/重规划
                plan = decision.plan
                graph = decision.new_graph
                loop_round = decision.loop_round
                replan_round = decision.replan_round
                # A6：用 runner 给的 initial_state（replan seed 旧结果 / loop fresh）
                initial_state = decision.initial_state
                continue
            except Exception as e:
                logger.error(f"[PlanExecutor] StateGraphBuilder error: {e}", exc_info=True)
                if event_sender:
                    yield StreamResponseHelper.send_error(str(e))
                return
    async def _execute_agent_mode(
        self,
        task: TaskNode,
        plan: ExecutionPlan,
        context: Dict[str, str],
        event_sender: Optional[Any] = None,
        deep_thinking: bool = False,
        context_health: Dict[str, dict] = None,
    ) -> AsyncGenerator[str, None]:
        logger.info(f"[PlanExecutor]  AGENT : {task.agent}, deep_thinking={deep_thinking}")
        if not self._use_workflow:
            raise RuntimeError(
                f"Workflow executor not available for AGENT mode. "
                f"Check configuration (agent.execution.use_workflow)."
            )
        async for event in self._execute_with_workflow(plan, context, event_sender, deep_thinking, context_health):
            yield event
    def _get_last_task(self, plan: ExecutionPlan, context: Dict[str, str]) -> Optional[TaskNode]:
        if not plan.tasks:
            return None
        if plan.mode in (PlanMode.SEQUENTIAL, PlanMode.PARALLEL):
            return plan.tasks[-1]
        if plan.mode == PlanMode.DAG:
            all_task_ids = {t.id for t in plan.tasks}
            has_dependent = set()
            for task in plan.tasks:
                has_dependent.update(task.dependencies)
            leaf_task_ids = all_task_ids - has_dependent
            for task in reversed(plan.tasks):
                if task.id in leaf_task_ids and task.id in context:
                    logger.debug(f"[_get_last_task] DAG: {task.id}")
                    return task
            return plan.tasks[-1]
        return None

    async def _execute_dynamic(
        self,
        plan: ExecutionPlan,
        context: Dict[str, str],
        event_sender: Optional[Any],
        deep_thinking: bool,
        context_health: Dict[str, dict],
    ) -> AsyncGenerator[str, None]:
        """DYNAMIC 模式：迭代规划（plan 1 task → execute → observe → plan next）。

        初始 plan 含 1 task → _execute_with_workflow 执行 → 结果回灌 planner →
        规划下一步或 DIRECT 最终回复 → 重复，直到 DIRECT 或 max_dynamic_steps。
        每步复用 _execute_with_workflow（含 astream + SSE 翻译 + runner）。
        """
        max_steps = int(get_config("agent.planner.max_dynamic_steps", 5))
        step = 0
        current_plan = plan
        logger.info(f"[PlanExecutor] DYNAMIC 迭代规划开始，max_steps={max_steps}")

        while step < max_steps:
            if not current_plan.tasks:
                logger.warning("[PlanExecutor] DYNAMIC: planner 未输出 task，终止")
                break
            # 执行当前单 task plan（复用 _execute_with_workflow）
            async for event in self._execute_with_workflow(
                current_plan, context, event_sender, deep_thinking, context_health
            ):
                yield event
            # 取结果
            task = current_plan.tasks[0]
            result = context.get(task.id, "")
            step += 1
            logger.info(f"[PlanExecutor] DYNAMIC step {step} done: task={task.id}, result_len={len(result)}")
            # P2-25: 失败短路——空结果或 error: 前缀直接终止，避免空转烧 LLM
            if self._is_dynamic_step_failed(result):
                logger.warning(
                    f"[PlanExecutor] DYNAMIC step {step} 失败（result 空或 error），终止迭代: "
                    f"task={task.id}, result={(result or '')[:200]}"
                )
                break
            # 回灌 planner 规划下一步
            next_plan = await self._plan_next_step(plan.original_query, task, result, step)
            if next_plan.mode == PlanMode.DIRECT:
                context["direct_response"] = next_plan.direct_response or ""
                logger.info(f"[PlanExecutor] DYNAMIC: planner 给出最终回复，结束（step={step}）")
                break
            if not next_plan.tasks:
                logger.warning("[PlanExecutor] DYNAMIC: planner 未输出 task，终止")
                break
            current_plan = next_plan
        else:
            logger.warning(f"[PlanExecutor] DYNAMIC: 达 max_steps={max_steps}，强制终止")

    async def _plan_next_step(
        self,
        original_query: str,
        prev_task: TaskNode,
        prev_result: str,
        step: int,
    ) -> ExecutionPlan:
        """DYNAMIC：把上一步结果回灌 planner，生成下一个 task 或最终回复。"""
        from utils.planning.generator import generate_execution_plan
        from utils.config import get_config_db
        subagents = get_config_db().subagents.get_all(enabled_only=True) or []
        prompt = (
            f"上一步 [{prev_task.id}]（agent={prev_task.agent}）的结果：\n"
            f"{prev_result[:1500]}\n\n"
            f"原始请求：{original_query}\n\n"
            f"请规划下一步（输出 1 个 task，mode 用 dynamic 或 agent），"
            f"或如果已得到最终答案，用 direct 模式（direct_response 给出最终回复）。"
        )
        return await generate_execution_plan(
            user_input=prompt,
            subagents=subagents,
            llm_model=self.llm_model,
        )

    # ─── DEBATE 模式（专题对抗） ───

    async def _execute_debate(
        self,
        plan: ExecutionPlan,
        context: Dict[str, str],
        event_sender: Optional[Any],
        deep_thinking: bool,
        context_health: Dict[str, dict],
    ) -> AsyncGenerator[str, None]:
        """DEBATE 模式：多轮辩论对抗。

        轮1：执行 plan（正反方论证 + 裁判）→ 裁判判定是否收敛
        轮2（如需要）：replan → 补充论证 + 终裁
        收敛条件：裁判输出含"共识"/"一致"/"终裁"关键词，或达 max_rounds。
        """
        max_rounds = int(get_agent_config("agent.execution.debate.max_rounds", 2,
                                         workspace_id=self.workspace_id))
        current_plan = plan
        debate_history: list[str] = []

        for round_num in range(1, max_rounds + 1):
            logger.info(f"[DEBATE] 第 {round_num}/{max_rounds} 轮开始")

            # 执行本轮 plan
            async for event in self._execute_with_workflow(
                current_plan, context, event_sender, deep_thinking, context_health
            ):
                yield event

            # 收集裁判输出
            judge_id = current_plan.tasks[-1].id if current_plan.tasks else None
            judge_output = context.get(judge_id, "") if judge_id else ""
            debate_history.append(f"=== 第 {round_num} 轮 ===\n{judge_output}")

            # 收敛检测
            if self._debate_converged(judge_output, round_num):
                logger.info(f"[DEBATE] 第 {round_num} 轮已收敛，辩论结束")
                break

            # 未收敛 → replan 下一轮（补充论证）
            if round_num < max_rounds:
                next_plan = await self._replan_debate(
                    current_plan, context, debate_history, round_num
                )
                if next_plan and next_plan.tasks:
                    current_plan = next_plan
                else:
                    logger.warning("[DEBATE] replan 失败，终止辩论")
                    break
        else:
            logger.info(f"[DEBATE] 达最大轮数 {max_rounds}，辩论结束")

    @staticmethod
    def _debate_converged(judge_output: str, round_num: int) -> bool:
        """检测辩论是否已收敛。

        收敛标记：
        - 第1轮裁判已给出明确终裁结论
        - 裁判声明共识达成
        - 输出过短（说明已无新论据）
        - 第2轮强制收敛
        """
        if not judge_output or len(judge_output.strip()) < 20:
            return True
        if round_num >= 2:
            return True
        converged_keywords = [
            "终裁", "最终结论", "最终裁定", "裁定如下",
            "双方一致", "共识达成", "结论明确",
            "一致认为", "综合判断", "最终判定",
        ]
        return any(kw in judge_output for kw in converged_keywords)

    # ─── VOTE 模式（共识投票） ───

    async def _execute_vote(
        self,
        plan: ExecutionPlan,
        context: Dict[str, str],
        event_sender: Optional[Any],
        deep_thinking: bool,
        context_health: Dict[str, dict],
    ) -> AsyncGenerator[str, None]:
        """VOTE 模式：所有投票者并行执行 → 系统计票合成。"""
        # 1. 所有投票者并行执行
        async for event in self._execute_with_workflow(
            plan, context, event_sender, deep_thinking, context_health
        ):
            yield event

        # 2. 计票合成
        vote_result = self._synthesize_vote(plan, context)
        context["_vote_result"] = vote_result
        logger.info(f"[VOTE] 投票完成:\n{vote_result[:200]}")

    @staticmethod
    def _synthesize_vote(plan: ExecutionPlan, context: dict) -> str:
        """合成投票结果：提取每个投票者的立场，统计计数。"""
        import re

        votes: dict[str, list[str]] = {}
        uncategorized: list[str] = []

        for task in plan.tasks:
            output = context.get(task.id, "")
            if not output or is_error_result(output):
                votes.setdefault("弃权/错误", []).append(task.id)
                continue
            choice = _extract_vote_choice(output)
            if choice:
                normalized = _normalize_choice(choice)
                votes.setdefault(normalized, []).append(task.id)
            else:
                uncategorized.append(task.id)
                first = re.split(r'[。\n]', output)[0].strip()[:80]
                if first:
                    votes.setdefault(first, []).append(task.id)

        # 合并相似选择（如 "方案A" 和 "方案A更优" 合并为同一选项）
        votes = _merge_similar_choices(votes)

        lines = ["=== 投票结果 ==="]
        total = sum(len(v) for v in votes.values())
        sorted_votes = sorted(votes.items(), key=lambda x: len(x[1]), reverse=True)
        for i, (option, vids) in enumerate(sorted_votes):
            count = len(vids)
            lines.append(f"{i+1}. {option}: {count}票 ({count}/{total})")

        if sorted_votes:
            winner = sorted_votes[0]
            runner_up = sorted_votes[1] if len(sorted_votes) > 1 else None
            if runner_up and len(winner[1]) == len(runner_up[1]):
                lines.append(f"\n⚖️ 平局: {winner[0]} vs {runner_up[0]}")
            elif total > 0:
                majority = len(winner[1]) > total / 2
                label = "✅ 绝对多数胜出" if majority else "📊 相对多数领先"
                lines.append(f"\n{label}: {winner[0]}")

        return "\n".join(lines)

    async def _replan_debate(
        self,
        plan: ExecutionPlan,
        context: dict,
        debate_history: list[str],
        round_num: int,
    ) -> Optional[ExecutionPlan]:
        """辩论 replan：注入历史到 Planner，生成补充论证 plan。"""
        from utils.planning.generator import generate_execution_plan
        from utils.config import get_config_db

        subagents = get_config_db().subagents.get_all(enabled_only=True) or []
        history_text = "\n\n".join(debate_history[-3:])  # 最近3轮

        replan_prompt = (
            f"原始辩题：{plan.original_query}\n\n"
            f"=== 辩论历史 ===\n{history_text[:3000]}\n\n"
            f"请分析当前辩论状态。"
            f"如果裁判已给出明确终裁结论，用 direct 模式给出最终回复（direct_response）。"
            f"如果还需要补充论证，用 agent 模式输出 1~2 个 task（指定正方/反方 agent 做 rebuttal）。"
            f"最多 2 轮辩论（当前第 {round_num + 1} 轮）。"
        )
        try:
            return await generate_execution_plan(
                user_input=replan_prompt,
                subagents=subagents,
                llm_model=self.llm_model,
            )
        except Exception as e:
            logger.error(f"[DEBATE] replan 失败: {e}")
            return None

    def _is_synthesizer_task(self, plan: ExecutionPlan, context: dict) -> bool:
        """检测 plan 最后一个 task 是否为汇总 Agent。
        
        条件：
        - 至少 2 个 task
        - 最后 task 的 dependencies 覆盖所有前序 task id
        - PARALLEL 模式天然适合汇总（前序 task 无依赖关系）
        - SEQUENTIAL/DAG 需要依赖至少 2 个前序（排链式依赖伪汇总）
        """
        if not plan.tasks or len(plan.tasks) < 2:
            return False
        last = plan.tasks[-1]
        if not last.dependencies:
            return False
        other_ids = {t.id for t in plan.tasks[:-1]}
        if not other_ids.issubset(set(last.dependencies)):
            return False
        if plan.mode == PlanMode.PARALLEL:
            return True
        return len(last.dependencies) >= 2

    async def _summarize_results(self, plan: ExecutionPlan, context: Dict[str, str], context_health: Dict[str, dict] = None) -> str:
        if context_health is None:
            context_health = {}
        if plan.mode == PlanMode.DIRECT:
            return context.get("direct_response", "")
        # VOTE 模式：返回计票结果
        if plan.mode == PlanMode.VOTE and "_vote_result" in context:
            return context["_vote_result"]
        if not context:
            return ""
        if plan.mode == PlanMode.AGENT:
            last_task = plan.tasks[-1] if plan.tasks else None
            if last_task and last_task.id in context:
                return context[last_task.id]
            return list(context.values())[-1] if context else ""
        # 汇总 Agent 检测：最后 task 依赖全量前序 → 直接返回其输出
        if (plan.mode in (PlanMode.PARALLEL, PlanMode.SEQUENTIAL, PlanMode.DAG)
                and self._is_synthesizer_task(plan, context)):
            last = plan.tasks[-1]
            if last.id in context and not is_error_result(context[last.id]):
                logger.info(f"[_summarize_results] 汇总 Agent: {last.agent}")
                return context[last.id]
        if plan.mode == PlanMode.PARALLEL and plan.auto_summary:
            logger.info(f"[_summarize_results] PARALLEL + auto_summary LLM ")
            return await self._call_llm_summarize(plan.original_query, context)
        if plan.mode in (PlanMode.SEQUENTIAL, PlanMode.DAG):
            if len(plan.tasks) == 1:
                task_id = plan.tasks[0].id
                if task_id in context:
                    return context[task_id]
            last_task = self._get_last_task(plan, context)
            if last_task and last_task.id in context:
                result = context[last_task.id]
                has_output = bool(result and result.strip())
                health = context_health.get(last_task.id, {})
                health_status = health.get("status", "healthy")
                failed_tools = health.get("failed_tools", [])
                if has_output and health_status == "healthy":
                    return result
                elif has_output and health_status == "degraded":
                    failed_info = f"部分工具失败: {failed_tools}"
                    logger.info(f"[_summarize_results] 任务 {last_task.id} 健康降级: {failed_info}")
                    return result + f"\n\n---\n注意: {failed_info}"
                logger.info(f"[_summarize_results]  {last_task.id} ")
                return self._degraded_summary(plan, context, context_health)
        summary = "\n"
        for tid, res in context.items():
            summary += f"\n[{tid}]: {res}\n"
        return summary
    def _degraded_summary(self, plan: ExecutionPlan, context: Dict[str, str], context_health: Dict[str, dict]) -> str:
        healthy_results = []
        degraded_results = []
        failed_task_ids = []
        for task in plan.tasks:
            if task.id not in context:
                failed_task_ids.append(task.id)
                continue
            result = context[task.id]
            if is_error_result(result):
                failed_task_ids.append(task.id)
                continue
            health = context_health.get(task.id, {})
            status = health.get("status", "healthy")
            if status == "healthy":
                healthy_results.append((task.id, result))
            else:
                failed_tools = health.get("failed_tools", [])
                degraded_results.append((task.id, result, failed_tools))
        parts = []
        if healthy_results:
            if len(healthy_results) == 1:
                parts.append(healthy_results[0][1])
            else:
                for tid, res in healthy_results:
                    parts.append(f"---  {tid}  ---\n{res}")
        elif degraded_results:
            for tid, res, failed_tools in degraded_results:
                parts.append(f"---  {tid}  {failed_tools} ---\n{res}")
        if failed_task_ids:
            parts.append(f"\n: {', '.join(failed_task_ids)}")
        if not parts:
            return ""
        return "\n\n".join(parts)
    async def _call_llm_with_prompt(self, prompt: str, fallback: str, log_tag: str) -> str:
        """调用 LLM 处理给定 prompt，失败时返回 fallback。

        _call_llm_summarize 和 _generate_direct_response 的共用逻辑：
        - 读取 disable_thinking 配置并按需添加 /no_think 前缀
        - 检查 llm_model 可用性
        - 调用 call_llm 并提取 content
        - 异常时返回 fallback
        """
        disable_thinking = get_config('agent.planner.disable_thinking', False)
        if disable_thinking:
            prompt = f"/no_think\n\n{prompt}"
            logger.debug(f"[{log_tag}]  /no_think")
        if not self.llm_model:
            logger.warning(f"[{log_tag}] LLM ")
            return fallback
        try:
            from langchain_core.messages import HumanMessage
            from utils.llm import call_llm
            messages = [HumanMessage(content=prompt)]
            res = await call_llm(self.llm_model, messages)
            response = res.content if hasattr(res, 'content') else str(res)
            logger.debug(f"[{log_tag}] LLM : {response[:50]}...")
            return response
        except Exception as e:
            logger.error(f"[{log_tag}] LLM : {e}")
            return fallback

    async def _call_llm_summarize(self, query: str, context: Dict[str, str]) -> str:
        """用 LLM 汇总多任务结果，失败时返回 context_str 兜底。"""
        context_str = "\n".join([f"- {k}: {v}" for k, v in context.items()])
        prompt = f"""请汇总以下各任务的结果，针对用户查询给出综合回复。

用户查询：{query}

各任务结果：
{context_str}

请整合上述结果，给出条理清晰的综合回复。"""
        return await self._call_llm_with_prompt(prompt, context_str, "_call_llm_summarize")

    async def _generate_direct_response(self, query: str) -> str:
        """用 LLM 生成直接回复，失败时返回空串兜底。"""
        prompt = f"""请直接回答用户的问题，无需调用任何工具或 agent。

用户问题：{query}"""
        return await self._call_llm_with_prompt(prompt, "", "_generate_direct_response")