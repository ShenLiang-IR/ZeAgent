"""模型配置 Repository（CRUD）。"""
from typing import Dict, Any, Optional, List
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import select, text
from infrastructure.database.sessions import get_config_session
from infrastructure.database.models.model_config import ModelConfig
from infrastructure.database.repositories.base_repository import BaseRepository


class ModelConfigRepository(BaseRepository[ModelConfig, Dict[str, Any]]):
    """模型配置 CRUD。表 tb_model_config（MySQL agent_config 库）。"""
    _session_factory = get_config_session
    _model_class = ModelConfig
    _pk_name = 'id'

    def _entity_to_dict(self, entity: ModelConfig, session: Session) -> Dict[str, Any]:
        return {
            'id': entity.id,
            'model_name': entity.model_name,
            'provider': entity.provider,
            'model_type': entity.model_type,
            'display_name': entity.display_name or '',
            'api_key': entity.api_key or '',
            'api_endpoint_url': entity.api_endpoint_url or '',
            'status': entity.status,
            'fallback_model_id': entity.fallback_model_id,
            'created_at': entity.create_stamp,
            'updated_at': entity.upd_stamp,
        }

    def _ensure_fallback_column(self):
        """确保 tb_model_config.fallback_model_id 列存在（ALTER 幂等，配额 degrade 新增字段）。

        ModelConfig model 有 fallback_model_id 字段（配额 degrade 用），但现有 DB 表无该列，
        查询时 SELECT 该列会 1054 Unknown column。此方法幂等加列。
        """
        if getattr(self, '_fb_col_ensured', False):
            return
        try:
            with self._get_session() as session:
                # 先查列是否存在，避免重复 ALTER 触发 1060 Duplicate column 噪音
                exists = session.execute(text(
                    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tb_model_config' "
                    "AND COLUMN_NAME='fallback_model_id'"
                )).scalar()
                if not exists:
                    session.execute(text(
                        "ALTER TABLE tb_model_config ADD COLUMN fallback_model_id VARCHAR(32) NULL COMMENT '备用模型ID（配额 degrade）'"
                    ))
                    session.commit()
        except Exception:
            pass  # 列已存在则忽略
        self._fb_col_ensured = True

    def list_all(self, enabled_only: bool = False, model_type: str = None) -> List[Dict[str, Any]]:
        self._ensure_fallback_column()
        with self._get_session() as session:
            stmt = select(ModelConfig).where(ModelConfig.del_flag == '0')
            if enabled_only:
                stmt = stmt.where(ModelConfig.status == '1')
            if model_type:
                stmt = stmt.where(ModelConfig.model_type == model_type)
            stmt = stmt.order_by(ModelConfig.create_stamp.desc())
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]

    def get_by_id(self, id_value: str) -> Optional[Dict[str, Any]]:
        self._ensure_fallback_column()
        with self._get_session() as session:
            stmt = select(ModelConfig).where(
                ModelConfig.id == id_value,
                ModelConfig.del_flag == '0'
            )
            entity = session.scalar(stmt)
            return self._entity_to_dict(entity, session) if entity else None

    def create_model(self, model_name: str, provider: str, model_type: str, **kwargs) -> Optional[Dict[str, Any]]:
        import uuid
        try:
            with self._get_session() as session:
                entity = ModelConfig(
                    id=uuid.uuid4().hex,
                    model_name=model_name, provider=provider, model_type=model_type,
                    **kwargs
                )
                session.add(entity)
                session.commit()
                session.refresh(entity)
                return self._entity_to_dict(entity, session)
        except Exception as e:
            logger.error("[ModelConfigRepository] create failed: " + str(e))
            return None

    def update_model(self, id_value: str, **kwargs) -> Optional[Dict[str, Any]]:
        try:
            with self._get_session() as session:
                stmt = select(ModelConfig).where(
                    ModelConfig.id == id_value, ModelConfig.del_flag == '0'
                )
                entity = session.scalar(stmt)
                if not entity:
                    return None
                for k, v in kwargs.items():
                    if hasattr(entity, k) and k != 'id':
                        setattr(entity, k, v)
                session.commit()
                session.refresh(entity)
                return self._entity_to_dict(entity, session)
        except Exception as e:
            logger.error("[ModelConfigRepository] update failed: " + str(e))
            return None

    def delete_model(self, id_value: str) -> bool:
        try:
            with self._get_session() as session:
                stmt = select(ModelConfig).where(
                    ModelConfig.id == id_value, ModelConfig.del_flag == '0'
                )
                entity = session.scalar(stmt)
                if entity:
                    entity.del_flag = '1'
                    session.commit()
                    return True
                return False
        except Exception as e:
            logger.error("[ModelConfigRepository] delete failed: " + str(e))
            return False
