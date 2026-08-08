from typing import Optional
from fastapi import HTTPException, Header
from loguru import logger
from .auth_providers import get_auth_provider, AuthValidationError
from .auth_providers.base import AuthResult
from .permissions import PermissionManager, UserPermissions
from .constants import DEFAULT_USER_ID
def get_effective_authorization(authorization: Optional[str]) -> Optional[str]:
    if authorization:
        return authorization
    try:
        from utils.config.config_loader import get_config
        default_token = get_config("auth.default_token", "")
        if default_token:
            if default_token.lower().startswith("bearer "):
                return default_token
            return f"Bearer {default_token}"
        logger.debug("[Auth]  token")
    except Exception as e:
        logger.warning(f"[Auth]  token : {e}")
    return None
def get_current_auth_result(
    authorization: Optional[str] = Header(None),
) -> AuthResult:
    from utils.config.config_loader import get_config
    enable_permission_check = get_config("auth.enable_permission_check", True)
    effective_auth = get_effective_authorization(authorization)
    if not effective_auth:
        if enable_permission_check:
            raise HTTPException(status_code=401, detail=" Authorization ")
        else:
            logger.debug("[Auth]  Authorization admin ")
            return AuthResult(
                user_id=DEFAULT_USER_ID,
                username=DEFAULT_USER_ID,
                roles=["admin"],
            )
    if not effective_auth.startswith("Bearer "):
        if enable_permission_check:
            raise HTTPException(
                status_code=401,
                detail="Authorization  'Bearer <token>'",
            )
        return AuthResult(user_id=DEFAULT_USER_ID, username=DEFAULT_USER_ID, roles=["admin"])
    token = effective_auth.replace("Bearer ", "").strip()
    if not token:
        if enable_permission_check:
            raise HTTPException(status_code=401, detail="Token ")
        return AuthResult(user_id=DEFAULT_USER_ID, username=DEFAULT_USER_ID, roles=["admin"])
    provider = get_auth_provider()
    try:
        auth_result = provider.validate_token(token)
        if not enable_permission_check:
            auth_result.roles = ["admin"]
        logger.debug(
            f"[Auth]  (provider={provider.name}, "
            f"check={enable_permission_check}) - "
            f"user_id={auth_result.user_id}, roles={auth_result.roles}"
        )
        return auth_result
    except AuthValidationError as e:
        if not enable_permission_check:
            logger.debug(
                f"[Auth] Token  guest: {e}"
            )
            return AuthResult(
                user_id=DEFAULT_USER_ID,
                username=DEFAULT_USER_ID,
                roles=["admin"],
            )
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except NotImplementedError:
        if not enable_permission_check:
            return AuthResult(
                user_id=DEFAULT_USER_ID,
                username=DEFAULT_USER_ID,
                roles=["admin"],
            )
        raise HTTPException(status_code=401, detail=" Provider  token ")
    except Exception as e:
        if not enable_permission_check:
            logger.debug(f"[Auth] Token  guest: {e}")
            return AuthResult(
                user_id=DEFAULT_USER_ID,
                username=DEFAULT_USER_ID,
                roles=["admin"],
            )
        logger.error(f"[Auth] Token : {e}")
        raise HTTPException(status_code=401, detail=f"Token : {e}")
def get_current_user_permissions(
    authorization: Optional[str] = Header(None),
) -> UserPermissions:
    from utils.config.config_loader import get_config
    auth_result = get_current_auth_result(authorization)
    enable_permission_check = get_config("auth.enable_permission_check", True)
    if enable_permission_check:
        system_name = get_config("auth.system_name", "invres")
        user_permissions = PermissionManager.extract_permissions_from_jwt(
            auth_result.payload, system_name
        )
    else:
        user_permissions = UserPermissions(
            user_id=auth_result.user_id,
            username=auth_result.username,
            roles=["admin"],
        )
    logger.debug(
        f"[Auth]  - user_id={user_permissions.user_id}, "
        f"roles={user_permissions.roles}"
    )
    return user_permissions
def get_current_user_id(
    authorization: Optional[str] = Header(None),
) -> str:
    permissions = get_current_user_permissions(authorization)
    return permissions.user_id
async def verify_admin_token(
    authorization: Optional[str] = Header(None),
) -> str:
    from utils.config.config_loader import get_config
    enable_permission_check = get_config("auth.enable_permission_check", True)
    if not enable_permission_check:
        logger.debug("[Admin]  Token ")
        if authorization and authorization.startswith("Bearer "):
            return authorization.replace("Bearer ", "").strip()
        return "skipped"
    if not authorization:
        logger.warning("[Admin]  Authorization ")
        raise HTTPException(status_code=401, detail=" Authorization ")
    if not authorization.startswith("Bearer "):
        logger.warning("[Admin] Authorization ")
        raise HTTPException(
            status_code=401,
            detail="Authorization  'Bearer <token>'",
        )
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        logger.warning("[Admin] Token ")
        raise HTTPException(status_code=401, detail="Token ")
    parts = token.split(".")
    if len(parts) != 3:
        logger.warning("[Admin] Token  -  JWT ")
        raise HTTPException(
            status_code=403,
            detail="Token  JWT Token",
        )
    provider = get_auth_provider()
    try:
        auth_result = provider.validate_token(token)
        logger.debug(f"[Admin] Token  - user_id={auth_result.user_id}")
        return token
    except AuthValidationError as e:
        logger.warning(f"[Admin] Token : {e}")
        raise HTTPException(
            status_code=e.status_code if e.status_code == 401 else 403,
            detail=f"JWT Token : {e}",
        )
    except Exception as e:
        logger.warning(f"[Admin] Token : {e}")
        raise HTTPException(
            status_code=403,
            detail="JWT Token  Token ",
        )
def get_user_id_from_auth_header(authorization: Optional[str]) -> str:
    if not authorization:
        from utils.config.config_loader import get_config
        enable_check = get_config("auth.enable_permission_check", True)
        if enable_check:
            raise HTTPException(status_code=401, detail=" Authorization ")
        logger.debug(
            f"[get_user_id_from_auth_header]  ID: {DEFAULT_USER_ID}"
        )
        return DEFAULT_USER_ID
    permissions = get_current_user_permissions(authorization)
    result = str(permissions.user_id) if permissions.user_id else DEFAULT_USER_ID
    logger.debug(f"[get_user_id_from_auth_header]  JWT  ID: {result}")
    return result


def get_workspace_id_from_auth_header(authorization: Optional[str]) -> Optional[int]:
    """从 Authorization header 的 JWT 提取 workspace_id（无 token/无登录模式返回 None）。"""
    auth = get_effective_authorization(authorization)
    if not auth:
        return None
    try:
        from services.auth_service import AuthService
        payload = AuthService().verify_token(auth)
        if payload:
            return payload.get("workspace_id")
    except Exception:
        pass
    return None