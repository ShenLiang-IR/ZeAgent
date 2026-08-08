"""Token jti 吊销服务（Redis 黑名单）。

根治 #5：已签发 token 可主动吊销（密钥泄露/用户登出/管理员封禁）。
- revoke(jti, ttl): 加入 Redis 黑名单（SADD + EXPIRE，ttl 后自动清理）
- is_revoked(jti): SISMEMBER 查询
- Redis 不可用时降级 in-memory（单进程，重启失效——标注限制）

多 worker 共享需 Redis（REDIS_URL）；in-memory 仅单进程，适合开发/降级。
"""
from __future__ import annotations

import os
from typing import Optional

from loguru import logger

_BLACKLIST_KEY = "jwt:jti:blacklist"
_DEFAULT_TTL = 7 * 24 * 3600  # 默认 7 天（对齐 token 过期）


class TokenRevocationService:
    _instance: Optional["TokenRevocationService"] = None

    def __init__(self):
        self._redis = self._init_redis()
        self._memory_fallback: set[str] = set()

    def _init_redis(self):
        try:
            import redis
            url = os.getenv("REDIS_URL", "")
            if not url:
                logger.warning(
                    "[TokenRevocation] REDIS_URL 未设置，降级 in-memory"
                    "（单进程，重启失效，生产建议配置 REDIS_URL）"
                )
                return None
            r = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
            r.ping()
            logger.info("[TokenRevocation] Redis 已连接，jti 黑名单多 worker 共享")
            return r
        except Exception as e:
            logger.warning(f"[TokenRevocation] Redis 不可用，降级 in-memory: {e}")
            return None

    @classmethod
    def get_instance(cls) -> "TokenRevocationService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（测试/热重载用）。"""
        cls._instance = None

    def revoke(self, jti: str, ttl: int = _DEFAULT_TTL) -> None:
        """吊销 jti：加入黑名单，ttl 秒后自动过期清理。"""
        if not jti:
            return
        if self._redis is not None:
            self._redis.sadd(_BLACKLIST_KEY, jti)
            self._redis.expire(_BLACKLIST_KEY, ttl)
        else:
            self._memory_fallback.add(jti)
        logger.info(f"[TokenRevocation] jti 已吊销: {jti[:8]}...")

    def is_revoked(self, jti: Optional[str]) -> bool:
        """查询 jti 是否已吊销。空 jti（旧 token 兼容）不查不拒。"""
        if not jti:
            return False
        if self._redis is not None:
            return bool(self._redis.sismember(_BLACKLIST_KEY, jti))
        return jti in self._memory_fallback
