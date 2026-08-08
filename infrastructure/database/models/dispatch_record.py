"""调度任务持久化记录模型（三期：任务状态持久化，进程重启可查）。"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, BigInteger, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from ..base import Base


class DispatchRecord(Base):
    """多 agent 调度任务记录。"""
    __tablename__ = "tb_dispatch_record"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dispatch_id: Mapped[Optional[str]] = mapped_column(String(64))
    agent_ids: Mapped[Optional[str]] = mapped_column(Text)  # JSON string
    message: Mapped[Optional[str]] = mapped_column(Text)
    mode: Mapped[Optional[str]] = mapped_column(String(20))
    status: Mapped[Optional[str]] = mapped_column(String(20))  # running/completed/failed
    result: Mapped[Optional[str]] = mapped_column(Text)  # JSON string
    error: Mapped[Optional[str]] = mapped_column(Text)
    trigger_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, comment="触发器 dispatch 时记录；与 team_id 列并行，互不依赖")
    create_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    update_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
