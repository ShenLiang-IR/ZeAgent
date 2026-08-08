"""成本统计模型：tb_usage_record（token 用量）+ tb_quota（配额）。

设计参见 docs/specs/2026-07-19-usage-tracking-design.md §3。
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, TIMESTAMP, BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..base import Base


class UsageRecord(Base):
    """单次 LLM 调用的 token 用量记录。"""
    __tablename__ = "tb_usage_record"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    usage_id: Mapped[str | None] = mapped_column(String(64), unique=True, comment="业务ID，USAGE_ 前缀")
    dispatch_id: Mapped[str | None] = mapped_column(String(64), comment="关联 tb_dispatch_record")
    trigger_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="触发器 dispatch 时记录")
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, comment="workspace 隔离")
    agent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="具体 agent")
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(64), comment="LLM 模型 ID")
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int | None] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 6), default=0, comment="美元成本")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    create_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        {'comment': 'LLM token 用量记录'},
    )


class Quota(Base):
    """配额配置（per workspace 月度/日度 token 或 cost 上限）。"""
    __tablename__ = "tb_quota"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, comment="所属 workspace")
    quota_type: Mapped[str | None] = mapped_column(String(20), comment="monthly_token/daily_token/monthly_cost")
    limit_value: Mapped[int | None] = mapped_column(BigInteger, comment="上限值")
    period: Mapped[str | None] = mapped_column(String(20), comment="YYYY-MM 或 YYYY-MM-DD")
    used_value: Mapped[int | None] = mapped_column(BigInteger, default=0, comment="已用值")
    over_limit_action: Mapped[str | None] = mapped_column(String(20), default="warn", comment="warn/block/degrade")
    status: Mapped[str | None] = mapped_column(String(20), default="active")
    create_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    update_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        {'comment': 'workspace 配额'},
    )
