"""管理 API：用户/角色/权限管理（仅管理员）"""

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from infrastructure.database.repositories.rbac_repository import PermissionRepository, RoleRepository
from infrastructure.database.repositories.user_repository import UserRepository
from services.auth_service import AuthService

router = APIRouter(prefix="/api/admin", tags=["admin-rbac"])


def _require_admin(request: Request) -> dict:
    """依赖：验证管理员权限（从 token 提取，必须含 admin 角色）。

    enable_permission_check=false（无登录模式）时放行 guest admin，
    与 require_read/require_write 等其他 admin 依赖一致，避免无登录模式下
    /api/admin/users + /roles + /workspaces 等返回 401。
    """
    from utils.config.config_loader import get_config
    enable_permission_check = get_config("auth.enable_permission_check", True)
    if not enable_permission_check:
        # 无登录模式：放行 guest admin（和 require_read 一致）
        return {"user_id": "guest", "roles": ["admin"]}
    token = request.headers.get("Authorization", "")
    if not token:
        raise HTTPException(401, "未登录")
    svc = AuthService()
    payload = svc.verify_token(token)
    if not payload:
        raise HTTPException(401, "token 无效或已过期")
    roles = payload.get("roles", [])
    if "admin" not in roles:
        raise HTTPException(403, "仅管理员可操作")
    return payload


# ===== 用户管理 =====
@router.get("/users")
async def list_users(payload: dict = Depends(_require_admin)):
    """列出所有用户（仅管理员）。"""
    repo = UserRepository()
    return {"list": repo.list_all()}


class CreateUserRequest(BaseModel):
    username: str
    phone: str
    password: str
    role: str = "user"  # user/admin
    workspace_id: int = 1


@router.post("/users")
async def create_user(req: CreateUserRequest, payload: dict = Depends(_require_admin)):
    """新建用户（仅管理员）。"""
    repo = UserRepository()
    if repo.get_by_username(req.username):
        raise HTTPException(400, f"用户名 {req.username} 已存在")
    entity = repo.create_user(
        username=req.username, phone=req.phone, password=req.password,
        role=req.role, workspace_id=req.workspace_id,
    )
    if not entity:
        raise HTTPException(500, "创建失败")
    return {"success": True, "user": entity}


class UpdateUserRequest(BaseModel):
    username: str | None = None
    phone: str | None = None
    role: str | None = None
    workspace_id: int | None = None


@router.put("/users/{user_id}")
async def update_user(user_id: int, req: UpdateUserRequest, payload: dict = Depends(_require_admin)):
    """编辑用户（仅管理员，不改密码）。"""
    repo = UserRepository()
    entity = repo.update_user(user_id, **req.model_dump(exclude_none=True))
    if not entity:
        raise HTTPException(404, "用户不存在")
    return {"success": True, "user": entity}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, payload: dict = Depends(_require_admin)):
    """删除用户（仅管理员，硬删）。"""
    repo = UserRepository()
    if not repo.delete_user(user_id):
        raise HTTPException(404, "用户不存在或删除失败")
    return {"success": True, "message": f"用户 {user_id} 已删除"}


class AssignRoleRequest(BaseModel):
    user_id: int
    role_code: str  # admin/editor/viewer
    workspace_id: int | None = None  # None=全局


@router.post("/users/assign-role")
async def assign_role(req: AssignRoleRequest, payload: dict = Depends(_require_admin)):
    """给用户分配角色（仅管理员）。"""
    repo = UserRepository()
    ok = repo.assign_role(req.user_id, req.role_code, req.workspace_id)
    if not ok:
        raise HTTPException(500, "分配角色失败")
    logger.info(f"[Admin] assign role {req.role_code} to user {req.user_id} by admin {payload.get('username')}")
    return {"success": True, "message": f"已分配角色 {req.role_code}"}


@router.post("/users/remove-role")
async def remove_role(req: AssignRoleRequest, payload: dict = Depends(_require_admin)):
    """移除用户角色（仅管理员）。"""
    repo = UserRepository()
    ok = repo.remove_role(req.user_id, req.role_code)
    if not ok:
        raise HTTPException(500, "移除角色失败")
    return {"success": True, "message": f"已移除角色 {req.role_code}"}


class UpdateUserStatusRequest(BaseModel):
    user_id: int
    status: str  # active/disabled


@router.post("/users/update-status")
async def update_user_status(req: UpdateUserStatusRequest, payload: dict = Depends(_require_admin)):
    """启用/禁用用户（仅管理员）。"""
    repo = UserRepository()
    entity = repo.update(req.user_id, status=req.status)
    if not entity:
        raise HTTPException(404, "用户不存在")
    return {"success": True, "message": f"用户状态已更新为 {req.status}"}


# ===== 角色管理 =====
@router.get("/roles")
async def list_roles(payload: dict = Depends(_require_admin)):
    """列出所有角色（仅管理员）。"""
    repo = RoleRepository()
    return {"list": repo.list_all()}


class RoleCreateRequest(BaseModel):
    role_name: str
    role_code: str
    description: str = ""
    workspace_id: int | None = None


class RoleUpdateRequest(BaseModel):
    role_name: str | None = None
    description: str | None = None


@router.post("/roles")
async def create_role(req: RoleCreateRequest, payload: dict = Depends(_require_admin)):
    """创建自定义角色（仅管理员，is_system=0）。"""
    from sqlalchemy import text

    from infrastructure.database.sessions import get_config_session
    with get_config_session() as s:
        # 检查 role_code 唯一（参数化查询，防 SQL 注入）
        existing = s.execute(text('SELECT role_id FROM tb_role WHERE role_code=:rc'), {'rc': req.role_code}).fetchone()
        if existing:
            raise HTTPException(400, f"角色代码 {req.role_code} 已存在")
        s.execute(text(
            'INSERT INTO tb_role (role_name, role_code, workspace_id, description, is_system) '
            'VALUES (:rn, :rc, :ws, :desc, 0)'
        ), {'rn': req.role_name, 'rc': req.role_code, 'ws': req.workspace_id, 'desc': req.description})
        s.commit()
        role_id = s.execute(text('SELECT LAST_INSERT_ID()')).scalar()
        logger.info(f"[Admin] create role {req.role_code} (id={role_id}) by {payload.get('username')}")
        return {"role_id": role_id, "role_name": req.role_name, "role_code": req.role_code, "message": "角色创建成功"}


@router.put("/roles/{role_id}")
async def update_role(role_id: int, req: RoleUpdateRequest, payload: dict = Depends(_require_admin)):
    """更新角色（仅管理员，系统角色不可改名）。"""
    from sqlalchemy import text

    from infrastructure.database.sessions import get_config_session
    with get_config_session() as s:
        row = s.execute(text('SELECT is_system FROM tb_role WHERE role_id=:rid'), {'rid': role_id}).fetchone()
        if not row:
            raise HTTPException(404, "角色不存在")
        sets = []
        params = {}
        if req.role_name is not None and not row[0]:
            sets.append('role_name=:rn'); params['rn'] = req.role_name
        elif req.role_name is not None and row[0]:
            raise HTTPException(400, "系统角色不可改名")
        if req.description is not None:
            sets.append('description=:desc'); params['desc'] = req.description
        if sets:
            params['rid'] = role_id
            s.execute(text(f'UPDATE tb_role SET {",".join(sets)} WHERE role_id=:rid'), params)
            s.commit()
        return {"success": True, "message": "角色更新成功"}


@router.delete("/roles/{role_id}")
async def delete_role(role_id: int, payload: dict = Depends(_require_admin)):
    """删除角色（仅管理员，系统角色 is_system=1 不可删）。"""
    from sqlalchemy import text

    from infrastructure.database.sessions import get_config_session
    with get_config_session() as s:
        row = s.execute(text('SELECT is_system, role_code FROM tb_role WHERE role_id=:rid'), {'rid': role_id}).fetchone()
        if not row:
            raise HTTPException(404, "角色不存在")
        if row[0]:
            raise HTTPException(400, f"系统角色 {row[1]} 不可删除")
        # 清理关联（参数化）
        s.execute(text('DELETE FROM tb_role_permission WHERE role_id=:rid'), {'rid': role_id})
        s.execute(text('DELETE FROM tb_user_role WHERE role_id=:rid'), {'rid': role_id})
        s.execute(text('DELETE FROM tb_role WHERE role_id=:rid'), {'rid': role_id})
        s.commit()
        logger.info(f"[Admin] delete role id={role_id} by {payload.get('username')}")
        return {"success": True, "message": "角色已删除"}


@router.get("/roles/{role_id}/permissions")
async def get_role_permissions(role_id: int, payload: dict = Depends(_require_admin)):
    """获取角色的权限列表（仅管理员）。"""
    repo = PermissionRepository()
    return {"list": repo.get_permissions_by_role(role_id)}


# ===== 权限管理 =====
@router.get("/permissions")
async def list_permissions(payload: dict = Depends(_require_admin)):
    """列出所有权限定义（仅管理员）。"""
    repo = PermissionRepository()
    return {"list": repo.list_all()}


class AssignPermissionRequest(BaseModel):
    role_id: int
    permission_id: int


@router.post("/roles/assign-permission")
async def assign_permission(req: AssignPermissionRequest, payload: dict = Depends(_require_admin)):
    """给角色分配权限（仅管理员，精细控制 agent/mcp/tool/skill）。"""
    repo = PermissionRepository()
    ok = repo.assign_permission_to_role(req.role_id, req.permission_id)
    if not ok:
        raise HTTPException(500, "分配权限失败")
    logger.info(f"[Admin] assign permission {req.permission_id} to role {req.role_id} by {payload.get('username')}")
    return {"success": True, "message": "权限已分配"}


@router.post("/roles/remove-permission")
async def remove_permission(req: AssignPermissionRequest, payload: dict = Depends(_require_admin)):
    """移除角色权限（仅管理员）。"""
    repo = PermissionRepository()
    ok = repo.remove_permission_from_role(req.role_id, req.permission_id)
    if not ok:
        raise HTTPException(500, "移除权限失败")
    return {"success": True, "message": "权限已移除"}


# ===== 用户权限查询 =====
@router.get("/users/{user_id}/permissions")
async def get_user_permissions(user_id: int, request: Request, payload: dict = Depends(_require_admin)):
    """获取用户权限列表（仅管理员，查看用户有哪些 agent/mcp/tool/skill 权限）。"""
    repo = UserRepository()
    workspace_id = payload.get("workspace_id", 1)
    roles = repo.get_user_roles(user_id, workspace_id)
    permissions = repo.get_user_permissions(user_id, workspace_id)
    return {"user_id": user_id, "roles": roles, "permissions": permissions}


# ===== 工作空间管理（仅管理员）=====


class WorkspaceCreateRequest(BaseModel):
    name: str
    description: str = ""
    owner_id: int | None = None


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class BindUserRequest(BaseModel):
    user_id: int
    is_owner: bool = False


@router.get("/workspaces")
async def list_workspaces(payload: dict = Depends(_require_admin)):
    """列出所有工作空间（仅管理员）。"""
    from sqlalchemy import text

    from infrastructure.database.sessions import get_config_session
    with get_config_session() as s:
        rows = s.execute(text(
            'SELECT w.workspace_id, w.name, w.description, w.owner_id, w.status, '
            'u.username as owner_name, '
            '(SELECT COUNT(*) FROM tb_user_workspace uw WHERE uw.workspace_id=w.workspace_id) as user_count '
            'FROM tb_workspace w LEFT JOIN tb_user u ON w.owner_id=u.id ORDER BY w.workspace_id'
        )).fetchall()
        return {"list": [
            {"workspace_id": r[0], "name": r[1], "description": r[2], "owner_id": r[3],
             "status": r[4], "owner_name": r[5], "user_count": r[6]}
            for r in rows
        ]}


@router.post("/workspaces")
async def create_workspace(req: WorkspaceCreateRequest, payload: dict = Depends(_require_admin)):
    """创建工作空间（仅管理员）。"""
    from sqlalchemy import text

    from infrastructure.database.sessions import get_config_session
    with get_config_session() as s:
        s.execute(text(
            'INSERT INTO tb_workspace (name, description, owner_id, status) '
            'VALUES (:name, :desc, :owner, "active")'
        ), {'name': req.name, 'desc': req.description, 'owner': req.owner_id})
        s.commit()
        ws_id = s.execute(text('SELECT LAST_INSERT_ID()')).scalar()
        logger.info(f"[Admin] create workspace {req.name} (id={ws_id}) by {payload.get('username')}")
        return {"workspace_id": ws_id, "name": req.name, "message": "工作空间创建成功"}


@router.put("/workspaces/{workspace_id}")
async def update_workspace(workspace_id: int, req: WorkspaceUpdateRequest, payload: dict = Depends(_require_admin)):
    """更新工作空间（仅管理员）。"""
    from sqlalchemy import text

    from infrastructure.database.sessions import get_config_session
    with get_config_session() as s:
        sets = []
        params = {}
        if req.name is not None: sets.append('name=:name'); params['name'] = req.name
        if req.description is not None: sets.append('description=:desc'); params['desc'] = req.description
        if req.status is not None: sets.append('status=:status'); params['status'] = req.status
        if sets:
            params['id'] = workspace_id
            s.execute(text(f'UPDATE tb_workspace SET {",".join(sets)} WHERE workspace_id=:id'), params)
            s.commit()
        return {"success": True, "message": "工作空间更新成功"}


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: int, payload: dict = Depends(_require_admin)):
    """删除工作空间（仅管理员，默认空间 id=1 不可删）。"""
    if workspace_id == 1:
        raise HTTPException(400, "默认空间不可删除")
    from sqlalchemy import text

    from infrastructure.database.sessions import get_config_session
    with get_config_session() as s:
        # 清理关联（参数化）
        s.execute(text('DELETE FROM tb_user_workspace WHERE workspace_id=:ws'), {'ws': workspace_id})
        s.execute(text('DELETE FROM tb_user_role WHERE workspace_id=:ws'), {'ws': workspace_id})
        s.execute(text('DELETE FROM tb_workspace WHERE workspace_id=:ws'), {'ws': workspace_id})
        s.commit()
        return {"success": True, "message": "工作空间已删除"}


@router.post("/workspaces/{workspace_id}/bind-user")
async def bind_user_to_workspace(workspace_id: int, req: BindUserRequest, payload: dict = Depends(_require_admin)):
    """绑定用户到工作空间（仅管理员）。"""
    from sqlalchemy import text

    from infrastructure.database.sessions import get_config_session
    with get_config_session() as s:
        s.execute(text(
            'INSERT IGNORE INTO tb_user_workspace (user_id, workspace_id, is_owner, status) '
            'VALUES (:uid, :ws, :owner, "active")'
        ), {'uid': req.user_id, 'ws': workspace_id, 'owner': 1 if req.is_owner else 0})
        # 自动分配默认空间级角色 viewer（加入空间即获得基础访问权限；INSERT IGNORE 幂等，重复绑定不产生多行）
        s.execute(text(
            'INSERT IGNORE INTO tb_user_role (user_id, role_id, workspace_id) '
            'SELECT :uid, role_id, :ws FROM tb_role WHERE role_code="viewer"'
        ), {'uid': req.user_id, 'ws': workspace_id})
        # 同步用户工作空间归属：默认空间设为绑定空间；当前空间为空或默认空间(1)时也设为绑定空间
        # （用户已明确切换到非默认空间则保留其当前选择）
        s.execute(text(
            'UPDATE tb_user SET default_workspace_id=:ws WHERE id=:uid'
        ), {'ws': workspace_id, 'uid': req.user_id})
        s.execute(text(
            'UPDATE tb_user SET workspace_id=:ws '
            'WHERE id=:uid AND (workspace_id IS NULL OR workspace_id=1)'
        ), {'ws': workspace_id, 'uid': req.user_id})
        s.commit()
        logger.info(f"[Admin] bind user {req.user_id} to workspace {workspace_id} by {payload.get('username')}")
        return {"success": True, "message": "用户已绑定到工作空间"}


@router.get("/workspaces/{workspace_id}/users")
async def get_workspace_users(workspace_id: int, payload: dict = Depends(_require_admin)):
    """获取工作空间内的用户列表（仅管理员）。"""
    from sqlalchemy import text

    from infrastructure.database.sessions import get_config_session
    with get_config_session() as s:
        rows = s.execute(text(
            'SELECT u.id, u.username, u.phone, u.role, uw.is_owner, uw.status '
            'FROM tb_user_workspace uw JOIN tb_user u ON uw.user_id=u.id '
            'WHERE uw.workspace_id=:ws ORDER BY u.id'
        ), {'ws': workspace_id}).fetchall()
        return {"workspace_id": workspace_id, "list": [
            {"id": r[0], "username": r[1], "phone": r[2], "role": r[3], "is_owner": r[4], "status": r[5]}
            for r in rows
        ]}
