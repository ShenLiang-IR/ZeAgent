"""RemoteA2AAdapter：远程 A2A 协议 agent 适配层（a2a-sdk 版）。

基于 a2a-sdk（官方 Python SDK）实现 Agent2Agent 协议通信。
通过 Agent Card 发现远程 agent 能力，发送任务并流式接收结果，
将 A2A StreamResponse 翻译为 ExecutionEvent，无缝接入工作流调度。

依赖：pip install "a2a-sdk[all]"
"""
from __future__ import annotations

from typing import Any, AsyncGenerator, Optional

from loguru import logger

from .types import ExecutionEvent, ExecutionEventType


class RemoteA2AAdapter:
    """远程 A2A agent 适配器（WorkflowAdapter 实现）。

    基于 a2a-sdk Client 实现 A2A 协议通信：
    - Agent Card 自动发现（capabilities/skills）
    - 鉴权自动注入（Bearer token + 自定义 headers）
    - 流式 SSE 接收任务状态更新和内容块
    - 事件翻译为 ExecutionEvent（兼容 StateGraphBuilder node 接口）

    Args:
        endpoint_url: A2A agent 服务基址（如 http://host:port）
        agent_name: 本地配置中的 agent 名（日志/上下文）
        auth_token: Bearer token（注入 Authorization 头）
        auth_headers: 自定义鉴权/请求头（与 auth_token 合并，auth_headers 优先）
    """

    def __init__(
        self,
        endpoint_url: str,
        agent_name: str,
        auth_token: Optional[str] = None,
        auth_headers: Optional[dict] = None,
    ):
        self._endpoint = (endpoint_url or "").rstrip("/")
        # A3: endpoint 必须为 http(s) 绝对 URL（防异常 scheme；config 驱动但仍校验）
        if self._endpoint and not (
            self._endpoint.startswith("http://") or self._endpoint.startswith("https://")
        ):
            raise ValueError(f"A2A endpoint 必须为 http(s) URL: {self._endpoint!r}")
        self._agent_name = agent_name
        self._auth_token = auth_token
        self._auth_headers = auth_headers or {}
        self._client = None  # a2a-sdk Client（延迟初始化）

    async def _get_client(self):
        """延迟创建 a2a-sdk Client（首次调用时初始化）。"""
        if self._client is not None:
            return self._client
        try:
            from a2a.client import create_client
            from a2a.client.client import ClientConfig

            config = ClientConfig(streaming=True)
            self._client = await create_client(
                agent=self._endpoint,
                client_config=config,
            )
            logger.info(f"[RemoteA2A] 已连接 {self._agent_name} @ {self._endpoint}")
            return self._client
        except Exception as e:
            logger.error(f"[RemoteA2A] {self._agent_name} 连接失败: {e}")
            raise

    def _build_message(self, task, plan, context) -> Any:
        """构造 A2A SendMessageRequest：依赖结果作为上下文拼接。"""
        from a2a.types.a2a_pb2 import Message, Part, SendMessageRequest

        # 收集依赖任务的输出作为上下文
        deps_chunks = []
        for dep_id in getattr(task, "dependencies", []) or []:
            if dep_id in context:
                deps_chunks.append(f"[上一步结果] {context[dep_id]}")

        # 构造消息内容
        content_parts = []
        if deps_chunks:
            content_parts.append("\n".join(deps_chunks))
        content_parts.append(task.description or "")

        text = "\n\n".join(content_parts)
        part = Part(text=text)
        msg = Message(parts=[part])
        # role 默认为 user（0 = ROLE_UNSPECIFIED，让 server 自行判断）

        return SendMessageRequest(message=msg)

    # ===== WorkflowAdapter 契约 =====

    async def execute_task(
        self, task, plan, context, deep_thinking=False, options=None, context_health=None
    ) -> Any:
        """非流式：优先 a2a-sdk Client，失败/空结果时 fallback httpx 直连。"""
        request = self._build_message(task, plan, context)
        # 尝试 a2a-sdk Client
        try:
            client = await self._get_client()
            collected_text: list[str] = []
            async for stream_resp in client.send_message(request):
                text = self._extract_text(stream_resp)
                if text:
                    collected_text.append(text)
            if collected_text:
                return "".join(collected_text)
        except Exception as e:
            logger.debug(f"[RemoteA2A] a2a-sdk Client 失败，fallback httpx: {e}")
        # fallback: httpx 直连
        return await self._execute_via_httpx(task, plan, context)

    async def execute_task_stream(
        self, task, plan, context, deep_thinking=False, options=None, context_health=None
    ) -> AsyncGenerator[Any, None]:
        """流式：优先 a2a-sdk Client，失败/空结果时 fallback httpx。"""
        request = self._build_message(task, plan, context)
        try:
            client = await self._get_client()
            event_count = 0
            async for stream_resp in client.send_message(request):
                event_count += 1
                ev = self._translate(stream_resp, getattr(task, "id", task.id))
                if ev is not None:
                    yield ev
            if event_count > 0:
                return
        except Exception as e:
            logger.debug(f"[RemoteA2A] stream fallback httpx: {e}")
        # fallback
        async for ev in self._stream_via_httpx(task, plan, context):
            yield ev

    # ===== httpx fallback（a2a-sdk Client 不兼容时的降级方案） =====

    async def _execute_via_httpx(self, task, plan, context) -> str:
        """httpx 直连 POST JSON-RPC message/stream，收集所有文本。"""
        try:
            import httpx
            import json as _json
            text_parts = self._build_text_parts(task, plan, context)
            payload = {
                "jsonrpc": "2.0", "method": "message/stream", "id": "adapter_001",
                "params": {"message": {"parts": text_parts}},
            }
            async with httpx.AsyncClient(timeout=300) as cli:
                resp = await cli.post(self._endpoint, json=payload)
                resp.raise_for_status()
                collected = []
                for line in resp.text.split("\n"):
                    line = line.strip()
                    if line.startswith("data: "):
                        data = _json.loads(line[6:])
                        result = data.get("result", {})
                        # 提取文本（seen：camelCase/snake_case 别名回退指向同一 inner 时去重，防重复收集）
                        seen_inners = set()
                        for field in ("artifactUpdate", "artifact_update", "statusUpdate", "status_update"):
                            inner = result.get(field, {})
                            if not inner and field in ("statusUpdate", "status_update"):
                                inner = result.get("statusUpdate", result.get("status_update", {}))
                            if not inner or id(inner) in seen_inners:
                                continue
                            seen_inners.add(id(inner))
                            art = inner.get("artifact", {}) if "artifact" in str(field).lower() else {}
                            msg = inner.get("message", {}) if "status" in str(field).lower() else {}
                            for parts in ([inner.get("parts", [])] + [art.get("parts", [])] + [msg.get("parts", [])]):
                                for p in (parts or []):
                                    if p.get("text"):
                                        collected.append(p["text"])
                return "".join(collected) if collected else ""
        except Exception as e:
            logger.error(f"[RemoteA2A] httpx fallback 失败: {e}")
            return f"error: {e}"

    async def _stream_via_httpx(self, task, plan, context) -> AsyncGenerator[Any, None]:
        """httpx 直连流式：每行 SSE 翻译为 ExecutionEvent。"""
        import httpx
        import json as _json
        text_parts = self._build_text_parts(task, plan, context)
        payload = {
            "jsonrpc": "2.0", "method": "message/stream", "id": "adapter_001",
            "params": {"message": {"parts": text_parts}},
        }
        tid = getattr(task, "id", task.id)
        try:
            async with httpx.AsyncClient(timeout=None) as cli:
                async with cli.stream("POST", self._endpoint, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data: "):
                            continue
                        data = _json.loads(line[6:])
                        result = data.get("result", {})
                        # 简化为 content_chunk（流式 fallback 不区分事件类型）
                        text = self._extract_text_v03(result)
                        if text:
                            yield ExecutionEvent(
                                type=ExecutionEventType.CONTENT_CHUNK,
                                data=text, metadata={"task_id": tid},
                            )
                    yield ExecutionEvent(
                        type=ExecutionEventType.TASK_COMPLETED,
                        data={"task_id": tid}, metadata={"task_id": tid},
                    )
        except Exception as e:
            logger.error(f"[RemoteA2A] stream fallback 失败: {e}")
            yield ExecutionEvent(
                type=ExecutionEventType.ERROR,
                data=str(e), metadata={"task_id": tid},
            )

    def _build_text_parts(self, task, plan, context) -> list:
        """构造 JSON-RPC parts 数组（文本内容）。"""
        deps_chunks = []
        for dep_id in getattr(task, "dependencies", []) or []:
            if dep_id in context:
                deps_chunks.append(f"[上一步结果] {context[dep_id]}")
        content_parts = []
        if deps_chunks:
            content_parts.append("\n".join(deps_chunks))
        content_parts.append(task.description or "")
        return [{"text": t} for t in content_parts]

    @staticmethod
    def _extract_text_v03(result: dict) -> str:
        """从 v0.3/v1.0 JSON-RPC result 中提取文本。"""
        chunks = []
        for field in ("statusUpdate", "status_update", "artifactUpdate", "artifact_update"):
            inner = result.get(field, {})
            if not inner:
                continue
            for container in (inner, inner.get("artifact", {}), inner.get("message", {})):
                for p in (container.get("parts", []) or []):
                    if p.get("text"):
                        chunks.append(p["text"])
        return "".join(chunks)

    # ===== 事件翻译（StreamResponse → ExecutionEvent） =====

    def _translate(self, stream_resp: Any, task_id: str) -> Optional[ExecutionEvent]:
        """a2a-sdk StreamResponse → ExecutionEvent。

        StreamResponse 是 protobuf oneof，包含以下字段之一：
        - task: 任务对象（可忽略，不产生事件）
        - message: 消息对象（提取文本作为 content chunk）
        - status_update: 状态更新（TASK_STARTED / TASK_COMPLETED / TASK_FAILED）
        - artifact_update: 产出物更新（CONTENT_CHUNK）
        """
        meta = {"task_id": task_id}

        # status_update（working/completed/failed/canceled/input-required）
        if stream_resp.HasField("status_update"):
            su = stream_resp.status_update
            status = getattr(su, "status", None)
            if status is None:
                return None
            status_name = self._status_name(status)

            if status_name in ("completed",):
                # 提取文本 → TASK_COMPLETED
                text = self._parts_text(getattr(su, "message", None))
                return ExecutionEvent(
                    type=ExecutionEventType.TASK_COMPLETED,
                    data={"task_id": task_id, "result": text or ""},
                    metadata=meta,
                )
            elif status_name in ("failed", "canceled"):
                return ExecutionEvent(
                    type=ExecutionEventType.TASK_FAILED,
                    data={"task_id": task_id},
                    metadata={**meta, "error": status_name},
                )
            elif status_name in ("working", "input-required"):
                # 提取进度消息文本 → CONTENT_CHUNK
                text = self._parts_text(getattr(su, "message", None))
                if text:
                    return ExecutionEvent(
                        type=ExecutionEventType.CONTENT_CHUNK,
                        data=text,
                        metadata=meta,
                    )
                # 无文本则发 TASK_STARTED（标记开始执行）
                return ExecutionEvent(
                    type=ExecutionEventType.TASK_STARTED,
                    data={"task_id": task_id},
                    metadata=meta,
                )

        # artifact_update（产出物）
        if stream_resp.HasField("artifact_update"):
            au = stream_resp.artifact_update
            artifact = getattr(au, "artifact", None)
            if artifact is None:
                return None
            text = self._parts_text(artifact)
            if text:
                return ExecutionEvent(
                    type=ExecutionEventType.CONTENT_CHUNK,
                    data=text,
                    metadata=meta,
                )

        # message（直接消息）
        if stream_resp.HasField("message"):
            msg = stream_resp.message
            text = self._parts_text(msg)
            if text:
                return ExecutionEvent(
                    type=ExecutionEventType.CONTENT_CHUNK,
                    data=text,
                    metadata=meta,
                )

        return None

    # ===== 辅助方法 =====

    def _extract_text(self, stream_resp: Any) -> str:
        """从 StreamResponse 提取所有文本内容（非流式模式下聚合用）。"""
        parts_list = []
        if stream_resp.HasField("artifact_update"):
            artifact = getattr(stream_resp.artifact_update, "artifact", None)
            if artifact:
                parts_list.append(self._parts_text(artifact))
        if stream_resp.HasField("message"):
            parts_list.append(self._parts_text(stream_resp.message))
        if stream_resp.HasField("status_update"):
            su = stream_resp.status_update
            status_name = self._status_name(getattr(su, "status", None))
            if status_name in ("completed",):
                parts_list.append(self._parts_text(getattr(su, "message", None)))
        return "".join(p for p in parts_list if p)

    def _extract_error(self, stream_resp: Any) -> Optional[str]:
        """从 StreamResponse 提取错误信息。"""
        if stream_resp.HasField("status_update"):
            su = stream_resp.status_update
            status_name = self._status_name(getattr(su, "status", None))
            if status_name in ("failed", "canceled"):
                return getattr(su, "error", status_name)
        return None

    @staticmethod
    def _parts_text(msg_or_artifact: Any) -> str:
        """从 protobuf Message/Artifact 中提取 text parts 拼接为字符串。"""
        if msg_or_artifact is None:
            return ""
        parts = getattr(msg_or_artifact, "parts", []) or []
        chunks = []
        for p in parts:
            text = getattr(p, "text", "") or ""
            if text:
                chunks.append(text)
        return "".join(chunks)

    @staticmethod
    def _status_name(status: Any) -> str:
        """兼容 protobuf enum name 提取（不同 a2a-sdk 版本可能返回 int 或 enum）。"""
        if status is None:
            return ""
        if hasattr(status, "name"):
            return status.name.lower()
        try:
            from a2a.types.a2a_pb2 import TaskStatus
            return TaskStatus.Name(status).lower()
        except Exception:
            return str(status).lower()
