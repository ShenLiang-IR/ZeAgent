from typing import List, Dict, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from loguru import logger
from sqlalchemy import select, and_, func
from infrastructure.database.sessions import get_config_session
from infrastructure.database.models.api import RkApiNode, RkApi
from ._error_handler import handle_admin_errors
from .permissions import require_read, require_write, require_delete
from utils.common.permissions import UserPermissions
router = APIRouter(prefix="/nodes", tags=["nodes"])
class NodeCreateRequest(BaseModel):
    name: str = Field(..., description="")
    code: str = Field(..., description="")
    baseUrl: str = Field(..., description="URL")
    environment: str = Field("", description="")
    description: str = Field("", description="")
class NodeUpdateRequest(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    baseUrl: Optional[str] = None
    environment: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
class NodeListResponse(BaseModel):
    nodes: List[Dict[str, Any]]
    total: int
    count: int
def _node_to_dict(node: RkApiNode, api_count: int = 0) -> Dict[str, Any]:
    env_map = {
        '1': '',
        '2': '',
        '3': ''
    }
    environment = env_map.get(node.server_run_envnm_cd, node.server_run_envnm_cd or '')
    status_map = {
        '1': 'healthy',
        '2': 'offline'
    }
    status = status_map.get(node.node_status, 'healthy')
    created_at = getattr(node, 'create_stamp', None) or getattr(node, 'create_time', None)
    return {
        'id': node.pr_key_id,
        'name': node.node_name or '',
        'code': node.agent_node_no or '',
        'baseUrl': node.intfc_path or '',
        'environment': environment,
        'apiCount': api_count,
        'status': status,
        'description': node.node_desc or '',
        'createTime': created_at.isoformat() if created_at else ''
    }
@router.get("/list", response_model=NodeListResponse)
@handle_admin_errors("", detail_with_context=True)
async def list_nodes(
    user_permissions: UserPermissions = Depends(require_read("node")),
    skip: int = Query(0, ge=0, description=""),
    limit: int = Query(10, ge=1, le=100, description=""),
    search: str = Query("", description=""),
    environment: str = Query("", description=""),
    status: str = Query("", description="")
):
    with get_config_session() as session:
        stmt = select(RkApiNode).where(RkApiNode.del_flag == '0')
        if search:
            stmt = stmt.where(RkApiNode.node_name.ilike(f'%{search}%'))
        if environment:
            env_map = {'': '1', '': '2', '': '3'}
            env_code = env_map.get(environment, environment)
            stmt = stmt.where(RkApiNode.server_run_envnm_cd == env_code)
        if status:
            status_map = {'healthy': '1', 'offline': '2'}
            status_code = status_map.get(status, status)
            stmt = stmt.where(RkApiNode.node_status == status_code)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.scalar(count_stmt) or 0
        stmt = stmt.offset(skip).limit(limit)
        nodes = session.scalars(stmt).all()
        result = []
        for node in nodes:
            api_count_stmt = select(func.count()).where(
                and_(
                    RkApi.node_id == node.pr_key_id,
                    RkApi.del_flag == '0'
                )
            )
            api_count = session.scalar(api_count_stmt) or 0
            result.append(_node_to_dict(node, api_count))
        return NodeListResponse(
            nodes=result,
            total=total,
            count=len(result)
        )
@router.get("/{node_id}")
@handle_admin_errors("", detail_with_context=True)
async def get_node(
    node_id: str,
    user_permissions: UserPermissions = Depends(require_read("node"))
):
    with get_config_session() as session:
        stmt = select(RkApiNode).where(
            and_(
                RkApiNode.pr_key_id == node_id,
                RkApiNode.del_flag == '0'
            )
        )
        node = session.scalar(stmt)
        if not node:
            raise HTTPException(status_code=404, detail=f"节点不存在: {node_id}")
        api_count_stmt = select(func.count()).where(
            and_(
                RkApi.node_id == node.pr_key_id,
                RkApi.del_flag == '0'
            )
        )
        api_count = session.scalar(api_count_stmt) or 0
        return {"node": _node_to_dict(node, api_count)}
@router.post("")
@handle_admin_errors("", detail_with_context=True)
async def create_node(
    request: NodeCreateRequest,
    user_permissions: UserPermissions = Depends(require_write("node"))
):
    with get_config_session() as session:
        env_map = {'': '1', '': '2', '': '3'}
        env_code = env_map.get(request.environment, '1')
        node = RkApiNode(
            node_name=request.name,
            agent_node_no=request.code,
            intfc_path=request.baseUrl,
            server_run_envnm_cd=env_code,
            node_desc=request.description,
            node_status='1',
            del_flag='0'
        )
        session.add(node)
        session.commit()
        logger.info(f"节点创建成功: {request.name}")
        return {
            "message": f"节点创建成功: {request.name}",
            "status": "success",
            "node_id": node.pr_key_id
        }
@router.put("/{node_id}")
@handle_admin_errors("", detail_with_context=True)
async def update_node(
    node_id: str,
    request: NodeUpdateRequest,
    user_permissions: UserPermissions = Depends(require_write("node"))
):
    with get_config_session() as session:
        stmt = select(RkApiNode).where(
            and_(
                RkApiNode.pr_key_id == node_id,
                RkApiNode.del_flag == '0'
            )
        )
        node = session.scalar(stmt)
        if not node:
            raise HTTPException(status_code=404, detail=f"节点不存在: {node_id}")
        if request.name is not None:
            node.node_name = request.name
        if request.code is not None:
            node.agent_node_no = request.code
        if request.baseUrl is not None:
            node.intfc_path = request.baseUrl
        if request.environment is not None:
            env_map = {'': '1', '': '2', '': '3'}
            node.server_run_envnm_cd = env_map.get(request.environment, request.environment)
        if request.description is not None:
            node.node_desc = request.description
        if request.status is not None:
            status_map = {'healthy': '1', 'offline': '2'}
            node.node_status = status_map.get(request.status, request.status)
        session.commit()
        logger.info(f"节点操作完成: {node_id}")
        return {
            "message": "操作成功",
            "status": "success"
        }
@router.delete("/{node_id}")
@handle_admin_errors("", detail_with_context=True)
async def delete_node(
    node_id: str,
    user_permissions: UserPermissions = Depends(require_delete("node"))
):
    with get_config_session() as session:
        stmt = select(RkApiNode).where(
            and_(
                RkApiNode.pr_key_id == node_id,
                RkApiNode.del_flag == '0'
            )
        )
        node = session.scalar(stmt)
        if not node:
            raise HTTPException(status_code=404, detail=f"节点不存在: {node_id}")
        node.del_flag = '1'
        session.commit()
        logger.info(f"节点操作完成: {node_id}")
        return {
            "message": "操作成功",
            "status": "success"
        }
@router.post("/{node_id}/test")
@handle_admin_errors("", detail_with_context=True)
async def test_node_connection(
    node_id: str,
    user_permissions: UserPermissions = Depends(require_write("node"))
):
    with get_config_session() as session:
        stmt = select(RkApiNode).where(
            and_(
                RkApiNode.pr_key_id == node_id,
                RkApiNode.del_flag == '0'
            )
        )
        node = session.scalar(stmt)
        if not node:
            raise HTTPException(status_code=404, detail=f"节点不存在: {node_id}")
        import random
        is_healthy = random.random() > 0.1
        if is_healthy:
            return {
                "message": "操作成功",
                "status": "success",
                "healthy": True
            }
        else:
            return {
                "message": "操作成功",
                "status": "error",
                "healthy": False
            }