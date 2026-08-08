"""审计日志模型：tb_audit_log（用户操作审计历史）。

设计参见 docs/specs/2026-07-19-audit-log-design.md §3。

与 dispatch_record.py 风格一致：直接定义 create_time（不用 Mixin）。
before_data/after_data 字段预留为第二期准备（MVP middleware 暂不写入这两个字段）。
"""
from datetime import datetime

from sqlalchemy import TIMESTAMP, BigInteger, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..base import Base


class AuditLog(Base):
    """用户操作审计日志（admin 写操作自动记录）。"""
    __tablename__ = "tb_audit_log"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    audit_id: Mapped[str | None] = mapped_column(String(64), unique=True, comment="业务ID，AUDIT_ 前缀")
    user_id: Mapped[str | None] = mapped_column(String(64), comment="操作者 user_id")
    username: Mapped[str | None] = mapped_column(String(100), comment="冗余用户名便于查询")
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="操作所在空间")
    http_method: Mapped[str | None] = mapped_column(String(10), comment="POST/PUT/DELETE/PATCH")
    path: Mapped[str | None] = mapped_column(String(255))
    resource_type: Mapped[str | None] = mapped_column(String(50), comment="agent/trigger/skill/mcp/...")
    resource_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str | None] = mapped_column(String(20), comment="create/update/delete/enable/disable")
    before_data: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON：操作前快照（第二期实施）")
    after_data: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON：操作后快照（第二期实施）")
    client_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    create_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        {'comment': '用户操作审计日志'},
    )
