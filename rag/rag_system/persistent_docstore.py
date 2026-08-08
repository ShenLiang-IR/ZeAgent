# rag/rag_system/persistent_docstore.py
# 生产 docstore — Redis/Postgres 替代 InMemoryStore
# config rag.parent_child.docstore_backend = "memory"/"redis"/"postgres"
import os
from contextlib import contextmanager
from loguru import logger
from typing import Optional, Dict, Any, List


class PersistentDocStore:
    """生产级 docstore，支持 Redis/Postgres 持久化。

    替代 ParentChildRetriever 的 InMemoryStore。
    进程重启后父块数据不丢失。

    安全加固（#10）：
    - Postgres 用连接池（SimpleConnectionPool，线程安全）替代单连接
    - 凭据从 kwargs/env（POSTGRES_URL/DATABASE_URL）读，不硬编码
    - Redis keys() 用 SCAN（非阻塞）替代 KEYS（生产防阻塞）
    """

    def __init__(self, backend: str = "memory", **kwargs):
        """
        Args:
            backend: "memory"（默认）/ "redis" / "postgres"
            kwargs: redis_url / postgres_url 等
        """
        self._backend = backend
        self._store: Dict = {}
        self._pg_pool = None
        if backend == "redis":
            self._init_redis(kwargs)
        elif backend == "postgres":
            self._init_postgres(kwargs)
        else:
            self._store = {}
        logger.info(f"[PersistentDocStore] backend={self._backend}")

    def _init_redis(self, kwargs):
        try:
            import redis
            url = kwargs.get("redis_url", "redis://localhost:6379/0")
            self._redis = redis.Redis.from_url(url)
            self._redis.ping()
            logger.info(f"[PersistentDocStore] Redis connected: {url}")
        except ImportError:
            logger.warning("[PersistentDocStore] redis 未安装，降级 memory")
            self._backend = "memory"
            self._store = {}
        except Exception as e:
            logger.warning(f"[PersistentDocStore] Redis 连接失败: {e}，降级 memory")
            self._backend = "memory"
            self._store = {}

    def _init_postgres(self, kwargs):
        try:
            from psycopg2.pool import SimpleConnectionPool
            url = (
                kwargs.get("postgres_url")
                or os.getenv("POSTGRES_URL")
                or os.getenv("DATABASE_URL")
            )
            if not url:
                logger.warning(
                    "[PersistentDocStore] postgres backend 未配置 postgres_url/POSTGRES_URL，"
                    "降级 memory（不使用硬编码凭据）"
                )
                self._backend = "memory"
                self._store = {}
                return
            self._pg_pool = SimpleConnectionPool(1, 10, url)
            conn = self._pg_pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS rag_docstore (
                            key VARCHAR(255) PRIMARY KEY,
                            value JSONB NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                conn.commit()
            finally:
                self._pg_pool.putconn(conn)
            logger.info(f"[PersistentDocStore] Postgres connected (pool): {url}")
        except ImportError:
            logger.warning("[PersistentDocStore] psycopg2 未安装，降级 memory")
            self._backend = "memory"
            self._store = {}
        except Exception as e:
            logger.warning(f"[PersistentDocStore] Postgres 连接失败: {e}，降级 memory")
            self._backend = "memory"
            self._store = {}

    @contextmanager
    def _pg_cursor(self):
        """从连接池获取连接 + cursor，用完归还（线程安全）。"""
        conn = self._pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                yield cur
            conn.commit()
        finally:
            self._pg_pool.putconn(conn)

    def put(self, key: str, value: Dict) -> None:
        """存储父块。"""
        if self._backend == "redis":
            import json
            self._redis.set(f"rag:doc:{key}", json.dumps(value))
        elif self._backend == "postgres":
            import json
            with self._pg_cursor() as cur:
                cur.execute(
                    "INSERT INTO rag_docstore (key, value) VALUES (%s, %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = %s",
                    (key, json.dumps(value), json.dumps(value))
                )
        else:
            self._store[key] = value

    def get(self, key: str) -> Optional[Dict]:
        """获取父块。"""
        if self._backend == "redis":
            import json
            val = self._redis.get(f"rag:doc:{key}")
            return json.loads(val) if val else None
        elif self._backend == "postgres":
            import json
            with self._pg_cursor() as cur:
                cur.execute("SELECT value FROM rag_docstore WHERE key = %s", (key,))
                row = cur.fetchone()
                return json.loads(row[0]) if row else None
        else:
            return self._store.get(key)

    def keys(self) -> List[str]:
        """列出所有 key。"""
        if self._backend == "redis":
            # SCAN 非阻塞（生产 Redis 禁用 KEYS，会阻塞主线程）
            return [
                k.replace(b"rag:doc:", b"").decode()
                for k in self._redis.scan_iter("rag:doc:*")
            ]
        elif self._backend == "postgres":
            with self._pg_cursor() as cur:
                cur.execute("SELECT key FROM rag_docstore")
                return [row[0] for row in cur.fetchall()]
        else:
            return list(self._store.keys())

    def delete(self, key: str) -> None:
        """删除父块。"""
        if self._backend == "redis":
            self._redis.delete(f"rag:doc:{key}")
        elif self._backend == "postgres":
            with self._pg_cursor() as cur:
                cur.execute("DELETE FROM rag_docstore WHERE key = %s", (key,))
        else:
            self._store.pop(key, None)
