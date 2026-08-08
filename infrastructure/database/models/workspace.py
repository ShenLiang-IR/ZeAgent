"""工作空间 + 用户组 model（多租户隔离）"""
from typing import Optional
from sqlalchemy import String, BigInteger, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class Workspace(Base):
    __tablename__ = "tb_workspace"
    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="创建者 user_id")
    config: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="工作空间级配置覆盖 (JSON)")
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class UserGroup(Base):
    __tablename__ = "tb_user_group"
    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    workspace_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="所属空间")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class UserWorkspace(Base):
    __tablename__ = "tb_user_workspace"
    uw_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    workspace_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="用户组")
    is_owner: Mapped[int] = mapped_column(Integer, default=0, comment="1=空间所有者")
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
