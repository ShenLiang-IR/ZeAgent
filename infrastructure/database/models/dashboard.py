"""用户工作台快捷方式模型。"""
from typing import Optional
from sqlalchemy import String, BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column
from ..base import Base, TimestampMixin


class UserDashboard(Base, TimestampMixin):
    """用户工作台收藏的二级菜单快捷方式。"""
    __tablename__ = "tb_user_dashboard"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="收藏者用户ID")
    workspace_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="所属工作空间ID")
    menu_path: Mapped[str] = mapped_column(String(255), nullable=False, comment="菜单路由路径，如 /agents")
    menu_label: Mapped[str] = mapped_column(String(100), nullable=False, comment="菜单显示名称")
    menu_icon: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="菜单图标名")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序序号")
