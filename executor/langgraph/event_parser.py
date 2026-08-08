from __future__ import annotations
import json
from typing import Any, AsyncGenerator, Dict, Optional
from langchain_core.messages import AIMessage, ToolMessage
from loguru import logger
from utils.message.message_extractor import extract_reasoning_from_content
from .task_context import ExecutionEvent
from ..stream_helper import send_sse_data


class LangGraphEventParser:
    """LangGraph 流事件解析器。

    thinking 标签清理统一走 utils.message.message_extractor.extract_reasoning_from_content
    （已删除 StreamingThinkingCleaner 死代码——process_streaming_text 全仓零调用）。
    """

    def __init__(self, task_id: str):
        self.task_id = task_id

    async def parse_stream(
        self,
        event_stream: AsyncGenerator[Dict[str, Any], None]
    ) -> AsyncGenerator[ExecutionEvent, None]:
        async for event in event_stream:
            async for evt in self.parse_event(event):
                yield evt

    async def parse_event(
        self,
        event: Dict[str, Any]
    ) -> AsyncGenerator[ExecutionEvent, None]:
        try:
            node_name = self._extract_node_name(event)
            if node_name in ("agent", "model"):
                async for evt in self._parse_agent_event(event, node_name):
                    yield evt
            elif node_name == "tools":
                async for evt in self._parse_tools_event(event):
                    yield evt
            elif "__start__" in event or "__end__" in event:
                yield self._create_lifecycle_event(event)
            else:
                logger.debug(f"[EventParser] : {node_name}")
        except Exception as e:
            logger.error(f"[EventParser] : {e}, event: {event}")
            yield ExecutionEvent(
                type="error",
                data=str(e),
                metadata={"task_id": self.task_id, "raw_event": str(event)}
            )

    def _extract_node_name(self, event: Dict[str, Any]) -> str:
        keys = list(event.keys())
        if "__start__" in keys:
            return "__start__"
        elif "__end__" in keys:
            return "__end__"
        elif len(keys) == 1:
            return keys[0]
        return ""

    async def _parse_agent_event(
        self,
        event: Dict[str, Any],
        node_name: str = "agent"
    ) -> AsyncGenerator[ExecutionEvent, None]:
        state = event.get(node_name, {})
        messages = state.get("messages", [])
        if not messages:
            return
        for msg in messages:
            if isinstance(msg, AIMessage):
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        tc_name = tc.get("name", "unknown")
                        tc_args = tc.get("args", {})
                        args_str = json.dumps(tc_args, ensure_ascii=False, default=str)
                        if len(args_str) > 500:
                            args_str = args_str[:500] + f"...({len(args_str)} chars)"
                        logger.info(f"[EventParser] 🔧 Tool call: {tc_name} | args={args_str}")
                    cleaned_content, reasoning = self._clean_and_extract_reasoning(msg.content or "")
                    yield ExecutionEvent(
                        type="tool_call",
                        data={
                            "tool_calls": [
                                {
                                    "id": tc.get("id"),
                                    "name": tc.get("name"),
                                    "args": tc.get("args", {}),
                                }
                                for tc in msg.tool_calls
                            ],
                            "reasoning": reasoning,
                            "content": cleaned_content,
                        },
                        metadata={"task_id": self.task_id}
                    )
                elif msg.content:
                    cleaned_content = self._clean_content(msg.content)
                    if cleaned_content:
                        yield ExecutionEvent(
                            type="message",
                            data=cleaned_content,
                            metadata={"task_id": self.task_id}
                        )

    async def _parse_tools_event(
        self,
        event: Dict[str, Any]
    ) -> AsyncGenerator[ExecutionEvent, None]:
        state = event.get("tools", {})
        messages = state.get("messages", [])
        for msg in messages:
            if isinstance(msg, ToolMessage):
                content_str = str(msg.content or "")
                display_len = len(content_str)
                truncated = content_str[:500]
                if display_len > 500:
                    truncated += f"...({display_len} chars)"
                status = getattr(msg, "status", "success")
                logger.info(
                    f"[EventParser] ✅ Tool result: {msg.name} | "
                    f"status={status} | content={truncated}"
                )
                yield ExecutionEvent(
                    type="tool_result",
                    data={
                        "tool_name": msg.name,
                        "content": msg.content,
                        "tool_call_id": msg.tool_call_id,
                        "status": getattr(msg, "status", "success"),
                    },
                    metadata={"task_id": self.task_id}
                )

    def _create_lifecycle_event(self, event: Dict[str, Any]) -> ExecutionEvent:
        if "__start__" in event:
            return ExecutionEvent(
                type="status",
                data="started",
                metadata={"task_id": self.task_id}
            )
        elif "__end__" in event:
            return ExecutionEvent(
                type="status",
                data="completed",
                metadata={"task_id": self.task_id}
            )
        return ExecutionEvent(
            type="status",
            data="unknown",
            metadata={"task_id": self.task_id}
        )

    def _clean_content(self, content: str) -> str:
        """清理 thinking 标签，委托 _clean_and_extract_reasoning。"""
        return self._clean_and_extract_reasoning(content)[0]

    def _clean_and_extract_reasoning(self, content: str) -> tuple[str, Optional[str]]:
        if not content:
            return content, None
        try:
            reasoning, cleaned = extract_reasoning_from_content(content)
            return cleaned, reasoning
        except Exception as e:
            logger.warning(f"[EventParser] : {e}")
            return content, None


def format_event_for_sse(event: ExecutionEvent) -> str:
    data = {
        "type": event.type,
        "data": event.data,
        "metadata": event.metadata,
    }
    return send_sse_data(data)
