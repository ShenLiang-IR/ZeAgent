from typing import Any

from loguru import logger
from sqlalchemy import and_, select, text
from sqlalchemy.orm import Session

from infrastructure.database.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseDocument,
    KnowledgeBaseSqlModel,
    KnowledgeBaseTableField,
)
from infrastructure.database.repositories.base_repository import BaseRepository
from infrastructure.database.sessions import get_config_session


class KnowledgeBaseRepository(BaseRepository[KnowledgeBase, dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = KnowledgeBase
    def _entity_to_dict(self, entity: KnowledgeBase, session: Session) -> dict[str, Any]:
        created_at = getattr(entity, 'create_stamp', None) or getattr(entity, 'create_time', None)
        updated_at = getattr(entity, 'upd_stamp', None) or getattr(entity, 'update_time', None)
        return {
            'pr_key_id': entity.pr_key_id,
            'knowledge_base_id': entity.knowledge_base_id,
            'knowledge_name': entity.knowledge_name,
            'knowledge_type': entity.knowledge_type,
            'description': entity.description or '',
            'business_type': entity.business_type or '',
            'visible_scope': entity.visible_scope,
            'document_types': entity.document_types,
            'embedding_model': entity.embedding_model or '',
            'chunk_size': entity.chunk_size,
            'overlap_size': entity.overlap_size,
            'public_access': entity.public_access,
            'hit_count': entity.hit_count or 0,
            'tags': entity.tags or '',
            'status': entity.status,
            'enabled': entity.status == '1',
            'segment_strategy': entity.segment_strategy or '',
            'level_count': entity.level_count,
            'level_switch': entity.level_switch,
            'database_type': entity.database_type or '',
            'database_table': entity.database_table or '',
            'label_extraction_rule': entity.label_extraction_rule or '',
            'workspace_id': entity.workspace_id,
            'created_at': created_at,
            'updated_at': updated_at
        }
    _pk_name = 'knowledge_base_id'
    def get_by_id(self, kb_id: str, return_dict: bool = True) -> KnowledgeBase | dict[str, Any] | None:
        return super().get_by_id(kb_id, return_dict=return_dict)
    def get_by_name(self, kb_name: str) -> dict[str, Any] | None:
        with self._get_session() as session:
            stmt = select(KnowledgeBase).where(
                and_(
                    KnowledgeBase.knowledge_name == kb_name,
                    KnowledgeBase.del_flag == '0'
                )
            )
            result = session.execute(stmt)
            entity = result.scalar_one_or_none()
            if entity:
                return self._entity_to_dict(entity, session)
            return None
    def _ensure_workspace_column(self):
        """确保 tb_knowledge_base.workspace_id 列存在（ALTER 幂等，现有表加字段）。"""
        if getattr(self, '_ws_col_ensured', False):
            return
        try:
            with self._get_session() as session:
                session.execute(text("ALTER TABLE tb_knowledge_base ADD COLUMN workspace_id BIGINT NULL"))
                session.commit()
        except Exception:
            pass  # 列已存在则忽略
        self._ws_col_ensured = True

    def get_all(self, enabled_only: bool = False, kb_type: str | None = None,
                workspace_id: int | None = None) -> list[dict[str, Any]]:
        self._ensure_workspace_column()
        with self._get_session() as session:
            stmt = select(KnowledgeBase).where(KnowledgeBase.del_flag == '0')
            if enabled_only:
                stmt = stmt.where(KnowledgeBase.status == '1')
            if kb_type:
                stmt = stmt.where(KnowledgeBase.knowledge_type == kb_type)
            if workspace_id is not None:
                stmt = stmt.where(KnowledgeBase.workspace_id == workspace_id)
            stmt = stmt.order_by(KnowledgeBase.knowledge_base_id)
            entities = session.scalars(stmt).all()
            result = [self._entity_to_dict(e, session) for e in entities]
            logger.debug(f"[KnowledgeBaseRepository] get_all: enabled_only={enabled_only}, kb_type={kb_type},  {len(result)} ")
            return result
    def get_unstructured(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        return self.get_all(enabled_only=enabled_only, kb_type=KnowledgeBase.TYPE_UNSTRUCTURED)
    def get_structured(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        return self.get_all(enabled_only=enabled_only, kb_type=KnowledgeBase.TYPE_STRUCTURED)
    def save_knowledge_base(
        self,
        kb_id: str,
        kb_name: str,
        kb_type: str,
        description: str = "",
        business_type: str = "",
        visible_scope: str = "1",
        document_types: str = "[]",
        embedding_model: str = "",
        chunk_size: int = 1000,
        overlap_size: int = 200,
        public_access: str = "0",
        tags: str = "",
        segment_strategy: str = "0",
        level_count: str = "2",
        level_switch: str = "0",
        database_type: str = "",
        database_table: str = "",
        label_extraction_rule: str = "",
        enabled: bool = True
    ) -> bool:
        try:
            kb_data = {
                'knowledge_name': kb_name,
                'knowledge_type': kb_type,
                'description': description,
                'business_type': business_type,
                'visible_scope': visible_scope,
                'document_types': document_types,
                'embedding_model': embedding_model,
                'chunk_size': chunk_size,
                'overlap_size': overlap_size,
                'public_access': public_access,
                'tags': tags,
                'status': '1' if enabled else '0',
                'segment_strategy': segment_strategy,
                'level_count': level_count,
                'level_switch': level_switch,
                'database_type': database_type,
                'database_table': database_table,
                'label_extraction_rule': label_extraction_rule,
                'del_flag': '0'
            }
            entity = self.upsert(kb_id, **kb_data)
            return entity is not None
        except Exception as e:
            logger.error(f"知识库仓储操作失败: {e}", exc_info=True)
            return False
    def delete_knowledge_base(self, kb_id: str) -> bool:
        try:
            with self._get_session() as session:
                session.query(KnowledgeBase).filter(
                    KnowledgeBase.knowledge_base_id == kb_id
                ).update({'del_flag': '1'})
                session.commit()
            return True
        except Exception as e:
            logger.error(f"知识库仓储操作失败: {e}", exc_info=True)
            return False
class KnowledgeBaseSqlModelRepository(BaseRepository[KnowledgeBaseSqlModel, dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = KnowledgeBaseSqlModel
    def _entity_to_dict(self, entity: KnowledgeBaseSqlModel, session: Session) -> dict[str, Any]:
        created_at = getattr(entity, 'create_stamp', None) or getattr(entity, 'create_time', None)
        updated_at = getattr(entity, 'upd_stamp', None) or getattr(entity, 'update_time', None)
        return {
            'pr_key_id': entity.pr_key_id,
            'sql_model_id': entity.sql_model_id,
            'knowledge_base_id': entity.knowledge_base_id,
            'sql_model_name': entity.sql_model_name,
            'sql_model_description': entity.sql_model_description or '',
            'sql_execution_config': entity.sql_execution_config or '',
            'created_at': created_at,
            'updated_at': updated_at
        }
    _pk_name = 'sql_model_id'
    def get_by_kb(self, knowledge_base_id: str) -> list[dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(KnowledgeBaseSqlModel).where(
                and_(
                    KnowledgeBaseSqlModel.knowledge_base_id == knowledge_base_id,
                    KnowledgeBaseSqlModel.del_flag == '0'
                )
            )
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]
class KnowledgeBaseDocumentRepository(BaseRepository[KnowledgeBaseDocument, dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = KnowledgeBaseDocument
    def _entity_to_dict(self, entity: KnowledgeBaseDocument, session: Session) -> dict[str, Any]:
        created_at = getattr(entity, 'create_stamp', None) or getattr(entity, 'create_time', None)
        updated_at = getattr(entity, 'upd_stamp', None) or getattr(entity, 'update_time', None)
        return {
            'pr_key_id': entity.pr_key_id,
            'file_id': entity.file_id,
            'knowledge_base_id': entity.knowledge_base_id,
            'document_name': entity.document_name,
            'description': entity.description or '',
            'document_type': entity.document_type,
            'file_path': entity.file_path,
            'bucket_name': entity.bucket_name,
            'file_size': entity.file_size,
            'file_hash': entity.file_hash,
            'recognition_rules': entity.recognition_rules,
            'segment_strategy': entity.segment_strategy,
            'status': entity.status,
            'total_chunks': entity.total_chunks,
            'processed_chunks': entity.processed_chunks,
            'error_message': entity.error_message,
            'created_at': created_at,
            'updated_at': updated_at
        }
    _pk_name = 'file_id'
    def get_by_kb(self, knowledge_base_id: str, status: str = None) -> list[dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(KnowledgeBaseDocument).where(
                and_(
                    KnowledgeBaseDocument.knowledge_base_id == knowledge_base_id,
                    KnowledgeBaseDocument.del_flag == '0'
                )
            )
            if status:
                stmt = stmt.where(KnowledgeBaseDocument.status == status)
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]
    def update_status(
        self,
        file_id: str,
        status: str,
        total_chunks: int = None,
        processed_chunks: int = None,
        error_message: str = None
    ) -> bool:
        try:
            with self._get_session() as session:
                update_data = {'status': status}
                if total_chunks is not None:
                    update_data['total_chunks'] = total_chunks
                if processed_chunks is not None:
                    update_data['processed_chunks'] = processed_chunks
                if error_message is not None:
                    update_data['error_message'] = error_message
                result = session.query(KnowledgeBaseDocument).filter(
                    and_(
                        KnowledgeBaseDocument.file_id == file_id,
                        KnowledgeBaseDocument.del_flag == '0'
                    )
                ).update(update_data)
                session.commit()
                if result > 0:
                    logger.debug(f"文件处理: file_id={file_id}, status={status}")
                    return True
                else:
                    logger.warning(f"文件未找到: file_id={file_id}")
                    return False
        except Exception as e:
            logger.error(f"知识库仓储操作失败: {e}", exc_info=True)
            return False
class KnowledgeBaseTableFieldRepository(BaseRepository[KnowledgeBaseTableField, dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = KnowledgeBaseTableField
    def _entity_to_dict(self, entity: KnowledgeBaseTableField, session: Session) -> dict[str, Any]:
        created_at = getattr(entity, 'create_stamp', None) or getattr(entity, 'create_time', None)
        updated_at = getattr(entity, 'upd_stamp', None) or getattr(entity, 'update_time', None)
        return {
            'pr_key_id': entity.pr_key_id,
            'knowledge_base_id': entity.knowledge_base_id,
            'table_name': entity.table_name,
            'field_name': entity.field_name,
            'field_type': entity.field_type or '',
            'field_desc': entity.field_desc or '',
            'enable_flag': entity.enable_flag,
            'created_at': created_at,
            'updated_at': updated_at
        }
    _pk_name = 'pr_key_id'
    def get_by_kb(self, knowledge_base_id: str) -> list[dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(KnowledgeBaseTableField).where(
                and_(
                    KnowledgeBaseTableField.knowledge_base_id == knowledge_base_id,
                    KnowledgeBaseTableField.del_flag == '0'
                )
            )
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]
    def get_enabled_by_kb(self, knowledge_base_id: str) -> list[dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(KnowledgeBaseTableField).where(
                and_(
                    KnowledgeBaseTableField.knowledge_base_id == knowledge_base_id,
                    KnowledgeBaseTableField.del_flag == '0',
                    KnowledgeBaseTableField.enable_flag == '1'
                )
            ).order_by(KnowledgeBaseTableField.table_name, KnowledgeBaseTableField.field_name)
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]
