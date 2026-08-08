"""认证服务：JWT 签发/验证 + 注册/登录/改密码"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
import jwt
from loguru import logger
from infrastructure.database.repositories.user_repository import UserRepository


class AuthService:
    def __init__(self):
        self._user_repo = UserRepository()

    def _get_jwt_config(self) -> Dict[str, Any]:
        import os
        from utils.config import get_config
        # S3: 密钥缺失/弱→直接拒绝，不回退默认弱密钥（对齐 standalone_provider）
        secret = os.environ.get('JWT_SECRET') or get_config('auth.jwt_secret', '')
        if not secret:
            raise RuntimeError(
                "[Security] JWT secret 未配置！请设置环境变量 JWT_SECRET 或 agent.jwt_secret"
            )
        return {
            'secret': secret,
            'expire_hours': get_config('agent.jwt_expire_hours', 24),
        }

    def create_token(self, user: Dict[str, Any]) -> str:
        """签发 JWT token（roles 唯一来源：tb_user_role 表）。"""
        cfg = self._get_jwt_config()
        user_id = user['id']
        workspace_id = user.get('workspace_id') or user.get('default_workspace_id') or 1
        roles = self._user_repo.get_user_roles(user_id, workspace_id)
        # 确保至少有一个默认角色
        if not roles:
            roles = ['viewer']
        payload = {
            'user_id': user_id,
            'username': user.get('username', ''),
            'role': roles[0],  # 主角色取第一个
            'workspace_id': workspace_id,
            'roles': roles,
            'exp': datetime.now(timezone.utc) + timedelta(hours=cfg['expire_hours']),
            'iat': datetime.now(timezone.utc),
        }
        token = jwt.encode(payload, cfg['secret'], algorithm='HS256')
        return token

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """验证 JWT token，返回 payload 或 None。"""
        cfg = self._get_jwt_config()
        try:
            # 去掉 Bearer 前缀
            if token.startswith('Bearer '):
                token = token[7:]
            payload = jwt.decode(token, cfg['secret'], algorithms=['HS256'])
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            return None

    def register(self, username: str, phone: str, password: str,
                role: str = 'user') -> Dict[str, Any]:
        """注册用户。"""
        # 检查用户名是否已存在
        existing = self._user_repo.get_by_username(username)
        if existing:
            return {'error': '用户名已存在'}
        # 创建用户
        user = self._user_repo.create_user(username, phone, password, role)
        if not user:
            return {'error': '注册失败'}
        token = self.create_token(user)
        return {'token': token, 'user': user}

    def login(self, username: str, password: str) -> Dict[str, Any]:
        """登录。"""
        user = self._user_repo.get_by_username(username)
        if not user:
            return {'error': '用户不存在'}
        if user.get('status') != 'active':
            return {'error': '用户已被禁用'}
        if not self._user_repo.verify_password(password, user.get('password_hash', '')):
            return {'error': '密码错误'}
        # 获取完整用户信息（不含 password_hash）
        user_safe = {k: v for k, v in user.items() if k != 'password_hash'}
        token = self.create_token(user_safe)
        # 获取权限
        workspace_id = user_safe.get('workspace_id') or 1
        permissions = self._user_repo.get_user_permissions(user_safe['id'], workspace_id)
        return {'token': token, 'user': user_safe, 'permissions': permissions}

    def change_password(self, user_id: int, old_password: str, new_password: str) -> Dict[str, Any]:
        """修改密码。"""
        ok = self._user_repo.update_password(user_id, old_password, new_password)
        if ok:
            return {'success': True, 'message': '密码修改成功'}
        return {'error': '旧密码错误或修改失败'}

    def get_current_user(self, token: str) -> Optional[Dict[str, Any]]:
        """从 token 获取当前用户信息 + 权限。"""
        payload = self.verify_token(token)
        if not payload:
            return None
        user_id = payload.get('user_id')
        workspace_id = payload.get('workspace_id', 1)
        permissions = self._user_repo.get_user_permissions(user_id, workspace_id)
        return {
            'user_id': user_id,
            'username': payload.get('username'),
            'role': payload.get('role'),
            'workspace_id': workspace_id,
            'roles': payload.get('roles', []),
            'permissions': permissions,
        }
