"""RBAC model：角色 + 权限 + 用户角色 + 角色权限关联"""
from typing import Optional
from sqlalchemy import String, BigInteger, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base


class Role(Base):
    __tablename__ = "tb_role"
    role_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="显示名")
    role_code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, comment="代码 admin/editor/viewer")
    workspace_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="所属空间 NULL=全局")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_system: Mapped[int] = mapped_column(Integer, default=0, comment="1=系统内置不可删")


class Permission(Base):
    __tablename__ = "tb_permission"
    permission_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    permission_code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, comment="read:agent:*")
    domain: Mapped[str] = mapped_column(String(50), nullable=False, comment="read/write/delete/execute/manage")
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="agent/mcp/tool/skill/workspace/user")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class UserRole(Base):
    __tablename__ = "tb_user_role"
    ur_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    workspace_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="空间级角色 NULL=全局")


class RolePermission(Base):
    __tablename__ = "tb_role_permission"
    rp_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    permission_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
