"""MySQL checkpointer 工厂（外层图持久化）。

读 db_config checkpoint 段 + enabled 开关，创建单例 AIOMySQLSaver；降级返回 None（fallback MemorySaver）。
B-5: 外层 StateGraphBuilder 的 checkpointer 从 MemorySaver 升级为 AIOMySQLSaver（跨重启持久化）。
"""
from __future__ import annotations
from typing import Any, Optional
from loguru import logger
from utils.config import get_config


class MysqlSaverFactory:
    """AIOMySQLSaver 单例工厂（async 创建，降级安全）。"""

    _saver: Optional[Any] = None
    _initialized: bool = False

    @classmethod
    async def get_saver(cls) -> Optional[Any]:
        """返回 AIOMySQLSaver 实例，或 None（降级 MemorySaver）。

        enabled=false / db_config 缺失 / MySQL 不可用 → None（调用方 fallback MemorySaver）。
        单例：首次调用后缓存，后续返回同一实例。
        """
        if cls._initialized:
            return cls._saver
        cls._initialized = True
        try:
            if not get_config("observability.checkpoint.mysql_enabled", False):
                logger.info("[Checkpoint] observability.checkpoint.mysql_enabled=false，用 MemorySaver")
                return None
            # 读 agent_config.json 的 database.checkpoint 段（原 db_config.json 已合并）
            from utils.config.db_config import load_db_config_file
            db_cfg = load_db_config_file()
            if not db_cfg:
                logger.warning("[Checkpoint] agent_config.json 无 database 段，降级 MemorySaver")
                return None
            ckpt = db_cfg.get("checkpoint")
            if not ckpt:
                logger.warning("[Checkpoint] database 段无 checkpoint 子段，降级 MemorySaver")
                return None
            import aiomysql
            from langgraph.checkpoint.mysql.aio import AIOMySQLSaver
            conn = await aiomysql.connect(
                host=ckpt.get("host", "127.0.0.1"),
                port=ckpt.get("port", 3306),
                user=ckpt.get("user", "root"),
                password=ckpt.get("password", ""),
                db=ckpt.get("database", "checkpoint"),
                autocommit=True,
            )
            saver = AIOMySQLSaver(conn=conn)
            await saver.setup()
            cls._saver = saver
            logger.info(f"[Checkpoint] AIOMySQLSaver 已创建（{ckpt.get('host')}/{ckpt.get('database')}）")
        except Exception as e:
            logger.warning(f"[Checkpoint] MysqlSaver 创建失败: {type(e).__name__}: {e}，降级 MemorySaver")
            return None
        return cls._saver

    @classmethod
    def reset(cls):
        """测试用：重置单例缓存。"""
        cls._saver = None
        cls._initialized = False
