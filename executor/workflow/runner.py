"""WorkflowRunner：replan/loop 轮次推进的共享编排（A1）。

消除 PlanExecutor._execute_with_workflow 与 MultiAgentService.dispatch_stream 中
重复的"loop/replan 决策 + 图重建"块，并修复 dispatch 缺 replan_round 上限的
潜在无限重规划 bug（plan 持续命中 condition 时会无限重规划）。

两入口各自保留 astream 消费翻译、human_approval、finalize（caller-specific），
仅把"轮次决策 + 重建图 + 计数器更新"下沉至此。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from loguru import logger
from utils.planning.schemas import ExecutionPlan
from .replan import check_loop, check_replan


@dataclass
class RoundDecision:
    """一轮的决策结果。

    action: "loop"（重跑同 plan）/ "replan"（新 plan）/ "done"（结束）
    命中 loop/replan 时 new_graph 已重建、计数器已更新；done 时 new_graph/initial_state 为 None。
    initial_state: 下一轮 astream 的初始状态（A6：replan seed 旧结果以跳过已完成 task；
                   loop 用 fresh 以允许重跑）
    """
    action: str
    plan: ExecutionPlan
    new_graph: Optional[Any]
    loop_round: int
    replan_round: int
    initial_state: Optional[dict] = None


class WorkflowRunner:
    """共享的 replan/loop 轮次推进器。

    caller 注入 builder/semaphore/build_kwargs（含 stream_mode/deep_thinking/
    max_concurrency/agent_rate_limits 的差异）+ 限额 + llm_model + replan_fn。
    advance() 返回下一轮决策；action=="done" 时调用方 break。
    """

    def __init__(
        self,
        builder,
        semaphore,
        build_kwargs: dict,
        *,
        max_replan_rounds: int,
        max_loop: int,
        llm_model: Any = None,
        context_health: Optional[dict] = None,
        replan_fn: Optional[Any] = None,
    ):
        self._builder = builder
        self._semaphore = semaphore
        self._build_kwargs = build_kwargs
        self._max_replan_rounds = max_replan_rounds
        self._max_loop = max_loop
        self._llm_model = llm_model
        self._context_health = context_health or {}
        self._replan_fn = replan_fn

    def _rebuild(self, plan: ExecutionPlan):
        return self._builder.build(plan=plan, semaphore=self._semaphore, **self._build_kwargs)

    @staticmethod
    def _fresh_state() -> dict:
        """fresh 初始状态（loop 用：允许重跑同 plan）。"""
        return {"results": {}, "errors": {}, "artifacts": {}, "blackboard": {}}

    def _seeded_state(self, context: dict) -> dict:
        """A6：seed 旧结果到 initial_state，使 replan 后同 id task 被 node 跳过（增量）。

        新 plan 通常生成新 id（LLM 不知旧 id）→ 罕见命中；命中则跳过已完成 task 不重跑。
        artifacts/blackboard 不 seed（结构化工件跨轮保留留待后续）。
        """
        return {"results": dict(context), "errors": {}, "artifacts": {}, "blackboard": {}}

    @staticmethod
    def _diff_and_reuse_ids(old_plan: ExecutionPlan, new_plan: ExecutionPlan) -> ExecutionPlan:
        """A6 plan-diff：按 (agent, description) 匹配，复用旧 task id + 重写 dependencies。

        LLM replan 生成新 id，但若某 task 的 agent+description 与旧 plan 一致（未变更），
        复用旧 id 使 A6 skip-if-in-results 命中（不重跑已完成 task）。依赖项同步重写。
        匹配歧义（同 agent+description 多个）取首个；启发式，best-effort。
        """
        # 旧 (agent, description) → id（首个匹配）
        old_map: dict = {}
        for t in old_plan.tasks:
            key = (t.agent, t.description)
            if key not in old_map:
                old_map[key] = t.id
        # 新 id → 旧 id 映射
        id_remap: dict = {}
        for t in new_plan.tasks:
            key = (t.agent, t.description)
            if key in old_map and old_map[key] != t.id:
                id_remap[t.id] = old_map[key]
        if not id_remap:
            return new_plan
        # 重写新 plan：task id + dependencies
        for t in new_plan.tasks:
            if t.id in id_remap:
                t.id = id_remap[t.id]
            if t.dependencies:
                t.dependencies = [id_remap.get(d, d) for d in t.dependencies]
        return new_plan

    async def advance(self, plan, context, *, loop_round, replan_round) -> RoundDecision:
        """决定下一轮：loop / replan / done。

        顺序：task 级循环（无 LLM，重跑同 plan）优先于重规划。
        修复点：replan 受 replan_round < max_replan_rounds 上限约束
        （原 dispatch 缺此检查，plan 持续命中 condition 时会无限重规划）。
        A6：loop 用 fresh initial_state（重跑），replan 用 seeded（增量跳过已完成）。
        """
        # task 级循环（无 LLM，重跑同 plan，优先于重规划）
        if self._max_loop > 0 and check_loop(plan, context):
            if loop_round < self._max_loop:
                logger.info(f"[WorkflowRunner] 循环第 {loop_round + 1} 轮（task loop），重跑同 plan")
                return RoundDecision("loop", plan, self._rebuild(plan),
                                     loop_round + 1, replan_round, self._fresh_state())
            logger.warning(f"[WorkflowRunner] 循环超 max_loop={self._max_loop}，停止")
            return RoundDecision("done", plan, None, loop_round, replan_round, None)
        # 动态重规划（受 replan_round 上限约束）
        if self._max_replan_rounds > 0 and replan_round < self._max_replan_rounds:
            new_plan = await check_replan(
                plan, context, self._context_health, self._llm_model, replan_fn=self._replan_fn
            )
            if new_plan is not None:
                # A6 plan-diff：复用未变更 task 的旧 id，使 skip-if-in-results 命中
                new_plan = self._diff_and_reuse_ids(plan, new_plan)
                logger.info(f"[WorkflowRunner] 重规划第 {replan_round + 1} 轮")
                return RoundDecision("replan", new_plan, self._rebuild(new_plan),
                                     loop_round, replan_round + 1, self._seeded_state(context))
        return RoundDecision("done", plan, None, loop_round, replan_round, None)
