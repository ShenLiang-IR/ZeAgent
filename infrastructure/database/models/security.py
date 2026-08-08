"""敏感词 model + repository。"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, BigInteger, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from infrastructure.database.base import Base


class SensitiveWord(Base):
    __tablename__ = "tb_sensitive_word"
    pr_key_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    word: Mapped[str] = mapped_column(String(200), nullable=False, index=True, comment="敏感词")
    category: Mapped[Optional[str]] = mapped_column(String(50), comment="分类：politics/porn/violence/other")
    enabled: Mapped[int] = mapped_column(Integer, default=1, comment="1=启用 0=禁用")
    create_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())
