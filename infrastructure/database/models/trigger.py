"""触发器模型：tb_trigger（触发器配置）+ tb_trigger_log（触发执行历史）。

设计参见 docs/specs/2026-07-19-trigger-registry-design.md §5 数据模型。

与 dispatch_record.py 风格一致：直接定义 create_time/update_time（不用 Mixin），
类型用 Optional[str]/Optional[int] 保持与现有表风格一致。
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, BigInteger, Integer, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from ..base import Base


class Trigger(Base):
    """触发器配置（cron / webhook / file_watch 三种类型）。"""
    __tablename__ = "tb_trigger"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trigger_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, comment="业务ID，TRG_前缀")
    trigger_name: Mapped[Optional[str]] = mapped_column(String(100))
    trigger_type: Mapped[Optional[str]] = mapped_column(String(20), comment="cron|webhook|file_watch")
    config: Mapped[Optional[str]] = mapped_column(Text, comment="JSON：类型相关配置")
    target_agent_ids: Mapped[Optional[str]] = mapped_column(String(500), comment="逗号分隔 agent_id 列表")
    target_mode: Mapped[Optional[str]] = mapped_column(String(20), default="parallel", comment="dispatch 模式")
    message_template: Mapped[Optional[str]] = mapped_column(Text, comment="渲染触发上下文的模板")
    workspace_id: Mapped[Optional[int]] = mapped_column(BigInteger, comment="所属 tb_workspace")
    enabled: Mapped[Optional[str]] = mapped_column(String(1), default="1", comment="1=启用 0=禁用")
    del_flag: Mapped[Optional[str]] = mapped_column(String(1), default="0")
    creator_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="创建者 user_id")
    create_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    update_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        {'comment': '触发器配置'},
    )


class TriggerLog(Base):
    """触发执行历史（每次触发一条记录，含 status/dispatch_id 可回查）。"""
    __tablename__ = "tb_trigger_log"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    log_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, comment="业务ID，TRG_LOG_前缀")
    trigger_id: Mapped[Optional[str]] = mapped_column(String(64))
    trigger_type: Mapped[Optional[str]] = mapped_column(String(20), comment="快照，便于查询")
    event_data: Mapped[Optional[str]] = mapped_column(Text, comment="JSON：触发上下文")
    dispatch_id: Mapped[Optional[str]] = mapped_column(String(64), comment="关联 tb_dispatch_record.dispatch_id")
    status: Mapped[Optional[str]] = mapped_column(String(20), default="running", comment="running|completed|failed|skipped")
    error: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    create_time: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        {'comment': '触发器执行历史'},
    )
