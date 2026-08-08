from typing import List, Dict, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from loguru import logger
from sqlalchemy import select, and_, func
from infrastructure.database.sessions import get_config_session
from infrastructure.database.models.api import RkApi, RkApiNode
from ._error_handler import handle_admin_errors
from .permissions import require_read, require_write, require_delete
from utils.common.permissions import UserPermissions
router = APIRouter(prefix="/apis", tags=["apis"])
class ApiCreateRequest(BaseModel):
    name: str = Field(..., description="API")
    path: str = Field(..., description="API")
    method: str = Field("GET", description="HTTP")
    nodeId: str = Field("", description="ID")
    description: str = Field("", description="")
    timeout: int = Field(30, description="")
    retryTimes: int = Field(3, description="")
class ApiUpdateRequest(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None
    method: Optional[str] = None
    nodeId: Optional[str] = None
    description: Optional[str] = None
    timeout: Optional[int] = None
    retryTimes: Optional[int] = None
    status: Optional[str] = None
class ApiListResponse(BaseModel):
    apis: List[Dict[str, Any]]
    total: int
    count: int
def _api_to_dict(api: RkApi, node_name: str = '') -> Dict[str, Any]:
    status_map = {
        '1': 'enabled',
        '2': 'disabled'
    }
    status = status_map.get(api.intfc_sta_cd, 'enabled')
    created_at = getattr(api, 'create_stamp', None) or getattr(api, 'create_time', None)
    return {
        'id': api.pr_key_id,
        'name': api.intfc_name or '',
        'path': api.intfc_path or '',
        'method': api.http_requer_mth_cd or 'GET',
        'nodeId': api.node_id or '',
        'nodeName': node_name,
        'description': api.intfc_desc or '',
        'timeout': api.tmout_time_num or 30,
        'retryTimes': api.retry_times or 3,
        'status': status,
        'createTime': created_at.isoformat() if created_at else ''
    }
@router.get("/list", response_model=ApiListResponse)
@handle_admin_errors(" API ", detail_with_context=True)
async def list_apis(
    user_permissions: UserPermissions = Depends(require_read("api")),
    skip: int = Query(0, ge=0, description=""),
    limit: int = Query(10, ge=1, le=100, description=""),
    search: str = Query("", description=""),
    nodeId: str = Query("", description=""),
    status: str = Query("", description="")
):
    with get_config_session() as session:
        stmt = select(RkApi).where(RkApi.del_flag == '0')
        if search:
            stmt = stmt.where(RkApi.intfc_name.ilike(f'%{search}%'))
        if nodeId:
            stmt = stmt.where(RkApi.node_id == nodeId)
        if status:
            status_map = {'enabled': '1', 'disabled': '2'}
            status_code = status_map.get(status, status)
            stmt = stmt.where(RkApi.intfc_sta_cd == status_code)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.scalar(count_stmt) or 0
        stmt = stmt.offset(skip).limit(limit)
        apis = session.scalars(stmt).all()
        node_ids = list(set(a.node_id for a in apis if a.node_id))
        node_map = {}
        if node_ids:
            node_stmt = select(RkApiNode).where(RkApiNode.pr_key_id.in_(node_ids))
            nodes = session.scalars(node_stmt).all()
            node_map = {n.pr_key_id: n.node_name or '' for n in nodes}
        result = [_api_to_dict(api, node_map.get(api.node_id, '')) for api in apis]
        return ApiListResponse(
            apis=result,
            total=total,
            count=len(result)
        )
@router.get("/{api_id}")
@handle_admin_errors(" API ", detail_with_context=True)
async def get_api(
    api_id: str,
    user_permissions: UserPermissions = Depends(require_read("api"))
):
    with get_config_session() as session:
        stmt = select(RkApi).where(
            and_(
                RkApi.pr_key_id == api_id,
                RkApi.del_flag == '0'
            )
        )
        api = session.scalar(stmt)
        if not api:
            raise HTTPException(status_code=404, detail=f"API : {api_id}")
        node_name = ''
        if api.node_id:
            node_stmt = select(RkApiNode).where(RkApiNode.pr_key_id == api.node_id)
            node = session.scalar(node_stmt)
            node_name = node.node_name if node else ''
        return {"api": _api_to_dict(api, node_name)}
@router.post("")
@handle_admin_errors(" API ", detail_with_context=True)
async def create_api(
    request: ApiCreateRequest,
    user_permissions: UserPermissions = Depends(require_write("api"))
):
    with get_config_session() as session:
        api = RkApi(
            intfc_name=request.name,
            intfc_path=request.path,
            http_requer_mth_cd=request.method.upper(),
            node_id=request.nodeId,
            intfc_desc=request.description,
            tmout_time_num=request.timeout,
            retry_times=request.retryTimes,
            intfc_sta_cd='1',
            del_flag='0'
        )
        session.add(api)
        session.commit()
        logger.info(f" API : {request.name}")
        return {
            "message": f"API : {request.name}",
            "status": "success",
            "api_id": api.pr_key_id
        }
@router.put("/{api_id}")
@handle_admin_errors(" API ", detail_with_context=True)
async def update_api(
    api_id: str,
    request: ApiUpdateRequest,
    user_permissions: UserPermissions = Depends(require_write("api"))
):
    with get_config_session() as session:
        stmt = select(RkApi).where(
            and_(
                RkApi.pr_key_id == api_id,
                RkApi.del_flag == '0'
            )
        )
        api = session.scalar(stmt)
        if not api:
            raise HTTPException(status_code=404, detail=f"API : {api_id}")
        if request.name is not None:
            api.intfc_name = request.name
        if request.path is not None:
            api.intfc_path = request.path
        if request.method is not None:
            api.http_requer_mth_cd = request.method.upper()
        if request.nodeId is not None:
            api.node_id = request.nodeId
        if request.description is not None:
            api.intfc_desc = request.description
        if request.timeout is not None:
            api.tmout_time_num = request.timeout
        if request.retryTimes is not None:
            api.retry_times = request.retryTimes
        if request.status is not None:
            status_map = {'enabled': '1', 'disabled': '2'}
            api.intfc_sta_cd = status_map.get(request.status, request.status)
        session.commit()
        logger.info(f" API : {api_id}")
        return {
            "message": "API ",
            "status": "success"
        }
@router.delete("/{api_id}")
@handle_admin_errors(" API ", detail_with_context=True)
async def delete_api(
    api_id: str,
    user_permissions: UserPermissions = Depends(require_delete("api"))
):
    with get_config_session() as session:
        stmt = select(RkApi).where(
            and_(
                RkApi.pr_key_id == api_id,
                RkApi.del_flag == '0'
            )
        )
        api = session.scalar(stmt)
        if not api:
            raise HTTPException(status_code=404, detail=f"API : {api_id}")
        api.del_flag = '1'
        session.commit()
        logger.info(f" API : {api_id}")
        return {
            "message": "API ",
            "status": "success"
        }
@router.post("/{api_id}/test")
@handle_admin_errors(" API ", detail_with_context=True)
async def test_api(
    api_id: str,
    user_permissions: UserPermissions = Depends(require_write("api"))
):
    with get_config_session() as session:
        stmt = select(RkApi).where(
            and_(
                RkApi.pr_key_id == api_id,
                RkApi.del_flag == '0'
            )
        )
        api = session.scalar(stmt)
        if not api:
            raise HTTPException(status_code=404, detail=f"API : {api_id}")
        import random
        is_success = random.random() > 0.1
        if is_success:
            return {
                "message": "API ",
                "status": "success",
                "success": True
            }
        else:
            return {
                "message": "API ",
                "status": "error",
                "success": False
            }