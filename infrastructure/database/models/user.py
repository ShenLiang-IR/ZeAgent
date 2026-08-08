from typing import Optional
from sqlalchemy import String, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "tb_user"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="user", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    default_workspace_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="默认工作空间ID")
    workspace_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="当前工作空间ID")