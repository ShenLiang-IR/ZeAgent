"""多 agent 调度服务：接入 executor/workflow/ 调度体系，支持并行调度。

通过 LangGraphWorkflowAdapter + WorkflowParallelExecutor 实现多 agent 并行执行，
流式聚合各 agent 输出。一期只实现 parallel 模式。

注意：使用 config_db.subagents（AgentRepository）避免 repositories/__init__ 循环 import。
"""
from collections.abc import AsyncGenerator
from typing import Any

from loguru import logger
from utils.observability.metrics import DISPATCH_TOTAL, DISPATCH_DURATION
import time


class MultiAgentService:
    """多 agent 调度服务，封装 executor/workflow 体系。"""

    _table_ensured = False

    def __init__(self):
        import asyncio as _aio

        from utils.config import get_config_db
        self._db = get_config_db()
        self._ensure_table()
        self._cleanup_stale_records()
        # per-workspace Semaphore 池：dict[workspace_id → Semaphore]
        # 不同 workspace 隔离并发额度，避免单租户拖垮全局
        self._workspace_semaphores: dict[int, _aio.Semaphore] = {}
        # dispatch 熔断器：LLM 故障时自动开路避免雪崩
        # 设计参见 docs/specs/2026-07-19-circuit-breaker-design.md
        from utils.circuit_breaker import CircuitBreaker
        from utils.config import get_config
        failure_threshold = get_config("agent.execution.circuit_breaker.failure_threshold", 5)
        recovery_timeout = get_config("agent.execution.circuit_breaker.recovery_timeout", 60)
        self._dispatch_breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            name="dispatch",
        )

    def _get_workspace_semaphore(self, workspace_id):
        """获取 per-workspace Semaphore（按 workspace_id 隔离并发额度）。

        - 已缓存的 workspace_id：返回缓存的 Semaphore
        - 在 workspace_quotas 配置里：按配置 limit 创建 Semaphore
        - 未配置的 workspace_id：fallback 到全局 max_concurrency
        - workspace_id=None：返回 None（调用方应自己用全局 Semaphore）

        Args:
            workspace_id: workspace ID（int 或 None）

        Returns:
            asyncio.Semaphore 或 None
        """
        import asyncio as _aio
        if workspace_id is None:
            return None
        wid = int(workspace_id)
        if wid in self._workspace_semaphores:
            return self._workspace_semaphores[wid]
        # 查配置：agent.execution.workspace_quotas = {"1": 5, "2": 10}
        from utils.config import get_config
        workspace_quotas = get_config("agent.execution.workspace_quotas", {})
        limit = workspace_quotas.get(str(wid)) or workspace_quotas.get(wid)
        if limit is None:
            # 未配置的 workspace：用全局 max_concurrency fallback
            limit = get_config("agent.execution.parallel_tasks.max_concurrency", 5)
        sem = _aio.Semaphore(int(limit))
        self._workspace_semaphores[wid] = sem
        return sem


    def _cleanup_stale_records(self):
        """②崩溃恢复：清理 30 分钟前的 running 记录为 failed（进程崩溃残留）。

        加时间窗口避免误杀热重启中正执行的任务。
        """
        try:
            from datetime import datetime, timedelta

            from sqlalchemy import update

            from infrastructure.database.models.dispatch_record import DispatchRecord
            from infrastructure.database.sessions import get_config_session
            cutoff = datetime.now(datetime.UTC) - timedelta(minutes=30)
            with get_config_session() as session:
                session.execute(
                    update(DispatchRecord)
                    .where(DispatchRecord.status == "running")
                    .where(DispatchRecord.create_time < cutoff)
                    .values(status="failed", error="进程崩溃恢复：running→failed（超30分钟）")
                )
        except Exception as e:
            logger.warning(f"[MultiAgent] 崩溃恢复清理失败: {e}")

    def _ensure_table(self):
        """确保 tb_dispatch_record 表存在（三期持久化，自动建表，幂等 lazy init）。"""
        if MultiAgentService._table_ensured:
            return
        try:
            from infrastructure.database.base import Base
            from infrastructure.database.engines import get_config_engine
            from infrastructure.database.models.dispatch_record import DispatchRecord
            Base.metadata.create_all(get_config_engine(), tables=[DispatchRecord.__table__], checkfirst=True)
            MultiAgentService._table_ensured = True
        except Exception as e:
            logger.warning(f"[MultiAgent] 建表失败: {e}")

    def list_dispatch_records(self, limit: int = 10) -> list[dict[str, Any]]:
        """查询历史调度记录（三期持久化，进程重启可查）。"""
        from sqlalchemy import select

        from infrastructure.database.models.dispatch_record import DispatchRecord
        from infrastructure.database.sessions import get_config_session
        with get_config_session() as session:
            stmt = select(DispatchRecord).order_by(DispatchRecord.pr_key_id.desc()).limit(limit)
            rows = session.scalars(stmt).all()
            return [{
                "pr_key_id": r.pr_key_id,
                "dispatch_id": r.dispatch_id,
                "agent_ids": r.agent_ids,
                "message": r.message,
                "mode": r.mode,
                "status": r.status,
                "result": r.result,
                "error": r.error,
                "create_time": str(r.create_time) if r.create_time else None,
            } for r in rows]

    async def resume_dispatch(self, dispatch_id: str) -> AsyncGenerator[dict[str, Any]]:
        """W3 崩溃 resume：加载 DispatchRecord 的部分结果，用 resume_from seed 续跑。

        从 tb_dispatch_record 取 agent_ids/message/mode/result（部分 collected_results），
        重调 dispatch_stream(resume_from=result)。dispatch 模式 task id 稳定（task_{i}_{aid}），
        故 seed 命中已完成 task 被 A6 skip 跳过，仅重跑未完成部分。
        适用于开启了 crash_resume.persist_intermediate 的场景（否则 result 为空无法续跑）。

        Yields: dispatch_stream 的事件流。
        """
        import json as _json
        from infrastructure.database.models.dispatch_record import DispatchRecord
        from infrastructure.database.sessions import get_config_session
        from sqlalchemy import select
        with get_config_session() as session:
            stmt = select(DispatchRecord).where(DispatchRecord.dispatch_id == dispatch_id).limit(1)
            rec = session.scalars(stmt).first()
            if not rec:
                yield {"type": "error", "data": f"未找到 dispatch 记录 {dispatch_id}"}
                return
            try:
                agent_ids = _json.loads(rec.agent_ids) if rec.agent_ids else []
            except (ValueError, TypeError):
                yield {"type": "error", "data": "dispatch 记录 agent_ids 解析失败"}
                return
            try:
                prior_results = _json.loads(rec.result) if rec.result else {}
            except (ValueError, TypeError):
                prior_results = {}
            message = rec.message or ""
            mode = rec.mode or "parallel"
        if not agent_ids or not prior_results:
            yield {"type": "error", "data": f"dispatch {dispatch_id} 无 agent_ids 或无中间结果，无法 resume"}
            return
        logger.info(f"[MultiAgent] resume_dispatch {dispatch_id}：{len(agent_ids)} agents, "
                    f"{len(prior_results)} 个已完成结果将跳过")
        async for ev in self.dispatch_stream(
            agent_ids=agent_ids, message=message, mode=mode, resume_from=prior_results,
        ):
            yield ev

    async def dispatch_stream(
        self,
        agent_ids: list[str],
        message: str,
        mode: str = "parallel",
        tasks: list[dict[str, Any]] | None = None,
        workspace_id: int | None = None,
        degrade_model_id: str | None = None,
        team_id: str | None = None,
        resume_from: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any]]:
        """调度多 agent，流式 yield 各 agent 事件。

        Args:
            agent_ids: agent pr_key_id 列表（parallel 模式）
            message: 用户消息
            mode: parallel（并行）| dag（依赖调度）
            tasks: DAG 模式的 task 定义列表 [{agent_id, dependencies:[索引]}]
            workspace_id: workspace ID（可选）。传入时用 per-workspace Semaphore 隔离
                          并发额度，未传时用全局 Semaphore（向下兼容）
            resume_from: W3 崩溃 resume——传入 prior collected_results（{task_id: result}），
                         seed 到 initial_state，使已完成 task 被 A6 skip-if-in-results 跳过续跑。
                         dispatch 模式 task id 稳定（task_{i}_{aid}），故 seed 可命中。

        Yields:
            事件 dict: {type, task_id, agent?, content?}
        """
        start_time = time.time()
        # N3: 注入调用方 workspace 到 _DELEGATION_WORKSPACE，供 delegate_agent 做目标 agent 可见性校验
        # （contextvar 在本 dispatch 的 asyncio task 内有效，task 结束自动释放）
        from delegation.delegate_agent import _DELEGATION_WORKSPACE
        _DELEGATION_WORKSPACE.set(workspace_id)
        # 熔断检查：open 状态时直接 yield error，不调 LLM
        # getattr 兼容 __new__ 绕过 __init__ 的测试场景
        if not hasattr(self, "_dispatch_breaker"):
            from utils.circuit_breaker import CircuitBreaker
            self._dispatch_breaker = CircuitBreaker(name="dispatch")
        if self._dispatch_breaker.is_open():
            logger.warning("[MultiAgent] dispatch breaker open, reject dispatch")
            yield {"type": "error", "data": "调度系统熔断中（LLM 故障），请稍后重试"}
            return

        # 团队级 dispatch：team_id → 展开为成员 agent_ids（设计 G3，向下兼容 agent_ids）
        if team_id and not agent_ids:
            from services.agent_team_service import AgentTeamService
            agent_ids = AgentTeamService().get_member_agent_ids(team_id)
            if not agent_ids:
                yield {"type": "error", "data": f"团队 {team_id} 无成员或不存在"}
                return
            logger.info(f"[MultiAgent] team dispatch {team_id} -> agents={agent_ids}")

        from executor.langgraph import get_langgraph_executor
        from executor.workflow import create_workflow_adapter

        # 1. 构建 adapter（agent 执行适配层）
        # 复用模块级单例 LangGraphTaskExecutor：图缓存跨 dispatch 复用，
        # 触发器高频重复同一 agent 时避免重复编译 LangGraph（配合 LRU 上限防膨胀）
        # create_workflow_adapter：默认本地 LangGraphWorkflowAdapter（零行为变更），
        # 当 config agent.execution.remote_a2a.endpoints 命中 task.agent 时启用远程 A2A（预留）
        # 配额 degrade：有 degrade_model_id 时切备用 LLM（与 chat 路由一致）
        from services.quota_guard import get_degrade_llm
        from utils.config import get_config
        from utils.llm import get_default_llm
        from utils.planning.schemas import ExecutionPlan, PlanMode, TaskNode
        lg_executor = get_langgraph_executor()
        llm_model = get_degrade_llm(degrade_model_id) or get_default_llm()
        adapter = create_workflow_adapter(
            langgraph_executor=lg_executor,
            subagent_getter=self._get_subagent_config,
            tools_getter=self._get_subagent_tools,
            llm_model=llm_model,
        )

        # 2. 构建 ExecutionPlan（按 mode）
        task_nodes = []
        if mode == "dag" and tasks:
            # DAG 模式：tasks 含 dependencies（索引），转为 task_id 依赖
            for i, t in enumerate(tasks):
                aid = str(t.get("agent_id", ""))
                cfg = self._db.get_effective_agent(aid)
                if not cfg:
                    logger.warning(f"[MultiAgent] agent {aid} 不存在，跳过")
                    continue
                task_id = f"task_{i}_{aid}"
                deps = [f"task_{d}_{tasks[d]['agent_id']}" for d in t.get("dependencies", []) if d < len(tasks)]
                task_nodes.append(TaskNode(
                    id=task_id,
                    agent=cfg.get("agent_name", ""),
                    description=message,
                    dependencies=deps,
                    on_failure="continue",
                ))
            # 循环依赖检测（Kahn 简化：所有 in_degree > 0 且无 0 入度 = 有环）
            _in_degrees = [len(t.get("dependencies", [])) for t in tasks]
            if sum(_in_degrees) > 0 and not any(d == 0 for d in _in_degrees):
                yield {"type": "error", "data": "DAG 循环依赖检测到，无法调度"}
                return
            plan_mode = PlanMode.DAG
            session_id = "dag_dispatch"
        elif mode == "sequential":
            # 顺序调度：链式依赖 t_i 依赖 t_{i-1}（context 传递）
            prev_task_id = None
            for i, aid in enumerate(agent_ids):
                cfg = self._db.get_effective_agent(aid)
                if not cfg:
                    logger.warning(f"[MultiAgent] agent {aid} 不存在，跳过")
                    continue
                task_id = f"task_{i}_{aid}"
                deps = [prev_task_id] if prev_task_id else []
                task_nodes.append(TaskNode(
                    id=task_id,
                    agent=cfg.get("agent_name", ""),
                    description=message,
                    dependencies=deps,
                    on_failure="continue",
                ))
                prev_task_id = task_id
            plan_mode = PlanMode.SEQUENTIAL
            session_id = "seq_dispatch"
        else:
            # parallel 模式（一期）：每个 agent 一个 task，无依赖
            for i, aid in enumerate(agent_ids):
                cfg = self._db.get_effective_agent(aid)
                if not cfg:
                    logger.warning(f"[MultiAgent] agent {aid} 不存在，跳过")
                    continue
                task_nodes.append(TaskNode(
                    id=f"task_{i}_{aid}",
                    agent=cfg.get("agent_name", ""),
                    description=message,
                    on_failure="continue",
                ))
            plan_mode = PlanMode.PARALLEL
            session_id = "multi_dispatch"

        if not task_nodes:
            yield {"type": "error", "data": "无有效 agent"}
            return

        plan = ExecutionPlan(
            mode=plan_mode,
            tasks=task_nodes,
            original_query=message,
        )

        # 统一调度：StateGraphBuilder 动态构建 StateGraph（所有 mode：parallel/dag/sequential/langgraph）
        import asyncio as _aio
        import json as _json
        import uuid as _uuid

        from langgraph.checkpoint.memory import MemorySaver

        from executor.workflow.stategraph_builder import StateGraphBuilder
        from infrastructure.database.models.dispatch_record import DispatchRecord
        from infrastructure.database.sessions import get_config_session

        dispatch_id = str(_uuid.uuid4())
        max_concurrency = get_config("agent.execution.parallel_tasks.max_concurrency", 5)
        # 优先用 per-workspace Semaphore（多租户隔离）；未传 workspace_id 时用全局 Semaphore（向下兼容）
        semaphore = self._get_workspace_semaphore(workspace_id) or _aio.Semaphore(max_concurrency)
        from utils.checkpoint import MysqlSaverFactory
        checkpointer = await MysqlSaverFactory.get_saver() or MemorySaver()

        builder = StateGraphBuilder(
            adapter=adapter,
            checkpointer=checkpointer,
        )
        agent_rate_limits = get_config("agent.execution.parallel_tasks.rate_limits", {})
        graph = builder.build(
            plan=plan,
            semaphore=semaphore,
            max_concurrency=max_concurrency,
            stream_mode="stream",
            agent_rate_limits=agent_rate_limits,
        )

        # 持久化 running 记录
        with get_config_session() as session:
            rec = DispatchRecord(
                dispatch_id=dispatch_id,
                agent_ids=_json.dumps(agent_ids, ensure_ascii=False),
                message=message,
                mode=mode,
                status="running",
            )
            session.add(rec)
            session.flush()
            record_pk = rec.pr_key_id

        # W3: resume_from seed——崩溃续跑时把 prior collected_results 注入 initial_state，
        # 使已完成 task 被 node skip-if-in-results 跳过（A6）；dispatch task id 稳定故可命中
        if resume_from:
            initial_state = {"results": dict(resume_from), "errors": {}, "artifacts": {}, "blackboard": {}}
            logger.info(f"[MultiAgent] resume dispatch：seed {len(resume_from)} 个已完成结果，跳过重跑")
        else:
            initial_state = {"results": {}, "errors": {}}
        from utils.observability import attach_callbacks
        config = attach_callbacks({
            "configurable": {"thread_id": dispatch_id},
            "max_concurrency": max_concurrency,
        }, session_id=dispatch_id)

        from utils.sse import build_sse_event
        from executor.stream_helper import send_sse_data
        collected_results = {}
        seen_task_started = set()
        # 动态重规划/循环：默认读全局 config（agent.execution.replan），与 PlanExecutor 对齐。
        # 下沉自 PlanExecutor：dispatch（触发器场景）现在也具备 replan + task 级 loop 能力。
        max_replan_rounds = get_config("agent.execution.replan.max_rounds", 3)
        max_loop = get_config("agent.execution.replan.max_loop", 3)
        replan_round = 0
        loop_round = 0
        # A1：共享 WorkflowRunner 推进轮次（消除与 PlanExecutor 的编排重复 + 修复缺
        # replan_round 上限的潜在无限重规划）
        from executor.workflow.runner import WorkflowRunner
        runner = WorkflowRunner(
            builder, semaphore,
            build_kwargs={"max_concurrency": max_concurrency, "stream_mode": "stream",
                          "agent_rate_limits": agent_rate_limits},
            max_replan_rounds=max_replan_rounds, max_loop=max_loop,
            llm_model=llm_model, replan_fn=None,
        )
        # A7：统一 trace 上下文（trace_id=dispatch_id），下游 astream/node/task 日志自动关联。
        # 手动 enter/exit 避免重排整个 while 块缩进；contextvar + logger.contextualize 经
        # asyncio context copy 传播到 Pregel 子任务。
        from utils.observability import trace_context
        _trace_ctx = trace_context(trace_id=dispatch_id, dispatch_id=dispatch_id)
        _trace_ctx.__enter__()
        try:
            while True:
                async for event in graph.astream(
                    initial_state, config=config,
                    stream_mode=["updates", "custom"],
                ):
                    mode, data = event
                    if mode == "custom":
                        task_id = (data or {}).get("task_id")
                        adapter_event = (data or {}).get("event")
                        if adapter_event is None:
                            continue
                        ev_type = getattr(adapter_event, "type", None)
                        ev_data = getattr(adapter_event, "data", None)
                        ev_type_str = ev_type.value if hasattr(ev_type, "value") else str(ev_type)
                        if ev_type_str == "content_chunk" and ev_data:
                            yield build_sse_event("content_chunk", task_id=task_id, content=ev_data, done=False)
                        elif ev_type_str == "task_started":
                            seen_task_started.add(task_id)
                            yield build_sse_event("task_started", task_id=task_id, done=False)
                        elif ev_type_str == "task_completed":
                            if isinstance(ev_data, dict):
                                collected_results[task_id] = ev_data.get("result", "")
                            yield build_sse_event("task_completed", task_id=task_id, done=True)
                        elif ev_type_str == "task_failed":
                            yield build_sse_event("task_failed", task_id=task_id, done=True)
                    elif mode == "updates":
                        for _node, output in (data or {}).items():
                            if isinstance(output, dict):
                                results = output.get("results", {})
                                errors = output.get("errors", {})
                                for task_id, result in results.items():
                                    # task_started 补发（独立于 collected_results，防 custom 未发时丢失）
                                    if task_id not in seen_task_started:
                                        yield build_sse_event("task_started", task_id=task_id, done=False)
                                        seen_task_started.add(task_id)
                                    # content_chunk + completed/failed 兜底（custom 未处理时）
                                    if task_id not in collected_results:
                                        yield build_sse_event("content_chunk", task_id=task_id, content=result, done=False)
                                        if task_id in errors:
                                            yield build_sse_event("task_failed", task_id=task_id, done=True)
                                        else:
                                            yield build_sse_event("task_completed", task_id=task_id, done=True)
                                        collected_results[task_id] = result
                # 人工审核（human_approval=true 时 pause 等审核，spec §5.2 对齐 plan_executor）
                human_approval = get_config("agent.execution.replan.human_approval", False)
                if human_approval:
                    from utils.review.registry import ReviewRegistry
                    review_timeout = get_config("agent.execution.replan.human_approval_timeout", 300)
                    ReviewRegistry.register(dispatch_id)
                    # agent_cards：每 task 的 agent 能力卡（供前端 PlanReviewDialog AgentCard 展示）
                    agent_cards = []
                    for t in plan.tasks:
                        cfg = self._get_subagent_config(t.agent) or {}
                        agent_cards.append({
                            "agent_name": t.agent,
                            "agent_description": cfg.get("agent_description", ""),
                            "tools": cfg.get("tools", []) or [],
                            "mcp_tools": cfg.get("mcp_tools", []) or [],
                            "external_tools": cfg.get("external_tools", []) or [],
                            "task_id": t.id,
                            "task_description": t.description,
                            "dependencies": t.dependencies or [],
                        })
                    yield send_sse_data(build_sse_event("plan_review", dispatch_id=dispatch_id,
                        plan={"mode": mode, "tasks": [{"id": t.id, "agent": t.agent, "description": t.description, "dependencies": t.dependencies or []} for t in plan.tasks]},
                        results=dict(collected_results), options=["approve", "modify", "reject"],
                        agent_cards=agent_cards))
                    logger.info(f"[MultiAgent] 人工审核 pause，等待 {dispatch_id}")
                    review_result = await ReviewRegistry.await_review(dispatch_id, review_timeout)
                    ReviewRegistry.remove(dispatch_id)
                    action = (review_result or {}).get("action", "reject")
                    if action == "reject":
                        logger.info("[MultiAgent] 用户拒绝，终止")
                        yield build_sse_event("task_failed", task_id="review", done=True)
                        return
                    # approve/modify: 继续到下方 loop/replan 检查（modify 重建留给 replan 路径）
                # A1：轮次决策下沉到 WorkflowRunner（loop/replan/done + 重建 + 计数）
                decision = await runner.advance(
                    plan, collected_results, loop_round=loop_round, replan_round=replan_round)
                if decision.action == "done":
                    break  # 无需循环/重规划
                plan = decision.plan
                graph = decision.new_graph
                loop_round = decision.loop_round
                replan_round = decision.replan_round
                # A6：用 runner 给的 initial_state（replan seed 旧结果 / loop fresh）
                initial_state = decision.initial_state
                # crash-resume 基础（gated）：每轮持久化中间 collected_results 到 DispatchRecord.result，
                # 进程崩溃后 DB 留有部分结果（status 仍 running→30 分钟后清 failed），
                # 为未来 resume orchestrator（reload + A6 seed 续跑）铺地基。默认关避免每轮 DB 写开销。
                if get_config("agent.execution.crash_resume.persist_intermediate", False) and collected_results:
                    try:
                        with get_config_session() as session:
                            session.query(DispatchRecord).filter(
                                DispatchRecord.pr_key_id == record_pk
                            ).update({
                                "result": _json.dumps(collected_results, ensure_ascii=False),
                            })
                    except Exception as e:
                        logger.warning(f"[MultiAgent] 中间结果持久化失败（non-fatal）: {e}")
                continue
            # 更新完成状态（对齐旧分支：写 result 字段）
            with get_config_session() as session:
                session.query(DispatchRecord).filter(
                    DispatchRecord.pr_key_id == record_pk
                ).update({
                    "status": "completed",
                    "result": _json.dumps(collected_results, ensure_ascii=False),
                })
            # 熔断器记录成功
            self._dispatch_breaker.record_success()
            # 业务指标：dispatch 成功 + 耗时
            DISPATCH_TOTAL.labels(mode=mode, status="completed").inc()
            DISPATCH_DURATION.labels(mode=mode).observe(time.time() - start_time)
            # 成本统计 hook：dispatch 完成后异步写 usage_record
            # 设计参见 docs/specs/2026-07-19-usage-tracking-design.md §4
            # MVP 第一期：token 数从 collected_results 字符数粗估（4 字符 ≈ 1 token）
            # 第二期改捕获 LangChain AIMessage.usage_metadata 真实 token 数
            try:
                await self._record_usage_hook(
                    dispatch_id=dispatch_id,
                    workspace_id=workspace_id,
                    collected_results=collected_results,
                    trigger_id=None,  # 由调用方（trigger dispatch）传入，第二期改
                    message=message,
                )
            except Exception as e:
                logger.warning(f"[MultiAgent] _record_usage_hook failed (non-fatal): {e}")
            # 自动评测 hook：dispatch 完成后 LLM-as-Judge 评分（config eval.auto_judge 控制）
            try:
                await self._eval_hook(
                    dispatch_id=dispatch_id,
                    message=message,
                    collected_results=collected_results,
                    workspace_id=workspace_id,
                )
            except Exception as e:
                logger.warning(f"[MultiAgent] _eval_hook failed (non-fatal): {e}")
            # 出站事件订阅 hook：dispatch 完成后通知外部系统（webhook + HMAC 验签）
            try:
                await self._event_subscription_hook(
                    "dispatch_completed", dispatch_id=dispatch_id,
                    workspace_id=workspace_id,
                    result_count=len(collected_results) if collected_results else 0,
                )
            except Exception as e:
                logger.warning(f"[MultiAgent] event_subscription_hook (completed) failed (non-fatal): {e}")
        except Exception as e:
            logger.error(f"[MultiAgent] dispatch failed: {e}", exc_info=True)
            # 熔断器记录失败
            self._dispatch_breaker.record_failure()
            # 业务指标：dispatch 失败 + 耗时
            DISPATCH_TOTAL.labels(mode=mode, status="failed").inc()
            DISPATCH_DURATION.labels(mode=mode).observe(time.time() - start_time)
            with get_config_session() as session:
                session.query(DispatchRecord).filter(
                    DispatchRecord.pr_key_id == record_pk
                ).update({"status": "failed", "error": str(e)[:500]})
            yield {"type": "error", "data": f"调度失败: {type(e).__name__}"}
            # 出站事件订阅 hook：dispatch 失败时通知外部系统
            try:
                await self._event_subscription_hook(
                    "dispatch_failed", dispatch_id=dispatch_id if 'dispatch_id' in dir() else "",
                    workspace_id=workspace_id, error=str(e)[:200],
                )
            except Exception:
                pass  # 事件订阅失败不影响错误处理
        finally:
            # A7：退出 trace 上下文（恢复 contextvar + logger contextualize）
            _trace_ctx.__exit__(None, None, None)

    def _get_subagent_config(self, agent_name: str) -> dict[str, Any] | None:
        """subagent_getter: agent_name → 生效配置（已发布版本快照优先，编辑不即时影响线上）。"""
        agent = self._db.subagents.get_by_name(agent_name)
        if not agent:
            return None
        return self._db.get_effective_agent(agent.get("pr_key_id")) or agent

    async def _record_usage_hook(
        self,
        dispatch_id: str,
        workspace_id: int | None,
        collected_results: dict[str, Any],
        trigger_id: str | None = None,
        message: str = "",
    ) -> None:
        """dispatch 完成后写 usage_record（每个 task 一条）。

        设计参见 docs/specs/2026-07-19-usage-tracking-design.md §4。

        MVP 第一期：token 数从字符数粗估（4 字符 ≈ 1 token）。
        第二期改为捕获 LangChain AIMessage.usage_metadata 真实 token 数。

        失败不抛异常（usage 写入是副作用，不应阻塞主流程）。
        """
        if not collected_results:
            return
        try:
            from services.usage_service import UsageService
            svc = UsageService()
            # 粗估 prompt_tokens（从 message 长度，4 字符 ≈ 1 token）
            prompt_tokens = max(1, len(message) // 4) if message else 0
            for task_id, result in collected_results.items():
                # completion_tokens 从 result 长度粗估
                result_str = str(result) if result else ""
                completion_tokens = max(1, len(result_str) // 4) if result_str else 0
                try:
                    svc.record_usage(
                        dispatch_id=dispatch_id,
                        workspace_id=workspace_id or 0,
                        agent_id=None,  # 第二期从 task.agent 拿真实 agent_id
                        user_id=None,
                        model_id="unknown",  # 第二期从 LLM response 拿真实 model_id
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        duration_ms=None,
                        trigger_id=trigger_id,
                    )
                except Exception as e:
                    logger.warning(
                        f"[MultiAgent] record_usage for {task_id} failed (non-fatal): {e}"
                    )
        except ImportError as e:
            logger.warning(f"[MultiAgent] UsageService unavailable, skip usage hook: {e}")
        except Exception as e:
            logger.warning(f"[MultiAgent] _record_usage_hook failed (non-fatal): {e}")

    async def _eval_hook(
        self,
        dispatch_id: str,
        message: str,
        collected_results: dict[str, Any],
        workspace_id: int | None = None,
    ) -> None:
        """dispatch 完成后自动 LLM-as-Judge 评测（config eval.auto_judge 控制）。

        对每个 task 的 result 用 message 作为 question 自动 judge + 存 result。
        未启用时跳过；失败不抛异常（评测是副作用）。
        """
        from utils.config import get_config
        if not get_config("eval.auto_judge", False):
            return  # 未启用自动评测
        if not collected_results:
            return
        try:
            from services.eval_service import EvalService
            svc = EvalService()
            for task_id, result in collected_results.items():
                response = str(result) if result else ""
                if not response.strip():
                    continue
                judged = await svc.judge_response(
                    question=message,
                    response=response,
                    expected_output="",  # 自动评测无 expected（离线 dataset 评测才有）
                )
                await svc.save_result(
                    dispatch_id=dispatch_id,
                    dataset_id=None,
                    question=message,
                    response=response,
                    expected_output=None,
                    score=judged["score"],
                    judge_feedback=judged["feedback"],
                    judge_model=judged["judge_model"],
                    workspace_id=workspace_id,
                )
                logger.info(f"[MultiAgent] _eval_hook {task_id}: score={judged['score']}")
        except Exception as e:
            logger.warning(f"[MultiAgent] _eval_hook inner failed (non-fatal): {e}")

    async def run_eval_dataset(self, dataset_id: str, responses: list[dict]) -> list[dict]:
        """离线评测：对 dataset 的 question 批量 judge（调用方提供 responses）。

        Args:
            dataset_id: 数据集 ID
            responses: [{question, response, expected_output?}] 列表

        Returns:
            [{question, response, score, feedback, judge_model}] 评测结果列表
        """
        try:
            from infrastructure.database.repositories.eval_repository import EvalDatasetRepository
            from services.eval_service import EvalService

            dataset = EvalDatasetRepository().get_by_dataset_id(dataset_id)
            if not dataset:
                return []
            svc = EvalService()
            results = []
            for item in responses:
                question = item.get("question", dataset.get("question", ""))
                response = item.get("response", "")
                expected = item.get("expected_output", dataset.get("expected_output", ""))
                judged = await svc.judge_response(
                    question=question, response=response, expected_output=expected,
                    scoring_criteria=dataset.get("scoring_criteria", ""),
                )
                results.append({
                    "question": question, "response": response,
                    "score": judged["score"], "feedback": judged["feedback"],
                    "judge_model": judged["judge_model"],
                })
            return results
        except Exception as e:
            logger.error(f"[MultiAgent] run_eval_dataset failed: {e}", exc_info=True)
            return []

    async def _event_subscription_hook(self, event_type: str, dispatch_id: str = "",
                                       workspace_id: int | None = None, **extra) -> None:
        """出站事件订阅 hook：dispatch 完成/失败时通知外部系统。

        查匹配订阅（event_type 精确匹配 or 'all'）+ 发 webhook（httpx POST + HMAC 验签）。
        失败不抛异常（事件订阅是副作用）。
        """
        try:
            from services.event_subscription_service import EventSubscriptionService
            payload = {"dispatch_id": dispatch_id, "workspace_id": workspace_id, **extra}
            await EventSubscriptionService().notify(event_type, payload, workspace_id)
        except Exception as e:
            logger.warning(f"[MultiAgent] _event_subscription_hook failed (non-fatal): {e}")

    async def _get_subagent_tools(self, agent_name: str, subagent_config: dict[str, Any]):
        """tools_getter: 包装 collect_subagent_tools_async 签名。

        adapter 期望 (agent_name, subagent_config) → (tools, skill_index, _, kb_stats)，
        实际 collect_subagent_tools_async(subagent_config, pr_key_id) → 4 元组。
        """
        from core.builder.tool_collector import collect_subagent_tools_async
        tools, skill_index, skill_ids, kb_stats = await collect_subagent_tools_async(
            subagent_config,
            subagent_config.get("pr_key_id"),
            return_skill_ids=True,
            return_kb_stats=True,
        )
        return tools, skill_index, skill_ids, kb_stats
