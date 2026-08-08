from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Numeric, Integer, BigInteger, TIMESTAMP as SqlTIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from ..base import Base
from .timestamp_mixins import TimestampMixinLegacy
class Agent(Base, TimestampMixinLegacy):
    __tablename__ = "tb_agent"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_name: Mapped[Optional[str]] = mapped_column(String(100))
    agent_description: Mapped[Optional[str]] = mapped_column(Text)
    application_id: Mapped[Optional[str]] = mapped_column(String(32))
    model_id: Mapped[Optional[str]] = mapped_column(String(32))
    visible_scope: Mapped[Optional[str]] = mapped_column(String(1))
    system_prompt: Mapped[Optional[str]] = mapped_column(Text)
    temperature: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    topp: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    max_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    response_timeout: Mapped[Optional[int]] = mapped_column(Integer)
    release_status: Mapped[Optional[str]] = mapped_column(String(1))
    version_no: Mapped[Optional[str]] = mapped_column(String(20))
    version_description: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[Optional[str]] = mapped_column(String(1))
    del_flag: Mapped[Optional[str]] = mapped_column(String(1))
    workspace_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="所属工作空间")
    is_public: Mapped[Optional[int]] = mapped_column(Integer, default=0, comment="0=私有 1=公开（旧字段，由 visibility 同步）")
    visibility: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True, comment="可见性 private/workspace/public（新 source of truth，NULL=待迁移）")
    creator_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="创建者用户ID")
    agent_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Agent 级执行配置覆盖 (JSON)，如 {\"delegation\":{\"enabled\":true}}")
    create_time: Mapped[Optional[datetime]] = mapped_column(SqlTIMESTAMP(timezone=True), server_default=func.now())
    update_time: Mapped[Optional[datetime]] = mapped_column(SqlTIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        {'comment': 'Agent'},
    )
class AgentRelation(Base):
    __tablename__ = "tb_agent_relation"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    relation_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    relation_flag: Mapped[Optional[str]] = mapped_column(String(1))
    del_flag: Mapped[Optional[str]] = mapped_column(String(1))
    create_time: Mapped[Optional[datetime]] = mapped_column(SqlTIMESTAMP(timezone=True), server_default=func.now())
    update_time: Mapped[Optional[datetime]] = mapped_column(SqlTIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        {'comment': 'Agent ()'},
    )
    RELATION_API = '1'
    RELATION_KB = '2'
    RELATION_MCP = '3'
    RELATION_SKILL = '4'