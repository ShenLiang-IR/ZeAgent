"""审计日志中间件：自动拦截 /api/admin/* 写操作，异步写 tb_audit_log。

设计参见 docs/specs/2026-07-19-audit-log-design.md §4。

功能（第二期增强）：
- 拦截 POST/PUT/DELETE/PATCH 到 /api/admin/*（排除 /api/admin/audit/* 自身）
- 从 Authorization header 解析 user_id（失败记 "anonymous"）
- 从 path 推断 resource_type/resource_id/action
- PUT/DELETE 前查旧记录写入 before_data（按 resource_type 路由到对应 repository）
- response 后读 body 写入 after_data（仅非流式响应，SSE 流不读避免破坏）
- 异步写审计日志（asyncio.create_task，不阻塞响应）
"""
import asyncio
import json
import re
import time

from fastapi import Request
from loguru import logger

WRITE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}
METHOD_TO_ACTION = {
    "POST": "create",
    "PUT": "update",
    "DELETE": "delete",
    "PATCH": "update",
}
# 特殊路径末尾覆盖 action（如 /enable /disable /test）
PATH_SUFFIX_ACTIONS = {"enable", "disable", "toggle", "test", "reload"}


async def audit_middleware(request: Request, call_next):
    """FastAPI middleware：拦截 admin 写操作，写审计日志（含 before/after_data）。"""
    if not _should_audit(request):
        return await call_next(request)

    # 解析 user_id（从 Authorization header，同步调用）
    user_id, username = _resolve_user(request)
    # 解析 resource_type / resource_id / action
    resource_type, resource_id, action = _parse_path(request)

    # 查 before_data：PUT/DELETE 时有旧记录，POST 创建时为 None
    before_data = _fetch_record(resource_type, resource_id)

    started = time.monotonic()
    response = await call_next(request)
    duration_ms = int((time.monotonic() - started) * 1000)

    # after_data：PUT 更新查修改后记录（与 before 对称看变更）；其他读 response body
    after_data = await _fetch_after_data(response, resource_type, resource_id, action)

    # 异步写审计（不阻塞响应）
    asyncio.create_task(_write_audit(
        user_id=user_id,
        username=username,
        http_method=request.method,
        path=str(request.url.path),
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        before_data=before_data,
        after_data=after_data,
        client_ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
        status_code=response.status_code,
        duration_ms=duration_ms,
    ))
    return response


def _should_audit(request: Request) -> bool:
    """是否需要审计：admin 写操作 + 非 audit 路径（避免递归）。"""
    if request.method not in WRITE_METHODS:
        return False
    path = request.url.path
    if not path.startswith("/api/admin"):
        return False
    # 排除 /api/admin/audit/* 自身（避免审计查询被审计）
    if path.startswith("/api/admin/audit"):
        return False
    return True


def _resolve_user(request: Request) -> tuple:
    """从 Authorization header 解析 user_id + username。失败记 'anonymous'。"""
    try:
        from utils.common.auth_dependencies import get_current_auth_result
        authorization = request.headers.get("authorization") or request.headers.get("Authorization")
        auth_result = get_current_auth_result(authorization=authorization)
        return auth_result.user_id, getattr(auth_result, "username", None) or auth_result.user_id
    except Exception as e:
        logger.debug(f"[Audit] resolve user failed (anonymous): {e}")
        return "anonymous", "anonymous"


def _looks_like_id(s: str) -> bool:
    """判断路径段是否像资源 ID（数字/UUID/带业务前缀），而非动作名/配置类型。

    - 纯数字（7, 2, 5）
    - UUID 格式（xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx）
    - 带业务前缀（MSG_/AUDIT_/RL_/USAGE_/SKL_/DISPATCH_ 等大写前缀+下划线+内容）
    """
    if not s:
        return False
    if s.isdigit():
        return True
    if re.match(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$', s):
        return True
    if re.match(r'^[A-Z]+_[a-zA-Z0-9_-]+$', s):
        return True
    return False


def _parse_path(request: Request) -> tuple:
    """从 path 推断 resource_type, resource_id, action。

    path 形如：
      /api/admin/triggers              → (trigger, None, create) [POST]
      /api/admin/triggers/{id}         → (trigger, {id}, update) [PUT]
      /api/admin/triggers/{id}/enable  → (trigger, {id}, enable) [POST]
      /api/admin/mcp/page              → (mcp, None, create)  ← page 是动作，非 ID
      /api/admin/mailbox/ack/MSG_xxx   → (mailbox, MSG_xxx, create)  ← 跳过 ack，取真实 ID
    """
    path = request.url.path
    parts = [p for p in path.split("/") if p]
    # parts[0]="api", parts[1]="admin", parts[2]=resource_type_plural
    if len(parts) < 3:
        return None, None, METHOD_TO_ACTION.get(request.method, "unknown")
    resource_type_plural = parts[2]
    # 简单单数化：去末尾 s（agents → agent, triggers → trigger）
    if resource_type_plural.endswith("s"):
        resource_type = resource_type_plural[:-1]
    else:
        resource_type = resource_type_plural
    # resource_id：取 parts[3:] 第一个"像 ID"的段（跳过动作名/配置类型段如 page/assign-role/agent/ack）
    # 避免 mcp/page→id=page、users/assign-role→id=assign-role、mailbox/ack/MSG_xxx→id=ack 这类误判
    resource_id = None
    for seg in parts[3:]:
        if seg in PATH_SUFFIX_ACTIONS:
            continue  # enable/disable/toggle/test/reload 等动作后缀
        if _looks_like_id(seg) and resource_id is None:
            resource_id = seg
        # 非 ID 段（page/assign-role/send/ack/list/notify/agent 等动作名或配置类型）不取作 resource_id
    # action：默认按 method 推断，特殊路径末尾覆盖
    action = METHOD_TO_ACTION.get(request.method, "unknown")
    if len(parts) >= 5 and parts[-1] in PATH_SUFFIX_ACTIONS:
        action = parts[-1]
    return resource_type, resource_id, action


# ─── before/after_data 捕获（第二期增强） ───

def _fetch_record(resource_type: str | None, resource_id: str | None) -> str | None:
    """按 resource_type 路由到对应 repository 查记录快照（before/after 复用）。

    Args:
        resource_type: trigger / agent / skill / mcp / ...
        resource_id: 业务 ID（trigger_id / agent pr_key_id / ...）

    Returns:
        JSON 字符串（记录快照）；无记录或查询失败返回 None
    """
    if not resource_type or not resource_id:
        return None
    try:
        row = None
        if resource_type == "trigger":
            from infrastructure.database.repositories.trigger_repository import TriggerRepository
            row = TriggerRepository().get_by_trigger_id(resource_id)
        elif resource_type == "agent":
            from infrastructure.database.repositories.agent_repository import AgentRepository
            row = AgentRepository().get_by_id(resource_id)
        elif resource_type == "skill":
            from infrastructure.database.repositories.skill_repository import SkillRepository
            row = SkillRepository().get_by_id(resource_id)
        elif resource_type == "mcp":
            from infrastructure.database.repositories.mcp_repository import McpRepository
            row = McpRepository().get_by_id(resource_id)
        elif resource_type == "mode":
            from infrastructure.database.repositories.mode_repository import ModeRepository
            row = ModeRepository().get_by_id(resource_id)
        elif resource_type == "api":
            from infrastructure.database.repositories.api_repository import ApiRepository
            row = ApiRepository().get_by_id(resource_id)
        # audit/usage/quota 等查询型资源无需 before_data（一般不通过 admin PUT/DELETE 改）
        if row:
            return json.dumps(row, ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning(f"[Audit] fetch before_data ({resource_type}/{resource_id}) failed: {e}")
    return None


async def _fetch_after_data(response, resource_type: str | None, resource_id: str | None, action: str) -> str | None:
    """after_data：PUT 更新查修改后记录（与 before_data 对称，便于对比变更）；其他读 response body。

    - action=update 且 resource_id 已知：查更新后记录（用户期望看变更后数据，而非 {"status":"success"} 响应体）
    - POST create（resource_id 通常 None）/ DELETE（已删）/ 查询失败：fallback 读 response body
    """
    if action == "update" and resource_type and resource_id:
        record = _fetch_record(resource_type, resource_id)
        if record:
            return record
    return await _read_response_body(response)


async def _read_response_body(response) -> str | None:
    """读 response body（POST/DELETE 等无 after 记录的场景）。

    admin 写操作返回 JSONResponse（短响应），可安全消费。
    流式响应（SSE）在 /api/chat/* 路径，middleware 已排除非 admin 路径，不会触发此函数。
    """
    try:
        # 普通 Response（JSONResponse / PlainTextResponse 继承 Response，有 body 属性）
        if hasattr(response, "body") and response.body:
            body = response.body
            if isinstance(body, bytes):
                return body.decode("utf-8", errors="replace")
            return str(body)
        # StreamingResponse：消费 body_iterator + 重新包装
        if hasattr(response, "body_iterator"):
            body_chunks = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                body_chunks.append(chunk)
            # 重新设置 body_iterator（让响应继续传给客户端）
            async def _replay():
                for chunk in body_chunks:
                    yield chunk
            response.body_iterator = _replay()
            body = b"".join(body_chunks)
            return body.decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug(f"[Audit] read response body failed (non-blocking): {e}")
    return None


async def _write_audit(**kwargs):
    """异步写 tb_audit_log。失败不抛异常（审计不应阻塞主流程）。"""
    try:
        from infrastructure.database.repositories.audit_repository import AuditRepository
        from utils.id_generator import generate_uuid
        AuditRepository().create(
            audit_id=f"AUDIT_{generate_uuid()[:16]}",
            **kwargs,
        )
    except Exception as e:
        logger.warning(f"[Audit] write failed: {e}")
