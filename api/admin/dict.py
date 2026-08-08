from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import List, Dict
from loguru import logger
from ._error_handler import handle_admin_errors_wrap
from .permissions import require_read
from .base import wrap_response
from utils.common.permissions import UserPermissions
router = APIRouter(prefix="/api/dict", tags=["admin"])
MODEL_TP_CLS = [
    {"dictId": "LLM", "dictName": "LLM", "dictDesc": ""},
    {"dictId": "Embedding", "dictName": "Embedding", "dictDesc": ""},
    {"dictId": "Image", "dictName": "Image", "dictDesc": ""},
    {"dictId": "Audio", "dictName": "Audio", "dictDesc": ""},
    {"dictId": "Video", "dictName": "Video", "dictDesc": ""},
    {"dictId": "Multimodal", "dictName": "Multimodal", "dictDesc": ""},
]
SPEC_MODEL_LABEL = [
    {"dictId": "chat", "dictName": "", "dictDesc": ""},
    {"dictId": "completion", "dictName": "", "dictDesc": ""},
    {"dictId": "reasoning", "dictName": "", "dictDesc": ""},
    {"dictId": "coding", "dictName": "", "dictDesc": ""},
    {"dictId": "function_call", "dictName": "", "dictDesc": ""},
    {"dictId": "vision", "dictName": "", "dictDesc": ""},
]
ENABLE_STATUS = [
    {"dictId": "0", "dictName": ""},
    {"dictId": "1", "dictName": ""},
]
DISPLAY_STATUS = [
    {"dictId": "0", "dictName": ""},
    {"dictId": "1", "dictName": ""},
]
MENU_TYPE = [
    {"dictId": "directory", "dictName": ""},
    {"dictId": "menu", "dictName": ""},
    {"dictId": "button", "dictName": ""},
]
YES_NO = [
    {"dictId": "0", "dictName": ""},
    {"dictId": "1", "dictName": ""},
]
DATA_PERMISSION_TYPE = [
    {"dictId": "1", "dictName": ""},
    {"dictId": "2", "dictName": ""},
    {"dictId": "3", "dictName": ""},
    {"dictId": "4", "dictName": ""},
    {"dictId": "5", "dictName": ""},
]
VISIBLE_SCOPE = [
    {"dictId": "1", "dictName": ""},
    {"dictId": "2", "dictName": ""},
    {"dictId": "3", "dictName": ""},
]
RELEASE_STATUS = [
    {"dictId": "0", "dictName": ""},
    {"dictId": "1", "dictName": ""},
    {"dictId": "2", "dictName": ""},
]
DICT_DATA = {
    "MODEL_TP_CLS": MODEL_TP_CLS,
    "SPEC_MODEL_LABEL": SPEC_MODEL_LABEL,
    "ENABLE_STATUS": ENABLE_STATUS,
    "DISPLAY_STATUS": DISPLAY_STATUS,
    "MENU_TYPE": MENU_TYPE,
    "YES_NO": YES_NO,
    "DATA_PERMISSION_TYPE": DATA_PERMISSION_TYPE,
    "VISIBLE_SCOPE": VISIBLE_SCOPE,
    "RELEASE_STATUS": RELEASE_STATUS,
}
class DictRequest(BaseModel):
    dict_type_list: List[str] = Field(..., alias="dictTypeList")
    class Config:
        populate_by_name = True
@router.post("/entries/actions/getDicList")
@handle_admin_errors_wrap("[Dict] ", message_with_context=False)
async def get_dict_list(
    request: DictRequest,
    user_permissions: UserPermissions = Depends(require_read("dict"))
):
    result = {}
    for dict_type in request.dict_type_list:
        dict_data = DICT_DATA.get(dict_type) or DICT_DATA.get(dict_type.upper())
        if dict_data:
            result[dict_type] = dict_data
        else:
            result[dict_type] = []
            logger.warning(f"[Dict] : {dict_type}")
    logger.info(f"[Dict]  {user_permissions.user_id} : {request.dict_type_list}")
    return wrap_response(result)
@router.post("/entries/actions/getSingleDict")
@handle_admin_errors_wrap("[Dict] ", message_with_context=False)
async def get_single_dict(
    request: Dict[str, str],
    user_permissions: UserPermissions = Depends(require_read("dict"))
):
    dict_type = request.get("dictType") or request.get("dict_type")
    if not dict_type:
        return wrap_response(None, message=" dictType ", success=False)
    dict_data = DICT_DATA.get(dict_type) or DICT_DATA.get(dict_type.upper())
    if dict_data:
        logger.info(f"[Dict]  {user_permissions.user_id} : {dict_type}")
        return wrap_response(dict_data)
    else:
        logger.warning(f"[Dict] 字典类型不存在: {dict_type}")
        return wrap_response([], message=f"字典类型不存在: {dict_type}")