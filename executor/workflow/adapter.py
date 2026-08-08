"""WorkflowAdapter 接口 + 调度工厂：本地 LangGraph 与远程 A2A 的统一适配层。

设计目标：为"agent 作为独立远程服务"的演进预留路径（A2A 协议）。
当前默认全部走本地 LangGraphWorkflowAdapter，**零行为变更**。

演进开关（config）：
    "agent": { "execution": { "remote_a2a": { "endpoints": {"agent_name": "http://host:port"} } } }
命中 task.agent 的 agent 走 RemoteA2AAdapter（基于 a2a-sdk），其余仍走本地。
adapter 在 plan 构建前创建（不知 task.agent），故远程路由下沉到
execute_task[_stream] 调用时按 task.agent 选择（见 DispatchingWorkflowAdapter）。
"""
from __future__ import annotations

from typing import Any, AsyncGenerator, Optional, Protocol, runtime_checkable

from loguru import logger

from utils.config import get_config


@runtime_checkable
class WorkflowAdapter(Protocol):
    """工作流适配层接口：StateGraphBuilder 的 node 函数通过此接口执行单个 task。

    实现方：
    - LangGraphWorkflowAdapter：进程内 LangGraph ReAct/DeepAgent（默认）
    - RemoteA2AAdapter：远程 A2A 协议 agent（预留，config 开启）

    契约方法签名与 LangGraphWorkflowAdapter 现有实现完全一致，向后兼容。
    """

    async def execute_task(
        self,
        task: Any,
        plan: Any,
        context: dict,
        deep_thinking: bool = False,
        options: Optional[Any] = None,
        context_health: Optional[dict] = None,
    ) -> Any: ...

    async def execute_task_stream(
        self,
        task: Any,
        plan: Any,
        context: dict,
        deep_thinking: bool = False,
        options: Optional[Any] = None,
        context_health: Optional[dict] = None,
    ) -> AsyncGenerator[Any, None]: ...


class DispatchingWorkflowAdapter:
    """按 task.agent 路由到本地 LangGraph 或远程 A2A。

    endpoints 在构造时读一次（agent.execution.remote_a2a.endpoints），
    命中 task.agent → remote_factory(agent_name, url)，否则 → 本地 adapter。
    默认 endpoints 为空 → 工厂直接返回本地 adapter，不经过本类（零开销）。

    remote_factory 可注入（默认构造 RemoteA2AAdapter），便于单测替换为 fake。
    """

    def __init__(
        self,
        local: WorkflowAdapter,
        endpoints: Optional[dict] = None,
        remote_factory: Optional[Any] = None,
    ):
        self._local = local
        self._endpoints = endpoints or {}
        self._remote_factory = remote_factory or self._default_remote_factory

    @staticmethod
    def _default_remote_factory(agent_name: str, url: str) -> WorkflowAdapter:
        """构造 RemoteA2AAdapter（a2a-sdk 版），从 config 读鉴权配置。

        config: agent.execution.remote_a2a.auth = {agent_name: {"token": "...", "headers": {...}}}
        """
        from executor.workflow.remote_a2a_adapter import RemoteA2AAdapter
        auth_token = None
        auth_headers = None
        try:
            auth_cfg = get_config("agent.execution.remote_a2a.auth", {}) or {}
            per_agent = auth_cfg.get(agent_name) or {}
            if isinstance(per_agent, dict):
                auth_token = per_agent.get("token")
                auth_headers = per_agent.get("headers")
        except Exception:
            pass
        return RemoteA2AAdapter(
            endpoint_url=url, agent_name=agent_name,
            auth_token=auth_token, auth_headers=auth_headers,
        )

    def _select(self, task) -> Optional[WorkflowAdapter]:
        """按 task.agent 选远程 adapter；无 endpoint 返回 None（走本地）。"""
        url = self._endpoints.get(getattr(task, "agent", None))
        if not url:
            return None
        try:
            return self._remote_factory(task.agent, url)
        except Exception as e:
            logger.warning(f"[DispatchingAdapter] 远程 adapter 构造失败 {task.agent}: {e}，降级本地")
            return None

    async def execute_task(
        self, task, plan, context, deep_thinking=False, options=None, context_health=None
    ):
        target = self._select(task) or self._local
        return await target.execute_task(task, plan, context, deep_thinking, options, context_health)

    async def execute_task_stream(
        self, task, plan, context, deep_thinking=False, options=None, context_health=None
    ) -> AsyncGenerator[Any, None]:
        target = self._select(task) or self._local
        async for ev in target.execute_task_stream(
            task, plan, context, deep_thinking, options, context_health
        ):
            yield ev


def create_workflow_adapter(
    langgraph_executor,
    subagent_getter,
    tools_getter,
    llm_model=None,
    response_mode_getter=None,
    messages_getter=None,
) -> WorkflowAdapter:
    """创建调度型 adapter：默认本地，按 config 远程化指定 agent（A2A 预留）。

    无 endpoints → 直接返回本地 LangGraphWorkflowAdapter（与原 create_langgraph_adapter
    返回同一对象，零行为变更）。有 endpoints → 包 DispatchingWorkflowAdapter 路由。
    """
    from .langgraph_adapter import create_langgraph_adapter
    local = create_langgraph_adapter(
        langgraph_executor=langgraph_executor,
        subagent_getter=subagent_getter,
        tools_getter=tools_getter,
        llm_model=llm_model,
        response_mode_getter=response_mode_getter,
        messages_getter=messages_getter,
    )
    try:
        endpoints = get_config("agent.execution.remote_a2a.endpoints", {}) or {}
    except Exception:
        endpoints = {}
    if not endpoints:
        return local
    logger.info(f"[create_workflow_adapter] 远程 A2A endpoints 命中: {list(endpoints.keys())}")
    return DispatchingWorkflowAdapter(local=local, endpoints=endpoints)
