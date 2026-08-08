from typing import Optional
from datetime import datetime
from sqlalchemy import String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base
class WritingTemplate(Base):
    __tablename__ = "tb_writing_template"
    pr_key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    template_name: Mapped[str] = mapped_column(String(50), nullable=False)
    template_desc: Mapped[Optional[str]] = mapped_column(String(200))
    template_content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="0")
    create_teller_no: Mapped[Optional[str]] = mapped_column(String(50))
    latest_enable_time: Mapped[Optional[datetime]] = mapped_column()
    create_stamp: Mapped[Optional[datetime]] = mapped_column(default=datetime.now)
    upd_stamp: Mapped[Optional[datetime]] = mapped_column(default=datetime.now, onupdate=datetime.now)
    del_flag: Mapped[str] = mapped_column(String(1), default="0")
    __table_args__ = (
        Index('IDX_TEMPLATE_NAME', 'template_name'),
        Index('IDX_TEMPLATE_STATUS', 'status'),
        Index('IDX_TEMPLATE_CREATE_TELLER', 'create_teller_no'),
    )
class WritingDocument(Base):
    __tablename__ = "tb_doc_management"
    pr_key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_name: Mapped[str] = mapped_column(String(200), nullable=False)
    template_id: Mapped[Optional[str]] = mapped_column(String(64))
    template_name: Mapped[Optional[str]] = mapped_column(String(100))
    doc_status: Mapped[str] = mapped_column(String(20), default="PROCESSING")
    doc_content: Mapped[Optional[str]] = mapped_column(Text)
    creator_id: Mapped[Optional[str]] = mapped_column(String(64))
    creator_name: Mapped[Optional[str]] = mapped_column(String(100))
    create_stamp: Mapped[Optional[datetime]] = mapped_column(default=datetime.now)
    upd_stamp: Mapped[Optional[datetime]] = mapped_column(default=datetime.now, onupdate=datetime.now)
    del_flag: Mapped[str] = mapped_column(String(1), default="0")
    __table_args__ = (
        Index('IDX_DOC_NAME', 'doc_name'),
        Index('IDX_DOC_STATUS', 'doc_status'),
        Index('IDX_DOC_TEMPLATE', 'template_id'),
        Index('IDX_DOC_CREATOR', 'creator_id'),
        Index('IDX_DOC_CREATE_STAMP', 'create_stamp'),
    )
TbWritingTemplate = WritingTemplate
TbWritingDocument = WritingDocument