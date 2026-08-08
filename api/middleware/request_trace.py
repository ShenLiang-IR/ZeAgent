"""请求追踪中间件：为每个 HTTP 请求生成/传递 X-Request-ID。

- 从请求头 X-Request-ID 读取（上游已生成时复用）
- 无则生成 UUID 短格式
- 注入到 loguru contextvar，使同一请求内所有日志都带 request_id
- 响应头回传 X-Request-ID 供客户端关联
"""
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from loguru import logger
from contextvars import ContextVar

# 请求级 contextvar（与 logging_utils 的 trace_id 对齐）
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestTraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 从请求头读取或生成
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_ctx.set(rid)

        # 注入到 loguru extra，使同一请求内所有日志带 request_id
        with logger.contextualize(request_id=rid, trace_id=rid):
            try:
                response: Response = await call_next(request)
                response.headers["X-Request-ID"] = rid
                return response
            finally:
                request_id_ctx.reset(token)


def get_request_id() -> str:
    """获取当前请求的 request_id（非请求上下文中返回 '-'）。"""
    return request_id_ctx.get()
