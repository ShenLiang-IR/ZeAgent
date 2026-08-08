"""Agent 版本与发布 API。

设计参见 当前文档分析.md §3.6。

路径前缀 /api/admin/agents/{agent_id}/versions/*：
- GET    /agents/{id}/versions                 列出版本快照
- POST   /agents/{id}/versions                 创建 draft 快照
- POST   /agents/{id}/versions/{v}/publish     发布版本（旧 published 自动 archived）
- POST   /agents/{id}/versions/{v}/rollback    回滚到指定版本
- GET    /agents/{id}/versions/diff?v1=&v2=    两版本配置 diff
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from utils.common.permissions import UserPermissions

from .base import wrap_response
from .permissions import require_read, require_write

router = APIRouter(prefix="/agents", tags=["agent-versions"])


def _parse_agent_id(agent_id: str) -> int:
    """安全解析 agent_id 为整数，失败抛 400。"""
    try:
        return int(agent_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"无效的 agent_id: {agent_id}")


class VersionCreate(BaseModel):
    version_no: str
    version_description: str = ""


@router.get("/{agent_id}/versions")
async def list_versions(
    agent_id: str,
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """列出某 agent 的所有版本快照。"""
    from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository
    from services.agent_version_service import AgentVersionService

    AgentVersionService()._ensure_table()
    versions = AgentVersionRepository().list_by_agent(_parse_agent_id(agent_id))
    return wrap_response({"versions": versions, "total": len(versions)})


@router.post("/{agent_id}/versions")
async def create_version(
    agent_id: str,
    data: VersionCreate,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """创建版本快照（draft 状态，保存当前 agent 配置）。"""
    from services.agent_version_service import AgentVersionService

    result = AgentVersionService().create_snapshot(_parse_agent_id(agent_id), data.version_no, data.version_description)
    if not result:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} 不存在")
    return wrap_response(result)


@router.post("/{agent_id}/versions/{version_no}/rollback")
async def rollback_version(
    agent_id: str,
    version_no: str,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """回滚：恢复工作副本到指定版本快照 + 回草稿（不再直接生效，需重新提交审批）。"""
    from services.agent_version_service import AgentVersionService

    result = AgentVersionService().rollback(_parse_agent_id(agent_id), version_no)
    if not result:
        raise HTTPException(status_code=404, detail=f"版本 {version_no} 不存在")
    return wrap_response(result)


@router.get("/{agent_id}/versions/diff")
async def diff_versions(
    agent_id: str,
    v1: str = Query(..., description="版本1"),
    v2: str = Query(..., description="版本2"),
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """两版本配置字段级 diff。"""
    from services.agent_version_service import AgentVersionService

    result = AgentVersionService().diff(_parse_agent_id(agent_id), v1, v2)
    if result is None:
        raise HTTPException(status_code=404, detail=f"版本 {v1} 或 {v2} 不存在")
    return wrap_response(result)
