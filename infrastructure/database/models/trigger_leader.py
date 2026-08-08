"""触发器 leader 租约模型（W4：动态 failover）。

多副本部署下，webhook/file_watch 触发器需单副本执行。DB 租约实现动态 leader 选举：
持约副本 = primary（加载非 cron 触发器），租约过期（崩溃）则其他副本接管。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import String, TIMESTAMP, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..base import Base


class TriggerLeader(Base):
    """触发器 leader 租约表（单行，id=1 固定）。"""
    __tablename__ = "tb_trigger_leader"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    holder_id: Mapped[Optional[str]] = mapped_column(String(128))  # 持约副本标识
    expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))  # 租约过期时间
    acquired_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now())
