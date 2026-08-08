"""工作空间 repository（空间 CRUD + 用户-空间关联查询）"""
from typing import Dict, Any, List
from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..sessions import get_config_session
from ..models.workspace import Workspace, UserGroup
from .base_repository import BaseRepository


class WorkspaceRepository(BaseRepository[Workspace, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = Workspace
    _pk_name = 'workspace_id'

    def _entity_to_dict(self, entity: Workspace, session: Session) -> Dict[str, Any]:
        created = getattr(entity, 'create_stamp', None) or getattr(entity, 'created_at', None)
        return {
            'workspace_id': entity.workspace_id,
            'name': entity.name,
            'description': entity.description,
            'owner_id': entity.owner_id,
            'status': entity.status,
            'created_at': str(created) if created else None,
        }

    def get_user_workspaces(self, user_id: int) -> List[Dict[str, Any]]:
        """获取用户可访问的工作空间列表。"""
        try:
            with self._get_session() as session:
                sql = (
                    'SELECT w.workspace_id, w.name, w.description, uw.is_owner, uw.status '
                    'FROM tb_user_workspace uw '
                    'JOIN tb_workspace w ON uw.workspace_id = w.workspace_id '
                    f'WHERE uw.user_id = {user_id} AND uw.status = "active"'
                )
                rows = session.execute(text(sql)).fetchall()
                return [
                    {'workspace_id': r[0], 'name': r[1], 'description': r[2],
                     'is_owner': r[3], 'status': r[4]}
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"get_user_workspaces failed: {e}")
            return []

    def switch_workspace(self, user_id: int, workspace_id: int, force: bool = False) -> bool:
        """切换用户当前工作空间。

        Args:
            force: admin 跳过关联校验，可切换到任意工作空间
        """
        try:
            with self._get_session() as session:
                # 验证用户有该空间权限（admin force 跳过）
                if not force:
                    r = session.execute(text(
                        f'SELECT 1 FROM tb_user_workspace WHERE user_id={user_id} '
                        f'AND workspace_id={workspace_id} AND status="active"'
                    )).fetchone()
                    if not r:
                        return False
                session.execute(text(
                    f'UPDATE tb_user SET workspace_id={workspace_id} WHERE id={user_id}'
                ))
                session.commit()
                return True
        except Exception as e:
            logger.error(f"switch_workspace failed: {e}")
            return False


class UserGroupRepository(BaseRepository[UserGroup, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = UserGroup
    _pk_name = 'group_id'

    def _entity_to_dict(self, entity: UserGroup, session: Session) -> Dict[str, Any]:
        return {
            'group_id': entity.group_id,
            'name': entity.name,
            'workspace_id': entity.workspace_id,
            'description': entity.description,
        }
