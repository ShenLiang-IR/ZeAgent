"""知识库版本快照 repository + 增量索引 service。

版本控制：snapshot/publish/rollback/diff（与 agent_version 模式一致）
增量索引：rebuild_index(kb_id) 调 RAG ingest 重建向量索引
"""
from typing import Any

from loguru import logger
from sqlalchemy import and_, select

from infrastructure.database.models.kb_version import KnowledgeBaseVersion
from infrastructure.database.repositories.base_repository import BaseRepository
from infrastructure.database.sessions import get_config_session


class KnowledgeBaseVersionRepository(BaseRepository[KnowledgeBaseVersion, dict[str, Any]]):
    """知识库版本快照 repository。"""
    _session_factory = get_config_session
    _model_class = KnowledgeBaseVersion
    _pk_name = 'pr_key_id'

    def _entity_to_dict(self, entity: KnowledgeBaseVersion, session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'version_id': entity.version_id,
            'knowledge_base_id': entity.knowledge_base_id,
            'version_no': entity.version_no,
            'version_description': entity.version_description,
            'snapshot': entity.snapshot,
            'status': entity.status,
            'workspace_id': entity.workspace_id,
            'create_time': str(entity.create_time) if entity.create_time else None,
            'update_time': str(entity.update_time) if entity.update_time else None,
        }

    def list_by_kb(self, knowledge_base_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """列出某知识库的所有版本（按时间倒序）。"""
        try:
            with self._get_session() as session:
                stmt = (
                    select(KnowledgeBaseVersion)
                    .where(KnowledgeBaseVersion.knowledge_base_id == knowledge_base_id)
                    .order_by(KnowledgeBaseVersion.pr_key_id.desc())
                    .limit(limit)
                )
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"KnowledgeBaseVersionRepository.list_by_kb ({knowledge_base_id}): {e}", exc_info=True)
            return []

    def get_by_version(self, knowledge_base_id: str, version_no: str) -> dict[str, Any] | None:
        """按知识库 + 版本号查询。"""
        try:
            with self._get_session() as session:
                stmt = select(KnowledgeBaseVersion).where(and_(
                    KnowledgeBaseVersion.knowledge_base_id == knowledge_base_id,
                    KnowledgeBaseVersion.version_no == version_no,
                ))
                entity = session.scalar(stmt)
                return self._entity_to_dict(entity, session) if entity else None
        except Exception as e:
            logger.error(f"KnowledgeBaseVersionRepository.get_by_version: {e}", exc_info=True)
            return None

    def archive_published(self, knowledge_base_id: str) -> int:
        """将某知识库的 published 版本改为 archived（publish 新版本时调用）。"""
        try:
            with self._get_session() as session:
                stmt = select(KnowledgeBaseVersion).where(and_(
                    KnowledgeBaseVersion.knowledge_base_id == knowledge_base_id,
                    KnowledgeBaseVersion.status == "published",
                ))
                entities = session.scalars(stmt).all()
                for e in entities:
                    e.status = "archived"
                session.commit()
                return len(entities)
        except Exception as e:
            logger.error(f"KnowledgeBaseVersionRepository.archive_published: {e}", exc_info=True)
            return 0
