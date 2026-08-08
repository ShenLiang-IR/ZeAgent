"""用户 repository（含认证辅助：按用户名查、验证密码、注册、改密码、角色权限查询）"""
from typing import Any

import bcrypt
from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models.user import User
from ..sessions import get_config_session
from .base_repository import BaseRepository


class UserRepository(BaseRepository[User, dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = User
    _pk_name = 'id'

    def _entity_to_dict(self, entity: User, session: Session) -> dict[str, Any]:
        # TimestampMixin 用 create_stamp/upd_stamp（非 created_at/updated_at）
        created = getattr(entity, 'create_stamp', None) or getattr(entity, 'created_at', None)
        return {
            'id': entity.id,
            'username': entity.username,
            'phone': entity.phone,
            'role': entity.role,
            'status': entity.status,
            'default_workspace_id': entity.default_workspace_id,
            'workspace_id': entity.workspace_id,
            'created_at': str(created) if created else None,
        }

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        """按用户名查用户（登录用，含 password_hash）。"""
        try:
            with self._get_session() as session:
                entity = session.scalar(select(User).where(User.username == username))
                if entity:
                    d = self._entity_to_dict(entity, session)
                    d['password_hash'] = entity.password_hash
                    return d
                return None
        except Exception as e:
            logger.error(f"get_by_username failed: {e}")
            return None

    def verify_password(self, password: str, password_hash: str) -> bool:
        """验证密码。"""
        if not password_hash:
            return False
        try:
            return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
        except Exception:
            return False

    def create_user(self, username: str, phone: str, password: str,
                    role: str = 'user', workspace_id: int = 1) -> dict[str, Any] | None:
        """注册用户（bcrypt 加密 + 关联默认空间 + 分配角色）。"""
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode()
        try:
            with self._get_session() as session:
                entity = User(
                    username=username, phone=phone, password_hash=password_hash,
                    role=role, status='active',
                    default_workspace_id=workspace_id, workspace_id=workspace_id,
                )
                session.add(entity)
                session.commit()
                session.refresh(entity)
                user_id = entity.id
                d = self._entity_to_dict(entity, session)
                # 关联默认空间
                session.execute(text(
                    f'INSERT IGNORE INTO tb_user_workspace (user_id, workspace_id, is_owner, status) '
                    f'VALUES ({user_id}, {workspace_id}, 0, "active")'
                ))
                # 分配角色
                if role == 'admin':
                    session.execute(text(
                        f'INSERT IGNORE INTO tb_user_role (user_id, role_id, workspace_id) '
                        f'SELECT {user_id}, role_id, NULL FROM tb_role WHERE role_code="admin"'
                    ))
                else:
                    # 普通用户默认 viewer 角色（role="user" 映射到 viewer）
                    session.execute(text(
                        f'INSERT IGNORE INTO tb_user_role (user_id, role_id, workspace_id) '
                        f'SELECT {user_id}, role_id, {workspace_id} FROM tb_role WHERE role_code="viewer"'
                    ))
                session.commit()
                return d
        except Exception as e:
            logger.error(f"create_user failed: {e}")
            return None

    def update_user(self, user_id: int, **kwargs) -> dict[str, Any] | None:
        """更新用户信息（username/phone/role/workspace_id，不改密码）。"""
        try:
            with self._get_session() as session:
                entity = session.scalar(select(User).where(User.id == user_id))
                if not entity:
                    return None
                for key in ('username', 'phone', 'role', 'default_workspace_id', 'workspace_id'):
                    if key in kwargs and kwargs[key] is not None:
                        setattr(entity, key, kwargs[key])
                session.commit()
                session.refresh(entity)
                return self._entity_to_dict(entity, session)
        except Exception as e:
            logger.error(f"update_user failed: {e}")
            return None

    def delete_user(self, user_id: int) -> bool:
        """删除用户（硬删）。"""
        try:
            with self._get_session() as session:
                entity = session.scalar(select(User).where(User.id == user_id))
                if not entity:
                    return False
                session.delete(entity)
                session.commit()
                return True
        except Exception as e:
            logger.error(f"delete_user failed: {e}")
            return False

    def update_password(self, user_id: int, old_password: str, new_password: str) -> bool:
        """修改密码（验证旧密码）。"""
        try:
            with self._get_session() as session:
                entity = session.scalar(select(User).where(User.id == user_id))
                if not entity or not self.verify_password(old_password, entity.password_hash or ''):
                    return False
                entity.password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode()
                session.commit()
                return True
        except Exception as e:
            logger.error(f"update_password failed: {e}")
            return False

    def get_user_roles(self, user_id: int, workspace_id: int = None) -> list[str]:
        """获取用户角色代码列表（含全局 + 空间级）。"""
        try:
            with self._get_session() as session:
                sql = (
                    'SELECT r.role_code FROM tb_user_role ur '
                    'JOIN tb_role r ON ur.role_id = r.role_id '
                    f'WHERE ur.user_id = {user_id} '
                    'AND (ur.workspace_id IS NULL'
                )
                if workspace_id:
                    sql += f' OR ur.workspace_id = {workspace_id}'
                sql += ')'
                rows = session.execute(text(sql)).fetchall()
                return [r[0] for r in rows]
        except Exception:
            return []

    def get_user_permissions(self, user_id: int, workspace_id: int = None) -> list[str]:
        """获取用户权限代码列表（通过角色关联）。"""
        try:
            with self._get_session() as session:
                sql = (
                    'SELECT DISTINCT p.permission_code FROM tb_user_role ur '
                    'JOIN tb_role_permission rp ON ur.role_id = rp.role_id '
                    'JOIN tb_permission p ON rp.permission_id = p.permission_id '
                    f'WHERE ur.user_id = {user_id} '
                    'AND (ur.workspace_id IS NULL'
                )
                if workspace_id:
                    sql += f' OR ur.workspace_id = {workspace_id}'
                sql += ')'
                rows = session.execute(text(sql)).fetchall()
                return [r[0] for r in rows]
        except Exception:
            return []

    def list_all(self) -> list[dict[str, Any]]:
        """列出所有用户。"""
        return self.get_all(return_dict=True)

    def assign_role(self, user_id: int, role_code: str, workspace_id: int = None) -> bool:
        """给用户分配角色（管理员操作）。"""
        try:
            with self._get_session() as session:
                ws_val = str(workspace_id) if workspace_id else 'NULL'
                session.execute(text(
                    f'INSERT IGNORE INTO tb_user_role (user_id, role_id, workspace_id) '
                    f'SELECT {user_id}, role_id, {ws_val} FROM tb_role WHERE role_code="{role_code}"'
                ))
                session.commit()
                return True
        except Exception as e:
            logger.error(f"assign_role failed: {e}")
            return False

    def remove_role(self, user_id: int, role_code: str) -> bool:
        """移除用户角色（管理员操作）。"""
        try:
            with self._get_session() as session:
                session.execute(text(
                    f'DELETE ur FROM tb_user_role ur '
                    f'JOIN tb_role r ON ur.role_id = r.role_id '
                    f'WHERE ur.user_id = {user_id} AND r.role_code = "{role_code}"'
                ))
                session.commit()
                return True
        except Exception as e:
            logger.error(f"remove_role failed: {e}")
            return False
