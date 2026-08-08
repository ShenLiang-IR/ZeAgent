import json
from typing import Dict, Any, Optional, List
from sqlalchemy import select, and_
from loguru import logger
from infrastructure.database.models.sys_model_res_mgmt import SysModelResMgmt
from infrastructure.database.repositories.base_repository import BaseRepository
from infrastructure.database.sessions import get_config_session
class SysModelResMgmtRepository(BaseRepository[SysModelResMgmt, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = SysModelResMgmt
    _pk_name = 'pr_key_id'
    def _entity_to_dict(self, entity: SysModelResMgmt, session=None) -> Dict[str, Any]:
        extra_config = {}
        scene_desc = (entity.scene_desc or '').strip()
        if scene_desc:
            if scene_desc.startswith('{'):
                try:
                    extra_config = json.loads(scene_desc)
                except (json.JSONDecodeError, TypeError) as e:
                    logger.debug(f"[SysModelResMgmtRepository] scene_desc  JSON : {e}")
        return {
            'pr_key_id': entity.pr_key_id,
            'risk_model_name': entity.risk_model_name,
            'model_id': entity.model_id,
            'model_tp_cls': entity.model_tp_cls,
            'model_desc': entity.model_desc,
            'spec_model_label': entity.spec_model_label,
            'website_hpg_url': entity.website_hpg_url,
            'model_name': entity.model_id,
            'base_url': entity.website_hpg_url,
            'api_key': entity.sgnt_pwfatt_info,
            'temperature': float(entity.temperat) if entity.temperat is not None else 0.7,
            'max_tokens': entity.max_serv_num,
            'extra_config': extra_config,
            'sgnt_pwfatt_info': entity.sgnt_pwfatt_info,
            'temperat': float(entity.temperat) if entity.temperat is not None else None,
            'scene_desc': entity.scene_desc,
            'model_status': entity.model_status,
            'del_flag': entity.del_flag,
            'create_stamp': entity.create_stamp,
            'upd_stamp': entity.upd_stamp
        }
    def create(self, **kwargs) -> SysModelResMgmt:
        with self._get_session() as session:
            new_record = self._model_class(**kwargs)
            session.add(new_record)
            session.commit()
            session.refresh(new_record)
            return new_record
    def get_by_id(self, pr_key_id: str, return_dict: bool = False) -> Optional[SysModelResMgmt | Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(self._model_class).where(
                and_(
                    self._model_class.pr_key_id == pr_key_id,
                    self._model_class.del_flag == '0'
                )
            )
            entity = session.scalar(stmt)
            if entity and return_dict:
                return self._entity_to_dict(entity, session)
            return entity
    def update(self, pr_key_id: str, **kwargs) -> Optional[SysModelResMgmt]:
        with self._get_session() as session:
            stmt = select(self._model_class).where(
                and_(
                    self._model_class.pr_key_id == pr_key_id,
                    self._model_class.del_flag == '0'
                )
            )
            record = session.scalar(stmt)
            if record:
                for key, value in kwargs.items():
                    if hasattr(record, key):
                        setattr(record, key, value)
                session.commit()
                session.refresh(record)
                return record
            return None
    def delete(self, pr_key_id: str) -> bool:
        with self._get_session() as session:
            stmt = select(self._model_class).where(
                and_(
                    self._model_class.pr_key_id == pr_key_id,
                    self._model_class.del_flag == '0'
                )
            )
            record = session.scalar(stmt)
            if record:
                record.del_flag = '1'
                session.commit()
                return True
            return False
    def get_all(self, return_dict: bool = True) -> List[SysModelResMgmt | Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(self._model_class).where(self._model_class.del_flag == '0')
            entities = session.scalars(stmt).all()
            if return_dict:
                return [self._entity_to_dict(e, session) for e in entities]
            return entities
    def get_by_model_type(
        self,
        model_tp_cls: str,
        model_status: str = '0',
        return_dict: bool = True
    ) -> List[SysModelResMgmt | Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(self._model_class).where(
                and_(
                    self._model_class.model_tp_cls == model_tp_cls,
                    self._model_class.model_status == model_status,
                    self._model_class.del_flag == '0'
                )
            )
            entities = session.scalars(stmt).all()
            if return_dict:
                return [self._entity_to_dict(e, session) for e in entities]
            return entities
    def get_available_model_by_id(self, pr_key_id: str) -> Optional[Dict[str, Any]]:
        try:
            with self._get_session() as session:
                stmt = select(self._model_class).where(
                    and_(
                        self._model_class.pr_key_id == pr_key_id,
                        self._model_class.del_flag == '0',
                        self._model_class.model_status == '0'
                    )
                )
                entity = session.scalar(stmt)
                if entity:
                    result = self._entity_to_dict(entity, session)
                    logger.debug(f"[SysModelResMgmtRepository] : {entity.risk_model_name} ({pr_key_id})")
                    return result
                else:
                    logger.debug(f"[SysModelResMgmtRepository] : {pr_key_id}")
                return None
        except Exception as e:
            logger.error(f"[SysModelResMgmtRepository]  (pr_key_id={pr_key_id}): {str(e)}", exc_info=True)
            return None
    def get_all_available(self) -> List[Dict[str, Any]]:
        try:
            with self._get_session() as session:
                stmt = select(self._model_class).where(
                    and_(
                        self._model_class.del_flag == '0',
                        self._model_class.model_status == '0'
                    )
                ).order_by(self._model_class.pr_key_id)
                entities = session.scalars(stmt).all()
                result = [self._entity_to_dict(e, session) for e in entities]
                logger.debug(f"[SysModelResMgmtRepository]  {len(result)} ")
                return result
        except Exception as e:
            logger.error(f"[SysModelResMgmtRepository] : {str(e)}", exc_info=True)
            return []
    def get_model_by_name(self, risk_model_name: str) -> Optional[Dict[str, Any]]:
        try:
            with self._get_session() as session:
                stmt = select(self._model_class).where(
                    and_(
                        self._model_class.risk_model_name == risk_model_name,
                        self._model_class.del_flag == '0',
                        self._model_class.model_status == '0'
                    )
                )
                entity = session.scalar(stmt)
                if entity:
                    return self._entity_to_dict(entity, session)
                return None
        except Exception as e:
            logger.error(f"[SysModelResMgmtRepository]  (name={risk_model_name}): {str(e)}", exc_info=True)
            return None