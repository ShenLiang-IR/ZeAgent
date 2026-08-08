from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from loguru import logger
from ._error_handler import handle_admin_errors_wrap
from .permissions import require_read, require_write, require_delete
from .base import wrap_response
from utils.common.permissions import UserPermissions
router = APIRouter(prefix="/system/resMgmt", tags=["admin"])
class ModelResourceQuery(BaseModel):
    risk_model_name: Optional[str] = Field(None, alias="riskModelName")
    model_tp_cls: Optional[str] = Field(None, alias="modelTpCls")
    model_status: Optional[str] = Field(None, alias="modelStatus")
    page_no: int = Field(1, alias="pageNo", ge=1)
    page_size: int = Field(10, alias="pageSize", ge=1, le=100)
    class Config:
        populate_by_name = True
class ModelResourceConfig(BaseModel):
    pr_key_id: Optional[str] = Field(None, alias="prKeyId")
    risk_model_name: str = Field(..., alias="riskModelName")
    model_tp_cls: str = Field(..., alias="modelTpCls")
    spec_model_label: Optional[List[str]] = Field(default_factory=list, alias="specModelLabel")
    model_desc: Optional[str] = Field(None, alias="modelDesc")
    website_hpg_url: str = Field(..., alias="websiteHpgUrl")
    model_id: str = Field(..., alias="modelId")
    sgnt_pwfatt_info: Optional[str] = Field(None, alias="sgntPwfattInfo")
    temperat: Optional[float] = Field(0.7, alias="temperat", ge=0, le=2)
    top_p: Optional[float] = Field(0.9, alias="topP", ge=0, le=1)
    max_serv_num: Optional[int] = Field(2000, alias="maxServNum")
    scene_desc: Optional[str] = Field(None, alias="sceneDesc")
    model_status: Optional[str] = Field("0", alias="modelStatus")
    create_stamp: Optional[str] = Field(None, alias="createStamp")
    upd_stamp: Optional[str] = Field(None, alias="updStamp")
    class Config:
        populate_by_name = True
class ModelResourceDelete(BaseModel):
    pr_key_id: str = Field(..., alias="prKeyId")
    class Config:
        populate_by_name = True
class TestConnectionRequest(BaseModel):
    website_hpg_url: str = Field(..., alias="websiteHpgUrl")
    sgnt_pwfatt_info: Optional[str] = Field(None, alias="sgntPwfattInfo")
    model_id: Optional[str] = Field(None, alias="modelId")
    class Config:
        populate_by_name = True
@router.post("/page")
@handle_admin_errors_wrap("[ModelResource] ", message_with_context=False)
async def res_mgmt_page(
    config: ModelResourceQuery,
    user_permissions: UserPermissions = Depends(require_read("model_resource"))
):
    page_no = config.page_no
    page_size = config.page_size
    logger.info(f"[ModelResource]  {user_permissions.user_id} : pageNo={page_no}, pageSize={page_size}")
    return wrap_response({
        "list": [],
        "total": 0,
        "pageNo": page_no,
        "pageSize": page_size
    })
@router.post("/create")
@handle_admin_errors_wrap("[ModelResource] ", message_with_context=False)
async def res_mgmt_create(
    config: ModelResourceConfig,
    user_permissions: UserPermissions = Depends(require_write("model_resource"))
):
    logger.info(f"[ModelResource]  {user_permissions.user_id} : {config.risk_model_name}")
    return wrap_response(message="操作成功")
@router.post("/delete")
@handle_admin_errors_wrap("[ModelResource] ", message_with_context=False)
async def res_mgmt_delete(
    config: ModelResourceDelete,
    user_permissions: UserPermissions = Depends(require_delete("model_resource"))
):
    logger.info(f"[ModelResource]  {user_permissions.user_id} : {config.pr_key_id}")
    return wrap_response(message="操作成功")
@router.post("/select")
@handle_admin_errors_wrap("[ModelResource] ", message_with_context=False)
async def res_mgmt_select(
    config: Optional[Dict[str, Any]] = None,
    user_permissions: UserPermissions = Depends(require_read("model_resource"))
):
    logger.info(f"[ModelResource]  {user_permissions.user_id} ")
    return wrap_response({
        "list": []
    })
@router.post("/testConnection")
@handle_admin_errors_wrap("[ModelResource] ", message_with_context=False)
async def res_mgmt_test_connection(
    config: TestConnectionRequest,
    user_permissions: UserPermissions = Depends(require_read("model_resource"))
):
    logger.info(f"[ModelResource]  {user_permissions.user_id} : {config.website_hpg_url}")
    return wrap_response(message="操作成功")
@router.post("/update")
@handle_admin_errors_wrap("[ModelResource] ", message_with_context=False)
async def res_mgmt_update(
    config: ModelResourceConfig,
    user_permissions: UserPermissions = Depends(require_write("model_resource"))
):
    logger.info(f"[ModelResource]  {user_permissions.user_id} : {config.pr_key_id}")
    return wrap_response(message="操作成功")