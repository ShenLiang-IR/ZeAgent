"""出站事件订阅 model：tb_event_subscription（外部系统订阅 dispatch 事件）。

设计参见 当前文档分析.md §3.13：出站事件订阅。

- 外部系统订阅事件类型（dispatch_completed/dispatch_failed/quota_exceeded/agent_error/all）
- 事件发生时通过 webhook（httpx POST + HMAC 验签）推送到 callback_url
- secret 用于 HMAC-SHA256 验签（接收方校验 X-Signature header）

与入站 webhook_trigger 正交：入站是外部触发 dispatch，出站是 dispatch 完成通知外部。
"""
from datetime import datetime

from sqlalchemy import TIMESTAMP, BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..base import Base


class EventSubscription(Base):
    """出站事件订阅。"""
    __tablename__ = "tb_event_subscription"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True, comment="业务ID，SUB_ 前缀")
    name: Mapped[str | None] = mapped_column(String(128), comment="订阅名称")
    event_type: Mapped[str | None] = mapped_column(String(50), comment="事件类型: dispatch_completed/dispatch_failed/quota_exceeded/agent_error/all")
    callback_url: Mapped[str | None] = mapped_column(String(500), comment="接收 webhook 的 URL")
    secret: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="HMAC 验签密钥")
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="workspace 隔离")
    enabled: Mapped[str | None] = mapped_column(String(1), default="1", comment="1启用 0禁用")
    create_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    update_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        {'comment': '出站事件订阅'},
    )
