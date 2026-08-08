"""触发器 leader 选举（W4：动态 failover）。

DB 租约：持约副本 = primary（加载非 cron 触发器）。租约过期（持约副本崩溃）则其他副本接管。
替代静态 TRIGGER_WORKER_ROLE env——动态 failover，primary 下线自动切换。

用法：config agent.execution.trigger_leader_election.enabled=true 时启用。
单副本部署下唯一副本始终持约，行为与静态 primary 一致。
"""
from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone

from loguru import logger

from utils.config import get_config


def _utcnow() -> datetime:
    """naive UTC（避免 utcnow() 弃用 + 保持与 DB TIMESTAMP 可比）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _holder_id() -> str:
    """副本标识：hostname:pid（多副本唯一）。"""
    return f"{socket.gethostname()}:{os.getpid()}"


class TriggerLeaderElection:
    """DB 租约 leader 选举（单例，惰性建表）。"""

    _table_ensured = False

    @classmethod
    def _ensure_table(cls) -> None:
        if cls._table_ensured:
            return
        try:
            from infrastructure.database.base import Base
            from infrastructure.database.engines import get_config_engine
            from infrastructure.database.models.trigger_leader import TriggerLeader
            Base.metadata.create_all(get_config_engine(), tables=[TriggerLeader.__table__], checkfirst=True)
            cls._table_ensured = True
        except Exception as e:
            logger.warning(f"[LeaderElection] 建表失败: {e}")

    @classmethod
    def enabled(cls) -> bool:
        # 优先环境变量（多 worker 部署用 docker env 注入），回退配置文件
        env_val = os.getenv("AGENT_TRIGGER_LEADER_ELECTION_ENABLED", "").lower()
        if env_val in ("1", "true", "yes"):
            return True
        if env_val in ("0", "false", "no"):
            return False
        return bool(get_config("agent.execution.trigger_leader_election.enabled", False))

    @classmethod
    def _ttl_seconds(cls) -> int:
        return int(get_config("agent.execution.trigger_leader_election.ttl_seconds", 30))

    @classmethod
    def acquire_or_renew(cls) -> bool:
        """尝试获取或续约 leader 租约。持约或新获取返回 True。

        逻辑：若当前持约者是本副本 → 续约（更新 expires_at）；
        若无持约者或租约已过期 → 抢占（UPDATE holder_id）；
        否则（他人持约未过期）→ False。
        """
        if not cls.enabled():
            return False
        cls._ensure_table()
        from infrastructure.database.models.trigger_leader import TriggerLeader
        from infrastructure.database.sessions import get_config_session
        from sqlalchemy import select, update
        holder = _holder_id()
        now = _utcnow()
        ttl = cls._ttl_seconds()
        new_expiry = now + timedelta(seconds=ttl)
        try:
            with get_config_session() as session:
                row = session.scalars(select(TriggerLeader).where(TriggerLeader.id == 1)).first()
                if row is None:
                    # 首次：插入
                    session.add(TriggerLeader(id=1, holder_id=holder, expires_at=new_expiry, acquired_at=now))
                    logger.info(f"[LeaderElection] {holder} 获取 leader（首次）")
                    return True
                # 续约（本副本持约）
                if row.holder_id == holder:
                    session.execute(
                        update(TriggerLeader).where(TriggerLeader.id == 1)
                        .values(holder_id=holder, expires_at=new_expiry))
                    return True
                # 抢占（他人租约过期）
                if row.expires_at is None or row.expires_at < now:
                    session.execute(
                        update(TriggerLeader).where(TriggerLeader.id == 1)
                        .values(holder_id=holder, expires_at=new_expiry, acquired_at=now))
                    logger.info(f"[LeaderElection] {holder} 抢占 leader（前 {row.holder_id} 租约过期）")
                    return True
                # 他人持约未过期
                return False
        except Exception as e:
            logger.warning(f"[LeaderElection] acquire_or_renew 失败（降级非 leader）: {e}")
            return False

    @classmethod
    def is_leader(cls) -> bool:
        """当前副本是否为有效 leader（持约且租约未过期）。"""
        if not cls.enabled():
            return True  # 未启用 → 视为 leader（向下兼容静态 primary 行为）
        cls._ensure_table()
        from infrastructure.database.models.trigger_leader import TriggerLeader
        from infrastructure.database.sessions import get_config_session
        from sqlalchemy import select
        holder = _holder_id()
        try:
            with get_config_session() as session:
                row = session.scalars(select(TriggerLeader).where(TriggerLeader.id == 1)).first()
                if row is None:
                    return False
                if row.holder_id != holder:
                    return False
                return row.expires_at is None or row.expires_at >= _utcnow()
        except Exception as e:
            logger.warning(f"[LeaderElection] is_leader 查询失败（降级 False）: {e}")
            return False

    @classmethod
    def reset(cls) -> None:
        """测试用：清空租约。"""
        cls._table_ensured = False
        try:
            from infrastructure.database.models.trigger_leader import TriggerLeader
            from infrastructure.database.sessions import get_config_session
            from sqlalchemy import delete
            with get_config_session() as session:
                session.execute(delete(TriggerLeader).where(TriggerLeader.id == 1))
        except Exception:
            pass
