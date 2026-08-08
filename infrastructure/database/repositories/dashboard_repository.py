"""用户工作台快捷方式 repository。"""
from typing import Any, Optional
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..base import Base
from ..models.dashboard import UserDashboard
from ..sessions import get_config_session, get_config_engine
from .base_repository import BaseRepository


class DashboardRepository(BaseRepository[UserDashboard, dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = UserDashboard
    _pk_name = 'id'

    def __init__(self):
        super().__init__()
        Base.metadata.create_all(get_config_engine(), tables=[UserDashboard.__table__], checkfirst=True)

    def _entity_to_dict(self, entity: UserDashboard, session: Session) -> dict[str, Any]:
        return {
            'id': entity.id,
            'user_id': entity.user_id,
            'workspace_id': entity.workspace_id,
            'menu_path': entity.menu_path,
            'menu_label': entity.menu_label,
            'menu_icon': entity.menu_icon,
            'sort_order': entity.sort_order,
        }

    def get_by_user(self, user_id: int, workspace_id: Optional[int] = None) -> list[dict[str, Any]]:
        """获取用户的工作台快捷方式列表（按 sort_order 排序）。"""
        with self._get_session() as session:
            stmt = select(UserDashboard).where(UserDashboard.user_id == user_id)
            if workspace_id is not None:
                stmt = stmt.where(UserDashboard.workspace_id == workspace_id)
            stmt = stmt.order_by(UserDashboard.sort_order, UserDashboard.id)
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]

    def add_shortcut(self, user_id: int, menu_path: str, menu_label: str,
                     menu_icon: Optional[str] = None, workspace_id: Optional[int] = None) -> Optional[dict[str, Any]]:
        """添加快捷方式（同 user+path 不重复）。"""
        with self._get_session() as session:
            existing = session.scalars(
                select(UserDashboard).where(
                    UserDashboard.user_id == user_id,
                    UserDashboard.menu_path == menu_path,
                )
            ).first()
            if existing:
                logger.debug(f"[Dashboard] 快捷方式已存在: user={user_id}, path={menu_path}")
                return self._entity_to_dict(existing, session)
            # sort_order = 当前最大值 + 1
            max_order = session.query(UserDashboard.sort_order).filter(
                UserDashboard.user_id == user_id
            ).order_by(UserDashboard.sort_order.desc()).first()
            next_order = (max_order[0] + 1) if max_order else 0
            entity = UserDashboard(
                user_id=user_id,
                workspace_id=workspace_id,
                menu_path=menu_path,
                menu_label=menu_label,
                menu_icon=menu_icon,
                sort_order=next_order,
            )
            session.add(entity)
            session.commit()
            session.refresh(entity)
            return self._entity_to_dict(entity, session)

    def remove_shortcut(self, shortcut_id: int, user_id: int) -> bool:
        """删除快捷方式（仅限本人）。"""
        with self._get_session() as session:
            entity = session.scalars(
                select(UserDashboard).where(
                    UserDashboard.id == shortcut_id,
                    UserDashboard.user_id == user_id,
                )
            ).first()
            if not entity:
                return False
            session.delete(entity)
            session.commit()
            return True
