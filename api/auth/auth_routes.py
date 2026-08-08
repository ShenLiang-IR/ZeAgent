"""认证 API：注册/登录/改密码/当前用户"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from loguru import logger
from services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    phone: str
    password: str
    role: str = "user"  # user / admin（admin 需要已有 admin 调用）


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


def _get_auth_service():
    return AuthService()


def _get_token_from_request(request: Request) -> Optional[str]:
    """从 Authorization header 或 query 参数获取 token。"""
    auth = request.headers.get("Authorization", "")
    if auth:
        return auth
    return request.query_params.get("token")


@router.post("/register")
async def register(req: RegisterRequest):
    """注册用户。admin 注册需已有 admin token（通过 _check_admin 注册 admin 角色）。"""
    svc = _get_auth_service()
    # 普通用户注册 role 固定为 user（防止越权注册 admin）
    role = "user" if req.role != "admin" else "user"
    result = svc.register(req.username, req.phone, req.password, role)
    if "error" in result:
        raise HTTPException(400, result["error"])
    logger.info(f"[Auth] register: {req.username} role={role}")
    return result


def _enrich_workspace_name(user: Optional[dict]) -> None:
    """给 user dict 补充 workspace_name（侧边栏展示用，从 workspace 表查）。"""
    if not user or not user.get("workspace_id"):
        return
    try:
        from infrastructure.database.repositories.workspace_repository import WorkspaceRepository
        ws = WorkspaceRepository().get_by_id(user["workspace_id"], return_dict=True)
        if ws:
            user["workspace_name"] = ws.get("name")
    except Exception as e:
        logger.warning(f"[Auth] enrich workspace_name failed: {e}")


@router.post("/login")
async def login(req: LoginRequest):
    """登录，返回 JWT token + 用户信息 + 权限。"""
    svc = _get_auth_service()
    result = svc.login(req.username, req.password)
    if "error" in result:
        raise HTTPException(401, result["error"])
    _enrich_workspace_name(result.get("user"))
    logger.info(f"[Auth] login: {req.username}")
    return result


@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, request: Request):
    """修改密码（需登录，验证旧密码）。"""
    token = _get_token_from_request(request)
    if not token:
        raise HTTPException(401, "未登录")
    svc = _get_auth_service()
    payload = svc.verify_token(token)
    if not payload:
        raise HTTPException(401, "token 无效或已过期")
    user_id = payload.get("user_id")
    result = svc.change_password(user_id, req.old_password, req.new_password)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/me")
async def get_current_user(request: Request):
    """获取当前用户信息 + 权限（从 token 解析）。"""
    token = _get_token_from_request(request)
    if not token:
        raise HTTPException(401, "未登录")
    svc = _get_auth_service()
    user = svc.get_current_user(token)
    if not user:
        raise HTTPException(401, "token 无效或已过期")
    _enrich_workspace_name(user)
    return user


@router.get("/workspaces")
async def list_user_workspaces(request: Request):
    """列出用户可访问的工作空间。

    admin 可见全部工作空间；普通用户仅返回已关联的空间。
    """
    token = _get_token_from_request(request)
    if not token:
        raise HTTPException(401, "未登录")
    svc = _get_auth_service()
    payload = svc.verify_token(token)
    if not payload:
        raise HTTPException(401, "token 无效")
    user_id = payload.get("user_id")
    from infrastructure.database.repositories.workspace_repository import WorkspaceRepository
    ws_repo = WorkspaceRepository()
    if payload.get("role") == "admin":
        return {"list": ws_repo.get_all(return_dict=True)}
    return {"list": ws_repo.get_user_workspaces(user_id)}


@router.post("/switch-workspace")
async def switch_workspace(request: Request, workspace_id: int):
    """切换当前工作空间。

    admin 可切换到任意工作空间（force 跳过关联校验）。
    """
    token = _get_token_from_request(request)
    if not token:
        raise HTTPException(401, "未登录")
    svc = _get_auth_service()
    payload = svc.verify_token(token)
    if not payload:
        raise HTTPException(401, "token 无效")
    user_id = payload.get("user_id")
    is_admin = payload.get("role") == "admin"
    from infrastructure.database.repositories.workspace_repository import WorkspaceRepository
    ws_repo = WorkspaceRepository()
    ok = ws_repo.switch_workspace(user_id, workspace_id, force=is_admin)
    if not ok:
        raise HTTPException(403, "无权访问该空间")
    # 重新签发 token（含新 workspace_id）
    from infrastructure.database.repositories.user_repository import UserRepository
    user = UserRepository().get_by_id(user_id, return_dict=True)
    if user:
        user["workspace_id"] = workspace_id
        new_token = svc.create_token(user)
        ws = ws_repo.get_by_id(workspace_id, return_dict=True)
        ws_name = ws.get("name") if ws else None
        return {"token": new_token, "workspace_id": workspace_id, "workspace_name": ws_name}
    return {"workspace_id": workspace_id}
