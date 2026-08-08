from fastapi import HTTPException, Header, Depends
from typing import Optional, List, Tuple
from functools import wraps
from loguru import logger
from utils.common.auth_dependencies import get_current_user_permissions
from utils.common.permissions import UserPermissions, PermissionManager
def get_admin_user_permissions(
    authorization: Optional[str] = Header(None),
) -> UserPermissions:
    logger.debug(f"[Admin] get_admin_user_permissions , authorization={authorization is not None}")
    return get_current_user_permissions(authorization)
def require_admin_permission(domain: str, resource_type: str, resource_id: Optional[str] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, user_permissions: UserPermissions = Depends(get_admin_user_permissions), **kwargs):
            if not user_permissions:
                raise HTTPException(status_code=401, detail="未提供用户权限信息")
            PermissionManager.require_permission(
                user_permissions,
                domain,
                resource_type,
                resource_id,
                error_detail=f"权限不足: {domain}:{resource_type}"
            )
            return await func(*args, user_permissions=user_permissions, **kwargs)
        return wrapper
    return decorator
class AdminPermissionChecker:
    @staticmethod
    def check_permission(
        user_permissions: UserPermissions,
        domain: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        raise_exception: bool = True
    ) -> bool:
        has_perm = user_permissions.has_permission(domain, resource_type, resource_id)
        if not has_perm and raise_exception:
            raise HTTPException(
                status_code=403,
                detail=f"权限不足: {domain}:{resource_type}:{resource_id or '*'}"
            )
        return has_perm
    @staticmethod
    def check_any_permission(
        user_permissions: UserPermissions,
        permissions: List[Tuple[str, str, Optional[str]]],
        raise_exception: bool = True
    ) -> bool:
        has_perm = user_permissions.has_any_permission(permissions)
        if not has_perm and raise_exception:
            perm_str = ", ".join([f"{d}:{r}:{rid or '*'}" for d, r, rid in permissions])
            raise HTTPException(
                status_code=403,
                detail=f"权限不足: {perm_str}"
            )
        return has_perm
    @staticmethod
    def check_role(
        user_permissions: UserPermissions,
        role: str,
        raise_exception: bool = True
    ) -> bool:
        has_role = user_permissions.has_role(role)
        if not has_role and raise_exception:
            raise HTTPException(
                status_code=403,
                detail=f"需要 {role} 角色"
            )
        return has_role
def require_read(resource_type: str, resource_id: Optional[str] = None):
    async def dependency(user_permissions: UserPermissions = Depends(get_admin_user_permissions)):
        AdminPermissionChecker.check_permission(user_permissions, "read", resource_type, resource_id)
        return user_permissions
    return dependency
def require_write(resource_type: str, resource_id: Optional[str] = None):
    async def dependency(user_permissions: UserPermissions = Depends(get_admin_user_permissions)):
        AdminPermissionChecker.check_permission(user_permissions, "write", resource_type, resource_id)
        return user_permissions
    return dependency
def require_delete(resource_type: str, resource_id: Optional[str] = None):
    async def dependency(user_permissions: UserPermissions = Depends(get_admin_user_permissions)):
        AdminPermissionChecker.check_permission(user_permissions, "delete", resource_type, resource_id)
        return user_permissions
    return dependency
def require_manage(resource_type: str, resource_id: Optional[str] = None):
    async def dependency(user_permissions: UserPermissions = Depends(get_admin_user_permissions)):
        AdminPermissionChecker.check_permission(user_permissions, "manage", resource_type, resource_id)
        return user_permissions
    return dependency