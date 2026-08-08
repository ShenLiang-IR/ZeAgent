from typing import Optional
from sqlalchemy import String, Text, Integer, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base
from .timestamp_mixins import TellerAuditMixin
class Mcp(Base, TellerAuditMixin):
    __tablename__ = "tb_mcp"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mcp_id: Mapped[Optional[str]] = mapped_column(String(32))
    mcp_name: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    category: Mapped[Optional[str]] = mapped_column(String(50))
    exec_cmd: Mapped[Optional[str]] = mapped_column(Text)
    connection_type: Mapped[Optional[str]] = mapped_column(String(20))
    connection_url: Mapped[Optional[str]] = mapped_column(String(200))
    auth_info: Mapped[Optional[str]] = mapped_column(String(200))
    timeout: Mapped[Optional[int]] = mapped_column(Integer)
    params: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(String(1))
    del_flag: Mapped[Optional[str]] = mapped_column(String(1))
    workspace_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="所属工作空间")
    is_public: Mapped[Optional[int]] = mapped_column(Integer, default=0, comment="0=私有 1=公开（旧字段，由 visibility 同步）")
    visibility: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True, comment="可见性 private/workspace/public（新 source of truth，NULL=待迁移）")
    creator_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="创建者用户ID")
    __table_args__ = (
        {'comment': 'MCP'},
    )
class McpIntfc(Base, TellerAuditMixin):
    __tablename__ = "tb_mcp_intfc"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    intfc_name: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    mcp_id: Mapped[str] = mapped_column(String(32), nullable=False)
    input_param_ex: Mapped[Optional[str]] = mapped_column(Text)
    output_param_ex: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(String(1))
    intfc_usage: Mapped[Optional[str]] = mapped_column(String(1))
    del_flag: Mapped[Optional[str]] = mapped_column(String(1))
    __table_args__ = (
        {'comment': 'MCP'},
    )