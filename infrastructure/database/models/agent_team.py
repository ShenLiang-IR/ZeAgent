"""Agent 团队协作 model：tb_agent_team（团队）+ tb_agent_mailbox（Agent 间消息）。

设计参见 docs/specs/2026-07-19-team-collaboration-design.md（SHELVED 解冻）。

- tb_agent_team：workspace 下组建 Agent 团队，members JSON 含 [{agent_id, role}]
- tb_agent_mailbox：Agent 间异步消息（from_agent → to_agent + content + ack 状态）

与 dispatch-multi 正交：dispatch 是临时拼队，team 是持久化团队 + Agent 间通信。
"""
from datetime import datetime

from sqlalchemy import TIMESTAMP, BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..base import Base


class AgentTeam(Base):
    """Agent 团队（workspace 下持久化编队）。"""
    __tablename__ = "tb_agent_team"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    team_id: Mapped[str | None] = mapped_column(String(64), unique=True, comment="业务ID，TEAM_ 前缀")
    name: Mapped[str | None] = mapped_column(String(128), comment="团队名称")
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="所属 workspace")
    visibility: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True, comment="可见性 private/workspace/public（NULL=待迁移）")
    creator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True, comment="创建者用户ID")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="团队说明")
    members: Mapped[str | None] = mapped_column(Text, comment="成员 JSON: [{agent_id, role}]")
    enabled: Mapped[str | None] = mapped_column(String(1), default="1", comment="1启用 0禁用")
    create_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    update_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        {'comment': 'Agent 团队'},
    )


class AgentMailbox(Base):
    """Agent 间消息（邮箱式异步通信）。"""
    __tablename__ = "tb_agent_mailbox"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[str | None] = mapped_column(String(64), unique=True, comment="业务ID，MSG_ 前缀")
    team_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="关联团队（跨团队消息为空）")
    from_agent: Mapped[str | None] = mapped_column(String(128), comment="发送方 agent_name")
    to_agent: Mapped[str | None] = mapped_column(String(128), comment="接收方 agent_name")
    content: Mapped[str | None] = mapped_column(Text, comment="消息内容")
    msg_type: Mapped[str | None] = mapped_column(String(20), default="text", comment="text/task/broadcast")
    status: Mapped[str | None] = mapped_column(String(20), default="pending", comment="pending/acked")
    workspace_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    create_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        {'comment': 'Agent 间消息'},
    )
