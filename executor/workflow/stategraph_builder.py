"""StateGraphBuilder：从 ExecutionPlan 动态构建 LangGraph StateGraph。

替代自研 Schedule + WorkflowDAGExecutor 的拓扑排序 + 分层并行。
利用 LangGraph 的 add_edge fan-in 实现依赖调度，
config["max_concurrency"] 控制图内并行，
add_node(retry_policy=) 实现节点级重试。
"""
from __future__ import annotations

import asyncio
from typing import Annotated, Optional

from langgraph.graph import START, END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import RetryPolicy
from loguru import logger
from typing_extensions import TypedDict
from utils.planning.schemas import ExecutionPlan, TaskNode
from utils.config import get_config

from .langgraph_adapter import LangGraphWorkflowAdapter


def _merge_task_dict(left: dict, right: dict) -> dict:
    """合并 {task_id: ...} dict；同 key 冲突（值不同）记 warning。

    L8：替代 operator.or_ 的静默覆盖，显式检测并发写冲突。
    行为等价（后者覆盖），仅增加 warning 便于排查 replan 后同 id 碰撞。
    """
    if not left:
        return dict(right)
    merged = dict(left)
    for k, v in right.items():
        if k in merged and merged[k] != v:
            logger.warning(f"[StateGraph] 冲突写入 task_id={k}: 旧值被覆盖")
        merged[k] = v
    return merged


class WorkflowState(TypedDict):
    """工作流状态：存储各 task 的结果和错误。

    使用 Annotated[dict, _merge_task_dict] reducer：同一 super-step 内多个 node
    并发返回 {task_id: result} 时自动合并，避免 INVALID_CONCURRENT_GRAPH_UPDATE；
    同 key 冲突显式记 warning（L8）。

    L5（结构化状态，非破坏性新增）：
    - artifacts: {task_id: [结构化工件]}，节点可产出结构化数据（非文本）
    - blackboard: 跨 task 共享黑板，任意 node 可读写结构化中间态
    二者默认空 dict，不读写则不影响现有 results/errors 契约。
    """
    results: Annotated[dict, _merge_task_dict]   # {task_id: result_str}，多 node 合并
    errors: Annotated[dict, _merge_task_dict]    # {task_id: error_str}，on_failure="continue" 时填充
    artifacts: Annotated[dict, _merge_task_dict]   # L5: {task_id: [结构化工件]}
    blackboard: Annotated[dict, _merge_task_dict]  # L5: 跨 task 共享结构化黑板


class StateGraphBuilder:
    """从 ExecutionPlan 动态构建 LangGraph StateGraph。

    构建流程：
    1. 为每个 TaskNode 创建 node 函数（含 semaphore 共享 + retry_policy）
    2. 根据 dependencies 创建 add_edge（含 fan-in: add_edge([...], target)）
    3. compile(checkpointer) → CompiledStateGraph
    """

    def __init__(
        self,
        adapter: LangGraphWorkflowAdapter,
        checkpointer: Optional[BaseCheckpointSaver] = None,
    ):
        self._adapter = adapter
        self._checkpointer = checkpointer
        self._agent_semaphores: dict = {}

    def build(
        self,
        plan: ExecutionPlan,
        semaphore: asyncio.Semaphore,
        max_concurrency: int = 10,
        deep_thinking: bool = False,
        stream_mode: str = "final",
        agent_rate_limits: dict = None,
    ) -> CompiledStateGraph:
        """从 ExecutionPlan 构建 StateGraph 并编译。

        Args:
            plan: 执行计划，包含 tasks 和 dependencies
            semaphore: 外部信号量，与 node 函数共享（图间+图内统一并发控制）
            max_concurrency: 传入 config["max_concurrency"]，控制 Pregel 图内并行
            deep_thinking: 透传给 adapter
            stream_mode: "final"（非流式 execute_task，dispatch 用）/
                         "stream"（流式 execute_task_stream + get_stream_writer，chat stream 用）
            agent_rate_limits: per-agent 限流 {agent_name: rate_limit}，有则独立 semaphore，无则全局 fallback

        Returns:
            CompiledStateGraph: 编译后的图实例
        """
        self._agent_semaphores = {agent: asyncio.Semaphore(limit) for agent, limit in (agent_rate_limits or {}).items()}
        # L8: task id 唯一性断言（replan 后同 id 碰撞的 defense-in-depth）
        task_ids = [t.id for t in plan.tasks]
        if len(task_ids) != len(set(task_ids)):
            dupes = sorted({i for i in task_ids if task_ids.count(i) > 1})
            raise ValueError(f"[StateGraphBuilder] 重复 task id: {dupes}")
        builder = StateGraph(WorkflowState)

        # 1. 为每个 task 创建 node 函数
        for task in plan.tasks:
            node_func = self._make_node_func(task, plan, semaphore, deep_thinking=deep_thinking, stream_mode=stream_mode)
            retry_policy = self._get_retry_policy(task)
            if retry_policy:
                builder.add_node(task.id, node_func, retry_policy=retry_policy)
            else:
                builder.add_node(task.id, node_func)

        # 2. 构建 edge（含 fan-in）
        self._add_edges(builder, plan.tasks)

        # 3. 编译
        compile_kwargs = {}
        if self._checkpointer:
            compile_kwargs["checkpointer"] = self._checkpointer

        graph = builder.compile(**compile_kwargs)
        logger.info(
            f"[StateGraphBuilder] 图构建完成: {len(plan.tasks)} tasks, "
            f"max_concurrency={max_concurrency}"
        )
        return graph

    def _select_semaphore(self, task: TaskNode, global_semaphore: asyncio.Semaphore) -> asyncio.Semaphore:
        """按 task.agent 选 semaphore：per-agent 优先，全局 fallback。"""
        return self._agent_semaphores.get(task.agent, global_semaphore)

    def _make_node_func(
        self,
        task: TaskNode,
        plan: ExecutionPlan,
        semaphore: asyncio.Semaphore,
        deep_thinking: bool = False,
        stream_mode: str = "final",
    ):
        """创建 node 函数，内部共享 semaphore 并调用 adapter。

        Args:
            stream_mode: "final"（非流式 execute_task，dispatch 用）/
                         "stream"（流式 execute_task_stream + get_stream_writer 转发 token 增量，chat stream 用）
        """
        adapter = self._adapter
        # L10a: 信号量 acquire 超时（防长任务持有致饥饿/无限等待），默认 60s
        acquire_timeout = get_config("agent.execution.parallel_tasks.acquire_timeout", 60)

        async def node(state: WorkflowState) -> dict:
            # A6: 增量重规划——replan 已 seed 的已完成 task 直接跳过（同 id 不重跑）；
            # loop 用 fresh initial_state（无 seed）故不影响循环重跑
            if task.id in state.get("results", {}):
                logger.debug(f"[StateGraphBuilder] task {task.id} 已在 results，跳过（增量）")
                return {}
            # L2: 构造 dep context——优先 artifacts 里的 TaskResultEnvelope（含 status/结构化工件），
            # fallback results(str)。下游 _build_task_context/_build_input 经 is_error_result/result_to_text
            # 兼容两者，envelope 使错误检测走 status 而非 "error:" 文本前缀
            dep_context = self._build_dep_context(state)
            # W1: 把 dep_context 设入 contextvar，使下游 agent 的 get_upstream_result 工具
            # 可无损读取上游完整结果（不依赖 prompt 文本截断）
            from .artifact_context import set_dep_context, reset_dep_context
            _dep_token = set_dep_context(dep_context)
            sem = self._select_semaphore(task, semaphore)
            try:
                await asyncio.wait_for(sem.acquire(), timeout=acquire_timeout)
            except asyncio.TimeoutError:
                logger.warning(f"[StateGraphBuilder] task {task.id} 信号量等待超时 {acquire_timeout}s，fail-fast")
                reset_dep_context(_dep_token)
                return self._result_state(task, f"error: semaphore acquire timeout ({acquire_timeout}s)",
                                         error=f"semaphore acquire timeout ({acquire_timeout}s)")
            try:
                if stream_mode == "stream":
                    # B-1: 流式 node——用 execute_task_stream + get_stream_writer 转发 token 增量
                    # 解决 GAP-1：消费方用 astream(stream_mode=["updates","custom"]) 同时拿 token 增量 + 最终结果
                    from langgraph.config import get_stream_writer
                    writer = get_stream_writer()
                    final_result = ""
                    async for event in adapter.execute_task_stream(
                        task=task,
                        plan=plan,
                        context=dep_context,
                        deep_thinking=deep_thinking,
                    ):
                        # 转发 adapter 事件到 custom stream channel
                        writer({"task_id": task.id, "event": event})
                        # 收集最终结果（adapter 末尾事件在 metadata 标记 is_final，结果在 data）
                        # P1 修复：原 getattr(event, "is_final") 恒 False（is_final 在 metadata 而非属性），
                        # 致 final_result 永远为空 → 多任务流式 DAG/SEQUENTIAL 下游丢失上游结果
                        if event.metadata.get("is_final", False):
                            final_result = event.data or ""
                    return self._result_state(task, final_result)
                else:
                    # 现有逻辑：非流式 execute_task（dispatch 用）
                    result = await adapter.execute_task(
                        task=task,
                        plan=plan,
                        context=dep_context,
                        deep_thinking=deep_thinking,
                    )
                    return self._result_state(task, result)
            except Exception as e:
                logger.error(f"[StateGraphBuilder] task {task.id} failed: {e}")
                if task.on_failure == "stop":
                    raise
                return self._result_state(task, f"error: {e}", error=str(e))
            finally:
                sem.release()
                reset_dep_context(_dep_token)

        return node

    def _result_state(self, task: TaskNode, output: str, error: str = None) -> dict:
        """构造 node 返回值（A5）。

        - results: {task.id: output_str}（保持 str 契约，向后兼容 is_error_result/_build_input）
        - artifacts: {task.id: [TaskResultEnvelope]}（结构化结果落地，L5 通道真实消费者）
        - errors: 失败时填 {task.id: error}
        """
        from .types import TaskResultEnvelope, TaskStatus, is_error_result
        failed = error is not None or is_error_result(output)
        status = TaskStatus.FAILED if failed else TaskStatus.COMPLETED
        envelope = TaskResultEnvelope(
            status=status,
            output="" if failed else output,
            error=error or (output if failed else ""),
        )
        state: dict = {
            "results": {task.id: output},
            "artifacts": {task.id: [envelope]},
        }
        if failed:
            state["errors"] = {task.id: error or output}
        return state

    @staticmethod
    def _build_dep_context(state: dict) -> dict:
        """L2/L5：构造 dep context。

        合并来源（后者覆盖前者，blackboard 优先级最高）：
        - results: {tid: str}（str 契约，向后兼容）
        - artifacts: {tid: [TaskResultEnvelope]}（结构化，优先于 results 的同 tid str）
        - blackboard: {key: val}（L5 跨 task 共享结构化黑板，任意 key；使 blackboard 可被下游消费）

        下游经 is_error_result/result_to_text 兼容 str 与 envelope。
        """
        results = state.get("results", {}) or {}
        artifacts = state.get("artifacts", {}) or {}
        blackboard = state.get("blackboard", {}) or {}
        dep_context: dict = {}
        # 1. results str（兜底）
        for tid, r in results.items():
            dep_context[tid] = r
        # 2. artifacts envelope（覆盖同 tid 的 str）
        for tid, envs in artifacts.items():
            if envs:
                dep_context[tid] = envs[0]
        # 3. blackboard（L5 跨 task 共享，key 可与 tid 不同；优先级最高）
        for k, v in blackboard.items():
            dep_context[k] = v
        return dep_context

    def _get_retry_policy(self, task: TaskNode):
        """获取节点的重试策略。

        on_failure='continue' → 不重试（返回 None，node catch 异常返回 errors dict）
        on_failure='stop'/'retry' → 设 RetryPolicy（重试 max_attempts 次，读 config）
        """
        if task.on_failure == "continue":
            return None
        return RetryPolicy(
            initial_interval=0.5,
            backoff_factor=2.0,
            max_interval=128.0,
            max_attempts=get_config("agent.execution.retry.max_attempts", 3),
            jitter=True,
        )

    def _add_edges(self, builder: StateGraph, tasks: list):
        """构建 edge：START → entry tasks → ... → terminal tasks → END。"""
        task_ids = {t.id for t in tasks}

        # 无依赖 → START
        for task in tasks:
            if not task.dependencies:
                builder.add_edge(START, task.id)

        # 有依赖 → fan-in（add_edge(["dep1", "dep2"], "target")）
        for task in tasks:
            if task.dependencies:
                valid_deps = [d for d in task.dependencies if d in task_ids]
                if valid_deps:
                    builder.add_edge(valid_deps, task.id)

        # 终点 → END
        has_dependents = set()
        for task in tasks:
            for dep in task.dependencies:
                has_dependents.add(dep)
        terminal_tasks = [t.id for t in tasks if t.id not in has_dependents]
        for tid in terminal_tasks:
            builder.add_edge(tid, END)
