from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, BigInteger, Integer, TIMESTAMP as SqlTIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from ..base import Base
from .timestamp_mixins import TellerAuditMixin
class Skill(Base, TellerAuditMixin):
    __tablename__ = "tb_skill"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(String(32))
    skill_name: Mapped[str] = mapped_column(String(100))
    skill_desc: Mapped[Optional[str]] = mapped_column(String(500))
    skill_type: Mapped[Optional[str]] = mapped_column(String(6))
    config_param: Mapped[Optional[str]] = mapped_column(Text)
    enable_status: Mapped[Optional[str]] = mapped_column(String(1))
    input_json_param: Mapped[Optional[str]] = mapped_column(Text)
    output_json_param: Mapped[Optional[str]] = mapped_column(Text)
    del_flag: Mapped[Optional[str]] = mapped_column(String(1))
    workspace_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="所属工作空间")
    is_public: Mapped[Optional[int]] = mapped_column(Integer, default=0, comment="0=私有 1=公开（旧字段，由 visibility 同步）")
    visibility: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True, comment="可见性 private/workspace/public（新 source of truth，NULL=待迁移）")
    creator_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="创建者用户ID")
    create_time: Mapped[Optional[datetime]] = mapped_column(SqlTIMESTAMP(timezone=True), server_default=func.now())
    update_time: Mapped[Optional[datetime]] = mapped_column(SqlTIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        {'comment': ''},
    )