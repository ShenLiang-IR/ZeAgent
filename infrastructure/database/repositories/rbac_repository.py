"""RBAC repository（角色 + 权限 + 角色-权限关联查询）"""
from typing import Optional, Dict, Any, List
from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from ..sessions import get_config_session
from ..models.rbac import Role, Permission
from .base_repository import BaseRepository


class RoleRepository(BaseRepository[Role, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = Role
    _pk_name = 'role_id'

    def _entity_to_dict(self, entity: Role, session: Session) -> Dict[str, Any]:
        return {
            'role_id': entity.role_id,
            'role_name': entity.role_name,
            'role_code': entity.role_code,
            'workspace_id': entity.workspace_id,
            'description': entity.description,
            'is_system': entity.is_system,
        }

    def get_by_code(self, role_code: str) -> Optional[Dict[str, Any]]:
        """按 role_code 查角色。"""
        try:
            with self._get_session() as session:
                entity = session.scalar(select(Role).where(Role.role_code == role_code))
                return self._entity_to_dict(entity, session) if entity else None
        except Exception as e:
            logger.error(f"get_by_code failed: {e}")
            return None

    def list_all(self) -> List[Dict[str, Any]]:
        return self.get_all(return_dict=True)


class PermissionRepository(BaseRepository[Permission, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = Permission
    _pk_name = 'permission_id'

    def _entity_to_dict(self, entity: Permission, session: Session) -> Dict[str, Any]:
        return {
            'permission_id': entity.permission_id,
            'permission_code': entity.permission_code,
            'domain': entity.domain,
            'resource_type': entity.resource_type,
            'description': entity.description,
        }

    def list_all(self) -> List[Dict[str, Any]]:
        return self.get_all(return_dict=True)

    def get_permissions_by_role(self, role_id: int) -> List[Dict[str, Any]]:
        """获取角色的权限列表。"""
        try:
            with self._get_session() as session:
                sql = (
                    'SELECT p.permission_id, p.permission_code, p.domain, p.resource_type, p.description '
                    'FROM tb_role_permission rp '
                    'JOIN tb_permission p ON rp.permission_id = p.permission_id '
                    f'WHERE rp.role_id = {role_id}'
                )
                rows = session.execute(text(sql)).fetchall()
                return [
                    {'permission_id': r[0], 'permission_code': r[1], 'domain': r[2],
                     'resource_type': r[3], 'description': r[4]}
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"get_permissions_by_role failed: {e}")
            return []

    def assign_permission_to_role(self, role_id: int, permission_id: int) -> bool:
        """给角色分配权限（管理员操作）。"""
        try:
            with self._get_session() as session:
                session.execute(text(
                    f'INSERT IGNORE INTO tb_role_permission (role_id, permission_id) '
                    f'VALUES ({role_id}, {permission_id})'
                ))
                session.commit()
                return True
        except Exception as e:
            logger.error(f"assign_permission_to_role failed: {e}")
            return False

    def remove_permission_from_role(self, role_id: int, permission_id: int) -> bool:
        """移除角色权限（管理员操作）。"""
        try:
            with self._get_session() as session:
                session.execute(text(
                    f'DELETE FROM tb_role_permission WHERE role_id={role_id} AND permission_id={permission_id}'
                ))
                session.commit()
                return True
        except Exception as e:
            logger.error(f"remove_permission_from_role failed: {e}")
            return False
