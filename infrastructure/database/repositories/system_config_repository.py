from typing import Dict, Optional, Any
from loguru import logger
from sqlalchemy.orm import Session
from ..sessions import get_config_session
from ..models.config import SystemConfig
from .base_repository import BaseRepository
class SystemConfigRepository(BaseRepository[SystemConfig, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = SystemConfig
    def _entity_to_dict(self, entity: SystemConfig, session: Session) -> Dict[str, Any]:
        return {
            'id': entity.id,
            'key': entity.key,
            'value': entity.value or '',
            'created_at': entity.create_time,
            'updated_at': entity.update_time
        }
    _pk_name = 'key'
    def get_config(self, key: str) -> Optional[str]:
        config = self.get_by_id(key, return_dict=False)
        return config.value if config else None
    def set_config(self, key: str, value: str) -> bool:
        try:
            existing = self.get_by_id(key, return_dict=False)
            if existing:
                updated = self.update(key, value=value)
                return updated is not None
            else:
                created = self.create(key=key, value=value)
                return created is not None
        except Exception as e:
            logger.error(f"系统配置仓储操作失败: {e}", exc_info=True)
            return False
    def get_all_configs(self) -> Dict[str, str]:
        try:
            configs = self.get_all(return_dict=False)
            return {config.key: config.value or '' for config in configs}
        except Exception as e:
            logger.error(f"系统配置仓储操作失败: {e}", exc_info=True)
            return {}