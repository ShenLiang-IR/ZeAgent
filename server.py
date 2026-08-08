import sys
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
agent_dir = Path(__file__).parent
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))
from utils.common.logging_utils import setup_agent_logging
setup_agent_logging()
from utils.config import get_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan：startup 加载触发器，shutdown 清理。

    设计参见 docs/specs/2026-07-19-trigger-registry-design.md §7.3。
    TriggerRegistry 是单例，load_from_db 从 tb_trigger 加载所有 enabled trigger。
    若触发器子系统初始化失败，不应阻塞 server 启动（捕获异常记录日志）。
    """
    # startup
    # 认证安全校验：生产模式拒绝裸奔配置（enable_permission_check=false / default_token 后门）
    # 不安全配置 raise RuntimeError 阻止启动（不吞，让 uvicorn 退出）；config 读取异常等不阻塞
    try:
        from utils.common.auth_safety import assert_auth_safety_from_config
        assert_auth_safety_from_config()
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"[Lifespan] auth safety check skipped (non-fatal): {e}", exc_info=True)
    # 三层可见性迁移（幂等：加列 + 迁移存量；失败不阻塞启动，查询层对 NULL 有回退）
    try:
        from infrastructure.database.migrate_visibility import migrate_visibility
        migrate_visibility()
    except Exception as e:
        logger.error(f"[Lifespan] visibility migration failed (non-fatal): {e}", exc_info=True)
    try:
        from services.trigger.registry import TriggerRegistry
        registry = TriggerRegistry.get_instance()
        loaded = await registry.load_from_db()
        logger.info(f"[Lifespan] {loaded} triggers loaded")
        # W4: leader_election 启用时启动 heartbeat（续约 + 失去/获得 leader 时重载非 cron）
        from services.trigger.leader_election import TriggerLeaderElection
        if TriggerLeaderElection.enabled():
            import asyncio as _aio
            app.state.trigger_heartbeat = _aio.create_task(registry.start_heartbeat())
    except Exception as e:
        logger.error(f"[Lifespan] trigger registry load failed (non-fatal): {e}", exc_info=True)
    # 独立轻量定时任务（不通过 tb_trigger，直接 lifespan 启动；失败不阻塞 server）
    try:
        from services.trigger.memory_decay_trigger import MemoryDecayTrigger
        await MemoryDecayTrigger().start()
    except Exception as e:
        logger.error(f"[Lifespan] memory_decay_trigger start failed (non-fatal): {e}", exc_info=True)
    try:
        from services.trigger.memory_preference_summary_trigger import MemoryPreferenceSummaryTrigger
        await MemoryPreferenceSummaryTrigger().start()
    except Exception as e:
        logger.error(f"[Lifespan] memory_preference_summary_trigger start failed (non-fatal): {e}", exc_info=True)
    try:
        from services.trigger.memory_consolidation_trigger import MemoryConsolidationTrigger
        await MemoryConsolidationTrigger().start()
    except Exception as e:
        logger.error(f"[Lifespan] memory_consolidation_trigger start failed (non-fatal): {e}", exc_info=True)
    # 配置文件热重载监听：直接编辑 config/ 下运行时配置文件后自动 reload，无需重启
    try:
        from utils.config.config_watcher import start_config_watcher
        await start_config_watcher()
    except Exception as e:
        logger.error(f"[Lifespan] config_watcher start failed (non-fatal): {e}", exc_info=True)
    # WebSocket Redis 跨 worker 订阅（有 REDIS_URL 时启动）
    try:
        from api.ws_approvals import _redis_subscriber
        import asyncio as _aio
        app.state.ws_redis_sub = _aio.create_task(_redis_subscriber())
    except Exception as e:
        logger.error(f"[Lifespan] WS redis subscriber start failed (non-fatal): {e}", exc_info=True)
    yield
    # shutdown
    try:
        ws_sub = getattr(app.state, "ws_redis_sub", None)
        if ws_sub:
            ws_sub.cancel()
    except Exception:
        pass
    try:
        # 停止配置文件热重载监听器
        from utils.config.config_watcher import stop_config_watcher
        await stop_config_watcher()
    except Exception as e:
        logger.error(f"[Lifespan] config_watcher stop failed: {e}", exc_info=True)
    try:
        # 关闭 MCP 进程池
        from tools.data_providers.mcp_client.process_pool import McpProcessPool
        await McpProcessPool.get_instance().shutdown()
    except Exception as e:
        logger.error(f"[Lifespan] MCP process pool shutdown failed: {e}", exc_info=True)
    try:
        # W4: 取消 heartbeat
        hb = getattr(app.state, "trigger_heartbeat", None)
        if hb:
            hb.cancel()
        from services.trigger.registry import TriggerRegistry
        await TriggerRegistry.get_instance().shutdown()
        logger.info("[Lifespan] triggers stopped")
    except Exception as e:
        logger.error(f"[Lifespan] trigger registry shutdown failed: {e}", exc_info=True)


app = FastAPI(title="Agent API", description="Agent API Server", lifespan=lifespan)
# 安全：CORS allow_origins 优先环境变量 CORS_ORIGINS（逗号分隔），回退本地开发白名单，缺失时告警
import os as _os
_cors_env = _os.environ.get("CORS_ORIGINS", "")
if _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
else:
    _cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    logger.warning(
        "[Security] CORS_ORIGINS 未设置，回退本地白名单（生产必须设环境变量 CORS_ORIGINS）"
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

# ─── 请求追踪中间件：注入 X-Request-ID + loguru contextvar ───
from api.middleware.request_trace import RequestTraceMiddleware
app.add_middleware(RequestTraceMiddleware)

# ─── Prometheus 监控指标 ───
# 设计参见 docs/specs/2026-07-19-monitoring-design.md（本期新建）
# 暴露 /metrics 端点，记录 HTTP 请求 QPS/延迟/状态码
# Prometheus 定时抓取，Grafana 可视化
from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    excluded_handlers=["/metrics"],  # 不记录 /metrics 自身的请求
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# ─── API rate limit（slowapi） ───
# 设计参见 docs/specs/2026-07-19-rate-limit-design.md
# per-IP 默认 100/min；webhook 入站端点第二期单独配置更高限额
# storage backend 由 REDIS_URL 决定：有则 Redis（多 worker 共享计数），
# 无则 in-memory（向下兼容本地开发）。Dockerfile 4 worker 部署时需配 REDIS_URL。
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.middleware.rate_limiter import create_limiter

limiter = create_limiter()
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# 审计中间件：自动拦截 /api/admin/* 写操作，异步写 tb_audit_log
# 设计参见 docs/specs/2026-07-19-audit-log-design.md
from api.middleware.audit_middleware import audit_middleware
app.middleware("http")(audit_middleware)

# 注册 API 路由
from api import admin_router, chat_router_main
from api.plan.review_routes import router as plan_review_router
from api.rag.rag_routes import router as rag_router
from api.model_routes import router as model_router
from api.auth.auth_routes import router as auth_router
from api.auth.admin_routes import router as admin_rbac_router
from api.text2sql_routes import router as text2sql_router
from api.openai_compat import router as openai_router
from api.approval.tool_approval_routes import router as tool_approval_router
app.include_router(admin_router)
app.include_router(chat_router_main)
app.include_router(plan_review_router)
app.include_router(rag_router)
app.include_router(model_router)
app.include_router(auth_router)
app.include_router(admin_rbac_router)
app.include_router(text2sql_router)
app.include_router(openai_router)
app.include_router(tool_approval_router)

# ─── WebSocket 端点 ───
from api.ws_approvals import ws_approvals_endpoint
app.add_api_websocket_route("/ws/approvals", ws_approvals_endpoint)

# ─── 全局 exception handler：统一错误响应格式 ───
# 设计目标：所有 HTTPException / RequestValidationError / 未捕获异常
# 都返回统一格式 {code, message, data}，便于前端解析
# 成功响应仍是 wrap_response（{code: "000...", message: "success", data: ...}）
# 失败响应 code="999...", message=错误描述, data=null
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from api.admin.base import wrap_response
from services.quota_guard import QuotaExceededError


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTPException → 统一 {code, message, data} 格式。"""
    return JSONResponse(
        status_code=exc.status_code,
        content=wrap_response(success=False, message=str(exc.detail), data=None),
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Rate limit（429）→ 统一格式，前端 handleApiError 弹"请求过于频繁"。"""
    return JSONResponse(
        status_code=429,
        content=wrap_response(success=False, message="请求过于频繁，请稍后重试", data=None),
    )


@app.exception_handler(QuotaExceededError)
async def quota_exceeded_handler(request: Request, exc: QuotaExceededError):
    """配额超限 → 429 + 统一格式（block 模式超限由 enforce_quota 抛出）。"""
    logger.warning(f"[Quota] {request.method} {request.url.path}: workspace={exc.workspace_id} {exc}")
    return JSONResponse(
        status_code=429,
        content=wrap_response(success=False, message=str(exc), data=None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """请求体校验失败 → 统一格式（422）。"""
    # 把 pydantic 校验错误拼成可读字符串
    errors = "; ".join(
        f"{'.'.join(str(x) for x in e.get('loc', []))}: {e.get('msg', '')}"
        for e in exc.errors()
    )
    return JSONResponse(
        status_code=422,
        content=wrap_response(success=False, message=f"参数校验失败: {errors}", data=None),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """未捕获异常 → 统一格式 500，记日志不暴露堆栈给客户端。"""
    logger.error(f"[Unhandled] {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=wrap_response(success=False, message=f"内部错误: {type(exc).__name__}", data=None),
    )

@app.get("/")
async def root():
    return {
        "message": "Agent API Server",
        "status": "running",
        "version": "0.8.0",
        "docs": "/docs",
        "routes_count": len(app.routes),
    }


@app.get("/health")
async def health_check():
    """深度健康检查：验证 DB 连接 + 关键依赖可用性。

    用于 Docker HEALTHCHECK 和负载均衡器探针。
    返回 200 表示服务健康，503 表示有依赖不可用。
    """
    checks = {}
    all_ok = True

    # DB 连接检查
    try:
        from sqlalchemy import text
        from infrastructure.database.sessions import get_config_session
        with get_config_session() as s:
            s.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"fail: {e}"
        all_ok = False

    # Redis 连接检查（可选，无 Redis 视为 ok）
    try:
        import os as _os2
        redis_url = _os2.getenv("REDIS_URL")
        if redis_url:
            import redis
            r = redis.from_url(redis_url, decode_responses=True)
            r.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "skipped (no REDIS_URL)"
    except Exception as e:
        checks["redis"] = f"fail: {e}"
        all_ok = False

    status_code = 200 if all_ok else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={"status": "healthy" if all_ok else "unhealthy", "checks": checks}
    )

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("Agent API Server")
    print("=" * 60)
    print(f"  LLM Base URL: {get_config('llm.default.base_url')}")
    print(f"  LLM Model:    {get_config('llm.default.model')}")
    print(f"  Backend:      {get_config('agent.backend', 'langgraph')}")
    print("=" * 60)
    print(f"  Server:  http://localhost:8072")
    print(f"  Docs:    http://localhost:8072/docs")
    print("=" * 60)
    uvicorn.run(
        app="server:app", host="0.0.0.0", port=8072, log_level="info", reload=True,
        reload_dirs=["."],
        reload_excludes=["skill_registry/*", "data/*", "temp/*", "logs/*", "__pycache__/*"],
    )