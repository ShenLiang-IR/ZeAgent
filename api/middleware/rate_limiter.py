"""多 worker 共享限流 Limiter 工厂。

根据 REDIS_URL 环境变量决定 storage backend：
- 有 REDIS_URL：用 Redis storage（多 worker 共享计数，4 worker 部署时限流正确）
- 无 REDIS_URL：用 in-memory（向下兼容本地开发，无需 Redis）

Redis 故障时 swallow_errors=True（fail-open）：限流系统故障时放行请求，
不阻塞主服务；超限仍返回 429（正常限流行为，不是错误）。

设计参见 docs/specs/2026-07-19-rate-limit-design.md（本期扩展 Redis storage）。
"""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# 默认限流：per-IP 100/min
# webhook 入站端点等高频场景可在路由层 @limiter.limit() 单独配置更高限额
DEFAULT_LIMITS = ["100 per minute"]


def create_limiter() -> Limiter:
    """创建限流器。

    REDIS_URL 环境变量存在时启用 Redis storage（多 worker 共享），
    否则用 in-memory（向下兼容本地开发，无需 Redis 依赖）。

    Returns:
        Limiter 实例
    """
    redis_url = os.getenv("REDIS_URL")
    kwargs = {
        "key_func": get_remote_address,
        "default_limits": DEFAULT_LIMITS,
    }
    if redis_url:
        kwargs["storage_uri"] = redis_url
        # Redis 故障 fail-open：限流检查出错时放行，避免限流系统故障拖垮主服务
        # （超限返回 429 是正常行为，不受影响；只有 Redis 连接失败时才放行）
        kwargs["swallow_errors"] = True
    return Limiter(**kwargs)
