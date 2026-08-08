import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from loguru import logger
from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from infrastructure.database.sessions import get_config_session
from infrastructure.database.models.writing import WritingTemplate, WritingDocument
from infrastructure.database.repositories.base_repository import BaseRepository
class WritingTemplateRepository(BaseRepository[WritingTemplate, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = WritingTemplate
    def _entity_to_dict(self, entity: WritingTemplate, session: Session) -> Dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'template_name': entity.template_name,
            'template_desc': entity.template_desc,
            'template_content': self._parse_json(entity.template_content),
            'status': entity.status,
            'enabled': entity.status == '1',
            'create_teller_no': entity.create_teller_no,
            'latest_enable_time': entity.latest_enable_time.isoformat() if entity.latest_enable_time else None,
            'create_stamp': entity.create_stamp.isoformat() if entity.create_stamp else None,
            'upd_stamp': entity.upd_stamp.isoformat() if entity.upd_stamp else None,
        }
    _pk_name = 'pr_key_id'
    def _parse_json(self, json_str: Optional[str]) -> Optional[Dict]:
        if not json_str:
            return None
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None
    def get_by_id(self, template_id: str, return_dict: bool = True) -> Optional[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(WritingTemplate).where(
                and_(
                    WritingTemplate.pr_key_id == template_id,
                    WritingTemplate.del_flag == '0'
                )
            )
            entity = session.scalar(stmt)
            if entity:
                if return_dict:
                    return self._entity_to_dict(entity, session)
                return entity
            return None
    def get_by_name(self, template_name: str) -> Optional[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(WritingTemplate).where(
                and_(
                    WritingTemplate.template_name == template_name,
                    WritingTemplate.del_flag == '0'
                )
            )
            entity = session.scalar(stmt)
            if entity:
                return self._entity_to_dict(entity, session)
            return None
    def get_all(self, enabled_only: bool = False, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(WritingTemplate).where(WritingTemplate.del_flag == '0')
            if enabled_only:
                stmt = stmt.where(WritingTemplate.status == '1')
            if status:
                stmt = stmt.where(WritingTemplate.template_status == status)
            stmt = stmt.order_by(WritingTemplate.update_time.desc())
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]
    def save_template(
        self,
        template_id: str,
        template_name: str,
        template_content: Dict[str, Any],
        template_desc: Optional[str] = None,
        status: str = "0",
        create_teller_no: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        try:
            now = datetime.now()
            content_json = json.dumps(template_content, ensure_ascii=False) if template_content else "{}"
            with self._get_session() as session:
                stmt = select(WritingTemplate).where(
                    and_(
                        WritingTemplate.pr_key_id == template_id,
                        WritingTemplate.del_flag == '0'
                    )
                )
                entity = session.scalar(stmt)
                if entity:
                    entity.template_name = template_name
                    entity.template_content = content_json
                    entity.template_desc = template_desc
                    entity.status = status
                    entity.upd_stamp = now
                else:
                    entity = WritingTemplate(
                        pr_key_id=template_id,
                        template_name=template_name,
                        template_content=content_json,
                        template_desc=template_desc,
                        status=status,
                        create_teller_no=create_teller_no,
                        create_stamp=now,
                        upd_stamp=now,
                        del_flag='0'
                    )
                    session.add(entity)
                session.commit()
                session.refresh(entity)
                return self._entity_to_dict(entity, session)
        except Exception as e:
            logger.error(f"[WritingTemplateRepository] : {e}")
            return None
    def delete_template(self, template_id: str) -> bool:
        try:
            with self._get_session() as session:
                stmt = select(WritingTemplate).where(
                    and_(
                        WritingTemplate.pr_key_id == template_id,
                        WritingTemplate.del_flag == '0'
                    )
                )
                entity = session.scalar(stmt)
                if entity:
                    entity.del_flag = '1'
                    entity.update_time = datetime.now()
                    session.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"[WritingTemplateRepository] : {e}")
            return False
class WritingDocumentRepository(BaseRepository[WritingDocument, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = WritingDocument
    def _entity_to_dict(self, entity: WritingDocument, session: Session) -> Dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'doc_name': entity.doc_name,
            'template_id': entity.template_id,
            'template_name': entity.template_name,
            'doc_status': entity.doc_status,
            'doc_content': self._parse_json(entity.doc_content),
            'creator_id': entity.creator_id,
            'creator_name': entity.creator_name,
            'create_stamp': entity.create_stamp.isoformat() if entity.create_stamp else None,
            'upd_stamp': entity.upd_stamp.isoformat() if entity.upd_stamp else None,
        }
    _pk_name = 'pr_key_id'
    def _parse_json(self, json_str: Optional[str]) -> Optional[Dict]:
        if not json_str:
            return None
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None
    def get_by_id(self, document_id: str, return_dict: bool = True) -> Optional[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(WritingDocument).where(
                and_(
                    WritingDocument.pr_key_id == document_id,
                    WritingDocument.del_flag == '0'
                )
            )
            entity = session.scalar(stmt)
            if entity:
                if return_dict:
                    return self._entity_to_dict(entity, session)
                return entity
            return None
    def get_by_template(
        self,
        template_id: str,
        creator_id: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(WritingDocument).where(
                and_(
                    WritingDocument.template_id == template_id,
                    WritingDocument.del_flag == '0'
                )
            )
            if creator_id:
                stmt = stmt.where(WritingDocument.creator_id == creator_id)
            stmt = stmt.order_by(WritingDocument.update_time.desc()).limit(limit)
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]
    def get_by_creator(
        self,
        creator_id: str,
        status: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(WritingDocument).where(
                and_(
                    WritingDocument.creator_id == creator_id,
                    WritingDocument.del_flag == '0'
                )
            )
            if status:
                stmt = stmt.where(WritingDocument.doc_status == status)
            stmt = stmt.order_by(WritingDocument.update_time.desc()).limit(limit)
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]
    def save_document(
        self,
        document_id: str,
        doc_name: str,
        template_id: Optional[str] = None,
        template_name: Optional[str] = None,
        doc_status: str = "PROCESSING",
        doc_content: Optional[Dict[str, Any]] = None,
        creator_id: Optional[str] = None,
        creator_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        try:
            now = datetime.now()
            content_json = json.dumps(doc_content, ensure_ascii=False) if doc_content else None
            with self._get_session() as session:
                stmt = select(WritingDocument).where(
                    and_(
                        WritingDocument.pr_key_id == document_id,
                        WritingDocument.del_flag == '0'
                    )
                )
                entity = session.scalar(stmt)
                if entity:
                    entity.doc_name = doc_name
                    entity.template_id = template_id
                    entity.template_name = template_name
                    entity.doc_status = doc_status
                    if doc_content:
                        entity.doc_content = content_json
                    entity.upd_stamp = now
                else:
                    entity = WritingDocument(
                        pr_key_id=document_id,
                        doc_name=doc_name,
                        template_id=template_id,
                        template_name=template_name,
                        doc_status=doc_status,
                        doc_content=content_json,
                        creator_id=creator_id,
                        creator_name=creator_name,
                        create_stamp=now,
                        upd_stamp=now,
                        del_flag='0'
                    )
                    session.add(entity)
                session.commit()
                session.refresh(entity)
                return self._entity_to_dict(entity, session)
        except Exception as e:
            logger.error(f"[WritingDocumentRepository] : {e}")
            return None
    def update_status(
        self,
        document_id: str,
        doc_status: str,
        doc_content: Optional[Dict[str, Any]] = None
    ) -> bool:
        try:
            with self._get_session() as session:
                stmt = select(WritingDocument).where(
                    and_(
                        WritingDocument.pr_key_id == document_id,
                        WritingDocument.del_flag == '0'
                    )
                )
                entity = session.scalar(stmt)
                if entity:
                    entity.doc_status = doc_status
                    if doc_content:
                        entity.doc_content = json.dumps(doc_content, ensure_ascii=False)
                    entity.upd_stamp = datetime.now()
                    session.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"[WritingDocumentRepository] : {e}")
            return False
    def update_content(
        self,
        document_id: str,
        doc_content: Dict[str, Any],
        doc_status: Optional[str] = None
    ) -> bool:
        try:
            with self._get_session() as session:
                stmt = select(WritingDocument).where(
                    and_(
                        WritingDocument.pr_key_id == document_id,
                        WritingDocument.del_flag == '0'
                    )
                )
                entity = session.scalar(stmt)
                if entity:
                    entity.doc_content = json.dumps(doc_content, ensure_ascii=False)
                    if doc_status:
                        entity.doc_status = doc_status
                    entity.upd_stamp = datetime.now()
                    session.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"[WritingDocumentRepository] : {e}")
            return False
    def delete_document(self, document_id: str) -> bool:
        try:
            with self._get_session() as session:
                stmt = select(WritingDocument).where(
                    and_(
                        WritingDocument.pr_key_id == document_id,
                        WritingDocument.del_flag == '0'
                    )
                )
                entity = session.scalar(stmt)
                if entity:
                    entity.del_flag = '1'
                    entity.upd_stamp = datetime.now()
                    session.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"[WritingDocumentRepository] : {e}")
            return False
template_repository = WritingTemplateRepository()
document_repository = WritingDocumentRepository()