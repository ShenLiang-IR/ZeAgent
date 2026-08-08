import json
from typing import Dict, List, Any, Optional, Set
from functools import lru_cache
from loguru import logger
class InvResJWTParser:
    @classmethod
    @lru_cache(maxsize=64)
    def _get_role_name_from_roleid(cls, roleid: str) -> Optional[str]:
        """roleid → role_code 映射（兼容旧 invres JWT 的 authorities 字段）。
        查询 tb_role 表，将 roleid 匹配 role_code 或 role_id。结果缓存 64 条。"""
        try:
            from infrastructure.database.sessions import get_config_session
            from sqlalchemy import text
            with get_config_session() as s:
                # 尝试 role_code 精确匹配
                row = s.execute(text(
                    "SELECT role_code FROM tb_role WHERE role_code = :rc"
                ), {"rc": roleid}).fetchone()
                if row:
                    return row[0]
                # 尝试 role_id 匹配（兼容旧系统数字 ID）
                if roleid.isdigit():
                    row = s.execute(text(
                        "SELECT role_code FROM tb_role WHERE role_id = :rid"
                    ), {"rid": int(roleid)}).fetchone()
                    if row:
                        return row[0]
        except Exception as e:
            logger.warning(f"[InvRes] roleid→role_code 映射查询失败 (roleid={roleid}): {e}")
        return None

    @classmethod
    def invalidate_role_cache(cls) -> None:
        """角色变更时调用，清空 roleid→role_code 映射缓存（防旧缓存）。"""
        cls._get_role_name_from_roleid.cache_clear()

    @classmethod
    def _get_merged_permissions(cls, roles: List[str]) -> List[str]:
        from .permissions import PermissionConfigLoader
        merged_perms: Set[str] = set()
        for role in roles:
            perms = PermissionConfigLoader.get_role_permissions(role)
            merged_perms.update(perms)
        return list(merged_perms)
    @classmethod
    def parse_invres_jwt(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not isinstance(payload, dict):
                logger.error("Invalid JWT payload: not a dictionary")
                return cls._get_default_permissions()
            user_id = payload.get("userId") or payload.get("user_id") or payload.get("tellerId")
            if user_id is None:
                logger.warning("JWT payload missing 'userId' field")
                user_id = ""
            elif not isinstance(user_id, str):
                user_id = str(user_id)
            username = payload.get("userName") or payload.get("username") or payload.get("userNickname") or f"user_{user_id}"
            if not isinstance(username, str):
                username = str(username)
            # 兼容两种 JWT 格式：
            # 1. 本项目 AuthService.create_token：roles 字段直接是角色 code 列表（如 ["admin"]），
            #    与 tb_role.role_code 直接匹配
            # 2. 旧 invres JWT：authorities 是 roleid 列表，需经 _get_role_name_from_roleid 反查 role_name
            roles = payload.get("roles")
            if isinstance(roles, list) and roles:
                roles = [str(r) for r in roles]
            else:
                authorities = payload.get("authorities", [])
                if not isinstance(authorities, list):
                    authorities = []
                role_ids = [a for a in authorities if isinstance(a, str)]
                roles = []
                for role_id in role_ids:
                    role_name = cls._get_role_name_from_roleid(role_id)
                    if role_name:
                        roles.append(role_name)
            permissions = cls._get_merged_permissions(roles)
            logger.debug(f"Successfully parsed InvRes JWT: userId={user_id}, username={username}, roles={roles}")
            return {
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "permissions": permissions
            }
        except Exception as e:
            logger.error(f"Failed to parse InvRes JWT: {e}")
            return cls._get_default_permissions()
    @staticmethod
    def _get_default_permissions() -> Dict[str, Any]:
        return {
            "user_id": "",
            "username": "unknown_user",
            "roles": [],
            "permissions": []
        }
def invres_jwt_parser(payload: Dict[str, Any]) -> Dict[str, Any]:
    return InvResJWTParser.parse_invres_jwt(payload)
def register_invres_jwt_parser():
    from utils.common.permissions import PermissionManager
    PermissionManager.register_parser("invres", invres_jwt_parser)
    logger.info("InvRes JWT")
if __name__ == "__main__":
    test_payload = {
        "userId": "12345",
        "userName": "test_user",
        "authorities": ["admin", "editor"]
    }
    result = invres_jwt_parser(test_payload)
    print(f": {json.dumps(result, indent=2, ensure_ascii=False)}")