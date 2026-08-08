from typing import Optional
from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base
from .timestamp_mixins import TimestampMixinLegacy
class RLSSysRule(Base, TimestampMixinLegacy):
    __tablename__ = "tb_sys_rls_rule"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    column_name: Mapped[Optional[str]] = mapped_column(String(128))
    operator: Mapped[str] = mapped_column(String(16), default="=")
    value_source: Mapped[str] = mapped_column(String(16), default="user")
    value_key: Mapped[Optional[str]] = mapped_column(String(64))
    fixed_value: Mapped[Optional[str]] = mapped_column(String(256))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    kb_id: Mapped[Optional[str]] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(String(256))
    __table_args__ = (
        {"comment": ""},
    )