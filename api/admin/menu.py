from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from loguru import logger
from ._error_handler import handle_admin_errors_wrap
from .permissions import require_read, require_write, require_delete
from .base import wrap_response
from utils.common.permissions import UserPermissions
router = APIRouter(prefix="/system/menu", tags=["admin"])
class MenuQuery(BaseModel):
    menu_name: Optional[str] = Field(None, alias="menuName")
    menu_type: Optional[str] = Field(None, alias="menuType")
    disp_sta: Optional[str] = Field(None, alias="dispSta")
    class Config:
        populate_by_name = True
class MenuConfig(BaseModel):
    pr_key_id: Optional[str] = Field(None, alias="prKeyId")
    menu_type: Optional[str] = Field(None, alias="menuType")
    menu_name: Optional[str] = Field(None, alias="menuName")
    parent_id: Optional[str] = Field(None, alias="parentId")
    menu_path: Optional[str] = Field(None, alias="menuPath")
    cmpt_path: Optional[str] = Field(None, alias="cmptPath")
    menu_icon: Optional[str] = Field(None, alias="menuIcon")
    display_order: Optional[int] = Field(None, alias="displayOrder")
    disp_sta: Optional[str] = Field("1", alias="dispSta")
    is_cache: Optional[str] = Field("0", alias="isCache")
    function_type: Optional[str] = Field(None, alias="functionType")
    need_data_permission: Optional[str] = Field("0", alias="needDataPermission")
    data_permission_type: Optional[str] = Field(None, alias="dataPermissionType")
    create_stamp: Optional[str] = Field(None, alias="createStamp")
    upd_stamp: Optional[str] = Field(None, alias="updStamp")
    class Config:
        populate_by_name = True
class MenuDetailRequest(BaseModel):
    pr_key_id: str = Field(..., alias="prKeyId")
    class Config:
        populate_by_name = True
class AuthoGenRequest(BaseModel):
    menu_id: str = Field(..., alias="menuId")
    role_ids: List[str] = Field(default_factory=list, alias="roleIds")
    class Config:
        populate_by_name = True
@router.post("/selectMenuList")
@handle_admin_errors_wrap("[Menu] ", message_with_context=False)
async def select_menu_list(
    config: Optional[MenuQuery] = None,
    user_permissions: UserPermissions = Depends(require_read("menu"))
):
    logger.info(f"[Menu]  {user_permissions.user_id} ")
    return wrap_response({
        "list": [],
        "total": 0
    })
@router.post("/selectMenuListByCondition")
@handle_admin_errors_wrap("[Menu] ", message_with_context=False)
async def select_menu_list_by_condition(
    config: Dict[str, Any],
    user_permissions: UserPermissions = Depends(require_read("menu"))
):
    logger.info(f"[Menu]  {user_permissions.user_id} : {config}")
    return wrap_response({
        "list": [],
        "total": 0
    })
@router.post("/addMenu")
@handle_admin_errors_wrap("[Menu] ", message_with_context=False)
async def add_menu(
    config: MenuConfig,
    user_permissions: UserPermissions = Depends(require_write("menu"))
):
    logger.info(f"[Menu]  {user_permissions.user_id} : {config.menu_name}")
    return wrap_response(message="操作成功")
@router.post("/deleteMenu")
@handle_admin_errors_wrap("[Menu] ", message_with_context=False)
async def delete_menu(
    config: MenuDetailRequest,
    user_permissions: UserPermissions = Depends(require_delete("menu"))
):
    logger.info(f"[Menu]  {user_permissions.user_id} : {config.pr_key_id}")
    return wrap_response(message="操作成功")
@router.post("/editMenu")
@handle_admin_errors_wrap("[Menu] ", message_with_context=False)
async def edit_menu(
    config: MenuConfig,
    user_permissions: UserPermissions = Depends(require_write("menu"))
):
    logger.info(f"[Menu]  {user_permissions.user_id} : {config.pr_key_id}")
    return wrap_response(message="操作成功")
@router.post("/selectMenuTree")
@handle_admin_errors_wrap("[Menu] ", message_with_context=False)
async def select_menu_tree(
    config: Optional[MenuQuery] = None,
    user_permissions: UserPermissions = Depends(require_read("menu"))
):
    logger.info(f"[Menu]  {user_permissions.user_id} ")
    return wrap_response({
        "tree": []
    })
@router.post("/detail")
@handle_admin_errors_wrap("[Menu] ", message_with_context=False)
async def menu_detail(
    config: MenuDetailRequest,
    user_permissions: UserPermissions = Depends(require_read("menu"))
):
    logger.info(f"[Menu]  {user_permissions.user_id} : {config.pr_key_id}")
    return wrap_response({})
@router.post("/authoGen")
@handle_admin_errors_wrap("[Menu] ", message_with_context=False)
async def autho_gen(
    config: AuthoGenRequest,
    user_permissions: UserPermissions = Depends(require_write("menu"))
):
    logger.info(f"[Menu]  {user_permissions.user_id} : {config.menu_id}")
    return wrap_response(message="操作成功")