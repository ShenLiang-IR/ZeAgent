from loguru import logger
from typing import List, Dict, Set, Optional, Any, Tuple, Callable
from enum import Enum
class PermissionDomain(str, Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"
    MANAGE = "manage"
class ResourceType(str, Enum):
    AGENT = "agent"
    SUBAGENT = "subagent"
    TOOL = "tool"
    EXTERNAL_TOOL = "external_tool"
    MODE = "mode"
    HTTP_CONFIG = "http_config"
    SYSTEM = "system"
class PermissionRule:
    def __init__(self, rule: str):
        self.rule = rule
        self.parts = rule.split(':')
        if len(self.parts) < 2:
            raise ValueError(f"Invalid permission rule format: {rule}")
        self.domain = self.parts[0] if len(self.parts) > 0 else "*"
        self.resource_type = self.parts[1] if len(self.parts) > 1 else "*"
        self.resource_id = self.parts[2] if len(self.parts) > 2 else "*"
    def matches(self, domain: str, resource_type: str, resource_id: Optional[str] = None) -> bool:
        if self.domain != "*" and self.domain != domain:
            return False
        if self.resource_type != "*" and self.resource_type != resource_type:
            return False
        if resource_id is not None:
            if self.resource_id != "*" and self.resource_id != resource_id:
                return False
        return True
    def __repr__(self) -> str:
        return f"PermissionRule({self.rule})"
class PermissionConfigLoader:
    """角色权限加载器（从 tb_role_permission 表读取）。"""

    @classmethod
    def get_role_permissions(cls, role: str) -> List[str]:
        """从 DB 查询角色权限列表。DB 不可用时回退硬编码默认。"""
        try:
            from infrastructure.database.sessions import get_config_session
            from sqlalchemy import text
            with get_config_session() as s:
                rows = s.execute(text(
                    "SELECT p.permission_code FROM tb_role_permission rp "
                    "JOIN tb_permission p ON rp.permission_id = p.permission_id "
                    "JOIN tb_role r ON rp.role_id = r.role_id "
                    "WHERE r.role_code = :rc"
                ), {"rc": role}).fetchall()
                if rows:
                    perms = [r[0] for r in rows]
                    # admin 始终超管：补 5 域通配，不依赖 DB seed 完整性
                    # （根因修复：DB seed 漏资源时 admin 不会 403，与 _get_default_permissions fallback 一致）
                    if role == "admin":
                        for w in ("read:*:*", "write:*:*", "delete:*:*", "execute:*:*", "manage:*:*"):
                            if w not in perms:
                                perms.append(w)
                    return perms
        except Exception as e:
            logger.warning(f"[PermissionConfig] DB query failed for role '{role}': {e}")
        return cls._get_default_permissions(role)

    @classmethod
    def reload_config(cls):
        """兼容旧接口（DB 模式无需缓存刷新）。"""
        pass

    @classmethod
    def _get_default_permissions(cls, role: str) -> List[str]:
        """硬编码默认权限（DB 不可用时的 fallback）。"""
        defaults = {
            "admin": ["read:*:*", "write:*:*", "delete:*:*", "execute:*:*", "manage:*:*"],
            "editor": ["read:agent:*", "write:agent:*", "read:subagent:*", "write:subagent:*", "read:tool:*", "read:external_tool:*", "read:mode:*"],
            "user": ["read:agent:*", "write:agent:*", "read:subagent:*", "read:tool:*", "read:external_tool:*", "read:mode:*", "read:skill:*", "read:mcp:*"],
            "viewer": ["read:agent:*", "read:subagent:*", "read:tool:*", "read:external_tool:*", "read:mode:*", "read:http_config:*"],
        }
        return defaults.get(role, [])
class UserPermissions:
    def __init__(
        self,
        user_id: str,
        username: Optional[str] = None,
        roles: Optional[List[str]] = None,
        custom_permissions: Optional[List[str]] = None
    ):
        self.user_id = user_id
        self.username = username or f"user_{user_id}"
        self.roles = set(roles or [])
        self.custom_permissions: Set[PermissionRule] = set()
        if custom_permissions:
            for perm in custom_permissions:
                try:
                    self.custom_permissions.add(PermissionRule(perm))
                except ValueError as e:
                    logger.warning(f"Invalid permission rule for user {user_id}: {perm} - {e}")
        self._load_permissions_from_roles()
    def _load_permissions_from_roles(self):
        self.all_permissions: Set[PermissionRule] = set(self.custom_permissions)
        for role in self.roles:
            role_perms = PermissionConfigLoader.get_role_permissions(role)
            for perm in role_perms:
                try:
                    self.all_permissions.add(PermissionRule(perm))
                except ValueError as e:
                    logger.warning(f"Invalid permission rule in config for role {role}: {perm} - {e}")
    def has_permission(
        self,
        domain: str,
        resource_type: str,
        resource_id: Optional[str] = None
    ) -> bool:
        for rule in self.all_permissions:
            if rule.matches(domain, resource_type, resource_id):
                return True
        return False
    def has_any_permission(
        self,
        permissions: List[Tuple[str, str, Optional[str]]]
    ) -> bool:
        for domain, resource_type, resource_id in permissions:
            if self.has_permission(domain, resource_type, resource_id):
                return True
        return False
    def has_all_permissions(
        self,
        permissions: List[Tuple[str, str, Optional[str]]]
    ) -> bool:
        for domain, resource_type, resource_id in permissions:
            if not self.has_permission(domain, resource_type, resource_id):
                return False
        return True
    def has_role(self, role: str) -> bool:
        return role in self.roles
    def get_all_permissions(self) -> List[str]:
        return [rule.rule for rule in self.all_permissions]
class PermissionManager:
    _custom_parsers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}
    @classmethod
    def register_parser(cls, system_name: str, parser: Callable[[Dict[str, Any]], Dict[str, Any]]):
        cls._custom_parsers[system_name] = parser
        logger.info(f"JWT: {system_name}")
    @classmethod
    def extract_permissions_from_jwt(
        cls,
        payload: Dict[str, Any],
        system_name: str = "invres"
    ) -> 'UserPermissions':
        try:
            if system_name in cls._custom_parsers:
                parser = cls._custom_parsers[system_name]
                parsed_data = parser(payload)
            else:
                parsed_data = cls._parse_standard_jwt(payload)
            user_id = parsed_data.get("user_id")
            if not user_id:
                raise ValueError("TokenID")
            if not isinstance(user_id, str):
                user_id = str(user_id)
            username = parsed_data.get("username")
            roles = parsed_data.get("roles", [])
            permissions = parsed_data.get("permissions", [])
            return UserPermissions(
                user_id=user_id,
                username=username,
                roles=roles,
                custom_permissions=permissions
            )
        except Exception as e:
            logger.error(f"[Auth] JWT: {e}")
            raise
    @staticmethod
    def _parse_standard_jwt(payload: Dict[str, Any]) -> Dict[str, Any]:
        user_id = payload.get("tellerId")
        roles = payload.get("roles") or payload.get("authorities", [])
        return {
            "user_id": user_id,
            "username": payload.get("userNickname"),
            "roles": roles if isinstance(roles, list) else [],
            "permissions": payload.get("permissions", [])
        }
    @staticmethod
    def require_permission(
        user_permissions: 'UserPermissions',
        domain: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        error_detail: Optional[str] = None
    ) -> None:
        from fastapi import HTTPException
        if not user_permissions.has_permission(domain, resource_type, resource_id):
            detail = error_detail or f"权限不足: {domain} {resource_type}"
            if resource_id:
                detail += f" ({resource_id})"
            logger.warning(
                f"[Permission Denied] 用户 {user_permissions.user_id} "
                f"权限不足: {domain}:{resource_type}:{resource_id}"
            )
            raise HTTPException(status_code=403, detail=detail)
    @staticmethod
    def require_role(
        user_permissions: 'UserPermissions',
        role: str,
        error_detail: Optional[str] = None
    ) -> None:
        from fastapi import HTTPException
        if not user_permissions.has_role(role):
            detail = error_detail or f"需要 {role} 角色"
            raise HTTPException(status_code=403, detail=detail)