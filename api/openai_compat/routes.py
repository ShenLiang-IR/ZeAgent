"""OpenAI 兼容 API（/v1/chat/completions, /v1/models）。

将 OpenAI 格式请求映射到内部 AgentService.chat，
支持流式（SSE）与非流式，兼容 OpenAI SDK 调用。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from loguru import logger

from utils.common.auth_dependencies import (
    get_effective_authorization,
    get_current_user_permissions,
)
from utils.llm.llm_factory import get_default_llm
from services import AgentService
from services.quota_guard import enforce_chat_quota, get_degrade_llm
from core.security.content_filter import filter_content, log_filter_event

router = APIRouter(prefix="/v1", tags=["openai-compat"])


# ── 请求 / 响应模型（OpenAI 格式） ──

class ChatMessage(BaseModel):
    role: str = "user"
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = Field(default="default", description="模型名 → 内部 agent_name 映射")
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None


class ChatCompletionResponseChoice(BaseModel):
    index: int = 0
    message: ChatMessage = Field(default_factory=ChatMessage)
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str = ""
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: list[ChatCompletionResponseChoice] = []


class ModelItem(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "organization"


class ModelListResponse(BaseModel):
    object: str = "list"
    data: list[ModelItem] = []


# ── model → agent 映射（配置驱动 + 默认回退） ──

def _resolve_agent_from_model(model: str) -> tuple[str | None, dict | None]:
    """model 名 → (agent_name, agent_config)。未命中返回 default agent。"""
    from utils.config import get_config
    from utils.config import get_config_db

    # 首先查配置 openai_compat.model_map.{model} → agent_name
    model_map = get_config("openai_compat.model_map", {}) or {}
    agent_name = model_map.get(model)
    if agent_name:
        config_db = get_config_db()
        cfg = config_db.agents.get_by_name(agent_name)
        if cfg and cfg.get("status") == "1":
            logger.debug(f"[OpenAICompat] model={model} → agent={agent_name}")
            return agent_name, cfg

    # 回退：openai_compat.default_agent 或第一个启用的 agent
    default_agent = get_config("openai_compat.default_agent", "")
    config_db = get_config_db()
    if default_agent:
        cfg = config_db.agents.get_by_name(default_agent)
        if cfg and cfg.get("status") == "1":
            logger.debug(f"[OpenAICompat] model={model} → fallback default agent={default_agent}")
            return default_agent, cfg

    # 最终回退：第一个启用 agent
    all_agents = config_db.agents.get_all(enabled_only=True) or []
    if all_agents:
        first = all_agents[0]
        name = first.get("agent_name", "default")
        logger.debug(f"[OpenAICompat] model={model} → fallback first agent={name}")
        return name, first

    return None, None


# ── OpenAI SSE 格式化 ──

def _sse_event(data: dict, stream: bool = False) -> str:
    """OpenAI SSE 格式：data: {json}\n\n。stream=False 时只用一次。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _openai_stream_chunk(
    chunk_id: str, model: str, created: int,
    delta_role: str | None, delta_content: str | None,
    finish_reason: str | None = None,
) -> dict:
    """构建一个 OpenAI stream chunk。"""
    delta = {}
    if delta_role:
        delta["role"] = delta_role
    if delta_content:
        delta["content"] = delta_content
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason,
        }],
    }


# ── 端点 ──

@router.post("/chat/completions", response_model=None)
async def chat_completions(
    request: ChatCompletionRequest,
    authorization: Optional[str] = Header(None),
):
    """OpenAI 兼容聊天补全（/v1/chat/completions）。

    将 OpenAI 格式请求映射到内部 AgentService.chat，
    支持 stream=true 时返回 SSE 事件流。
    """
    effective_auth = get_effective_authorization(authorization)
    # 配额预检（复用现有机制）
    internal_msgs = [{"role": m.role, "content": m.content} for m in request.messages]
    enforce_chat_quota(effective_auth, internal_msgs)

    # model → agent 映射
    agent_name, agent_config = _resolve_agent_from_model(request.model)
    if not agent_name:
        raise HTTPException(status_code=400, detail=f"No agent available for model '{request.model}'")

    try:
        user_perms = get_current_user_permissions(authorization)
        user_id = user_perms.user_id
    except Exception:
        user_id = "openai_user"

    # 内容安全
    last_user_msg = next((m.content for m in request.messages if m.role == "user"), "")
    if last_user_msg:
        fr = filter_content(last_user_msg)
        if fr.blocked:
            log_filter_event(last_user_msg, fr.matched, "input", str(user_id), "", None)
            raise HTTPException(status_code=400, detail=f"Content filtered: {fr.reason}")

    # 转换 messages → 内部格式（取最后一条 user 消息作为查询）
    from api.chat.message_utils import convert_to_langchain_messages
    langchain_messages = convert_to_langchain_messages(internal_msgs)

    agent_service = AgentService(
        session_id=f"openai_{uuid.uuid4().hex[:8]}",
        user_id=user_id,
        llm_model=get_degrade_llm(None) or get_default_llm(),
        skip_memory=True,
    )

    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    if request.stream:
        return StreamingResponse(
            _stream_openai_response(
                agent_service, langchain_messages, agent_name, agent_config,
                request.model, chunk_id, created,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # 非流式
    result_messages = await agent_service.chat(
        messages=langchain_messages,
        agent=agent_name,
        agent_config=agent_config,
        deep_thinking=False,
        user_id=user_id,
        request_messages=internal_msgs,
    )
    from langchain_core.messages import AIMessage
    ai_content = ""
    for msg in reversed(result_messages or []):
        if isinstance(msg, AIMessage):
            ai_content = msg.content if hasattr(msg, "content") else str(msg)
            break

    return ChatCompletionResponse(
        id=chunk_id,
        created=created,
        model=request.model,
        choices=[ChatCompletionResponseChoice(
            message=ChatMessage(role="assistant", content=ai_content),
            finish_reason="stop",
        )],
    )


async def _stream_openai_response(
    agent_service: AgentService,
    langchain_messages: list,
    agent_name: str,
    agent_config: dict | None,
    model: str,
    chunk_id: str,
    created: int,
):
    """OpenAI SSE 流式响应生成器。"""
    try:
        # 用 AgentService 的内部流式方法（如果存在）或非流式
        # 当前 AgentService 有 chat (非流式) 和 chat_stream (流式)
        if hasattr(agent_service, "chat_stream"):
            collected = ""
            async for chunk in agent_service.chat_stream(
                messages=langchain_messages,
                agent=agent_name,
                agent_config=agent_config,
                deep_thinking=False,
            ):
                if isinstance(chunk, str):
                    collected += chunk
                    yield _sse_event(_openai_stream_chunk(
                        chunk_id, model, created,
                        delta_role="assistant" if not collected else None,
                        delta_content=chunk,
                    ))
            # 最后一块：finish_reason
            yield _sse_event(_openai_stream_chunk(
                chunk_id, model, created,
                delta_role=None, delta_content=None,
                finish_reason="stop",
            ))
        else:
            # fallback：非流式结果作为单次 chunk 发送
            result = await agent_service.chat(
                messages=langchain_messages,
                agent=agent_name,
                agent_config=agent_config,
                deep_thinking=False,
            )
            from langchain_core.messages import AIMessage
            ai_content = ""
            for msg in reversed(result or []):
                if isinstance(msg, AIMessage):
                    ai_content = msg.content if hasattr(msg, "content") else str(msg)
                    break
            yield _sse_event(_openai_stream_chunk(
                chunk_id, model, created,
                delta_role="assistant", delta_content=ai_content,
            ))
            yield _sse_event(_openai_stream_chunk(
                chunk_id, model, created,
                delta_role=None, delta_content=None,
                finish_reason="stop",
            ))
    except Exception as e:
        logger.error(f"[OpenAICompat] stream error: {e}", exc_info=True)
        yield _sse_event({"error": str(e)})
        yield _sse_event(_openai_stream_chunk(chunk_id, model, created, None, None, "error"))
    yield "data: [DONE]\n\n"


@router.get("/models", response_model=ModelListResponse)
async def list_models(authorization: Optional[str] = Header(None)):
    """OpenAI 兼容模型列表（/v1/models）。返回所有启用 agent 作为可用 `id`。"""
    from utils.config import get_config_db
    config_db = get_config_db()
    agents = config_db.agents.get_all(enabled_only=True) or []
    created = int(time.time())
    items = [
        ModelItem(id=a.get("agent_name", f"agent_{i}"), created=created)
        for i, a in enumerate(agents)
    ]
    if not items:
        items = [ModelItem(id="default", created=created)]
    return ModelListResponse(data=items)
