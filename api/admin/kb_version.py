"""知识库版本管理 + 增量索引 API。

设计参见 当前文档分析.md §3.10。

路径前缀 /api/admin/knowledgebase/{kb_id}/versions/*：
- GET    /knowledgebase/{kb_id}/versions                 列出版本快照
- POST   /knowledgebase/{kb_id}/versions                 创建 draft 快照
- POST   /knowledgebase/{kb_id}/versions/{v}/publish     发布版本
- POST   /knowledgebase/{kb_id}/versions/{v}/rollback    回滚到指定版本
- GET    /knowledgebase/{kb_id}/versions/diff?v1=&v2=    两版本配置 diff
- POST   /knowledgebase/{kb_id}/rebuild-index            增量重建向量索引
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from utils.common.permissions import UserPermissions

from .base import wrap_response
from .permissions import require_read, require_write

router = APIRouter(prefix="/knowledgebase", tags=["kb-versions"])


class VersionCreate(BaseModel):
    version_no: str
    version_description: str = ""


class RebuildRequest(BaseModel):
    doc_dir: str | None = None


@router.get("/{kb_id}/versions")
async def list_versions(
    kb_id: str,
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """列出某知识库的所有版本快照。"""
    from infrastructure.database.repositories.kb_version_repository import KnowledgeBaseVersionRepository
    from services.kb_version_service import KnowledgeBaseVersionService

    KnowledgeBaseVersionService()._ensure_table()
    versions = KnowledgeBaseVersionRepository().list_by_kb(kb_id)
    return wrap_response({"versions": versions, "total": len(versions)})


@router.post("/{kb_id}/versions")
async def create_version(
    kb_id: str,
    data: VersionCreate,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """创建知识库版本快照（draft 状态）。"""
    from services.kb_version_service import KnowledgeBaseVersionService

    result = KnowledgeBaseVersionService().create_snapshot(kb_id, data.version_no, data.version_description)
    if not result:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    return wrap_response(result)


@router.post("/{kb_id}/versions/{version_no}/publish")
async def publish_version(
    kb_id: str,
    version_no: str,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """发布版本：draft→published，旧 published→archived。"""
    from services.kb_version_service import KnowledgeBaseVersionService

    result = KnowledgeBaseVersionService().publish(kb_id, version_no)
    if not result:
        raise HTTPException(status_code=404, detail=f"版本 {version_no} 不存在")
    return wrap_response(result)


@router.post("/{kb_id}/versions/{version_no}/rollback")
async def rollback_version(
    kb_id: str,
    version_no: str,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """回滚：恢复知识库配置到指定版本快照。"""
    from services.kb_version_service import KnowledgeBaseVersionService

    result = KnowledgeBaseVersionService().rollback(kb_id, version_no)
    if not result:
        raise HTTPException(status_code=404, detail=f"版本 {version_no} 不存在")
    return wrap_response(result)


@router.get("/{kb_id}/versions/diff")
async def diff_versions(
    kb_id: str,
    v1: str = Query(..., description="版本1"),
    v2: str = Query(..., description="版本2"),
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """两版本配置 diff。"""
    from services.kb_version_service import KnowledgeBaseVersionService

    result = KnowledgeBaseVersionService().diff(kb_id, v1, v2)
    if result is None:
        raise HTTPException(status_code=404, detail=f"版本 {v1} 或 {v2} 不存在")
    return wrap_response(result)


@router.post("/{kb_id}/rebuild-index")
async def rebuild_index(
    kb_id: str,
    req: RebuildRequest,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """增量重建知识库向量索引（文件变更后调用，重新 ingest 所有文档）。"""
    from services.kb_version_service import KnowledgeBaseVersionService

    result = await KnowledgeBaseVersionService().rebuild_index(kb_id, req.doc_dir)
    if not result.get("success"):
        return wrap_response(result, message=result.get("error", "重建失败"), success=False)
    return wrap_response(result)
