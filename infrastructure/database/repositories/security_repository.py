"""敏感词 repository。"""
from typing import Any
from loguru import logger
from sqlalchemy.orm import Session

from infrastructure.database.models.security import SensitiveWord
from infrastructure.database.repositories.base_repository import BaseRepository
from infrastructure.database.sessions import get_config_session


class SensitiveWordRepository(BaseRepository[SensitiveWord, dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = SensitiveWord
    _pk_name = 'pr_key_id'

    def _entity_to_dict(self, entity: SensitiveWord, session: Session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'word': entity.word,
            'category': entity.category,
            'enabled': entity.enabled,
            'create_time': str(entity.create_time) if entity.create_time else None,
        }

    def get_enabled_words(self) -> list[str]:
        """获取所有已启用的敏感词。"""
        try:
            with self._get_session() as session:
                from sqlalchemy import select
                rows = session.execute(
                    select(SensitiveWord.word).where(SensitiveWord.enabled == 1)
                ).scalars().all()
                return list(rows)
        except Exception as e:
            logger.warning(f"[SensitiveWord] get_enabled_words: {e}")
            return []
