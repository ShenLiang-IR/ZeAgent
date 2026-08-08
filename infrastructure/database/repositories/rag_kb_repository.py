"""RAG 知识库 Repository（CRUD）。"""
from typing import Dict, Any, Optional, List
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import select
from infrastructure.database.sessions import get_config_session
from infrastructure.database.models.rag_knowledge_base import RagKnowledgeBase
from infrastructure.database.repositories.base_repository import BaseRepository


class RagKnowledgeBaseRepository(BaseRepository[RagKnowledgeBase, Dict[str, Any]]):
    """RAG 知识库 CRUD。表 rag_knowledge_base（MySQL agent_config 库）。"""
    _session_factory = get_config_session
    _model_class = RagKnowledgeBase
    _pk_name = 'id'

    def _entity_to_dict(self, entity: RagKnowledgeBase, session: Session) -> Dict[str, Any]:
        return {
            'id': entity.id,
            'kb_id': entity.kb_id,
            'name': entity.name,
            'description': entity.description or '',
            'persist_directory': entity.persist_directory or '',
            'embedding_provider': entity.embedding_provider or '',
            'embedding_model': entity.embedding_model or '',
            'embedding_base_url': entity.embedding_base_url or '',
            'chunk_size': entity.chunk_size or 500,
            'chunk_overlap': entity.chunk_overlap or 100,
            'status': entity.status,
            'created_at': entity.create_stamp,
            'updated_at': entity.upd_stamp,
        }

    def list_all(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """列出所有知识库（del_flag=0）。"""
        with self._get_session() as session:
            stmt = select(RagKnowledgeBase).where(RagKnowledgeBase.del_flag == '0')
            if enabled_only:
                stmt = stmt.where(RagKnowledgeBase.status == '1')
            stmt = stmt.order_by(RagKnowledgeBase.create_stamp.desc())
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]

    def get_by_kb_id(self, kb_id: str) -> Optional[Dict[str, Any]]:
        """按 kb_id 查询。"""
        with self._get_session() as session:
            stmt = select(RagKnowledgeBase).where(
                RagKnowledgeBase.kb_id == kb_id,
                RagKnowledgeBase.del_flag == '0'
            )
            entity = session.scalar(stmt)
            return self._entity_to_dict(entity, session) if entity else None

    def create_kb(self, kb_id: str, name: str, **kwargs) -> Optional[Dict[str, Any]]:
        """创建知识库。"""
        import uuid
        try:
            with self._get_session() as session:
                entity = RagKnowledgeBase(
                    id=uuid.uuid4().hex,
                    kb_id=kb_id,
                    name=name,
                    **kwargs
                )
                session.add(entity)
                session.commit()
                session.refresh(entity)
                return self._entity_to_dict(entity, session)
        except Exception as e:
            logger.error("[RagKbRepository] create failed: " + str(e))
            return None

    def update_kb(self, kb_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """更新知识库（不可改 id/kb_id）。"""
        try:
            with self._get_session() as session:
                stmt = select(RagKnowledgeBase).where(
                    RagKnowledgeBase.kb_id == kb_id,
                    RagKnowledgeBase.del_flag == '0'
                )
                entity = session.scalar(stmt)
                if not entity:
                    return None
                for k, v in kwargs.items():
                    if hasattr(entity, k) and k not in ('id', 'kb_id'):
                        setattr(entity, k, v)
                session.commit()
                session.refresh(entity)
                return self._entity_to_dict(entity, session)
        except Exception as e:
            logger.error("[RagKbRepository] update failed: " + str(e))
            return None

    def delete_kb(self, kb_id: str) -> bool:
        """软删除知识库（del_flag=1）。"""
        try:
            with self._get_session() as session:
                stmt = select(RagKnowledgeBase).where(
                    RagKnowledgeBase.kb_id == kb_id,
                    RagKnowledgeBase.del_flag == '0'
                )
                entity = session.scalar(stmt)
                if entity:
                    entity.del_flag = '1'
                    session.commit()
                    return True
                return False
        except Exception as e:
            logger.error("[RagKbRepository] delete failed: " + str(e))
            return False
