"""Prompt 模板 repository。

参照 eval_repository.py 风格：BaseRepository[Model, Dict] + 业务查询方法。
"""
from typing import Any

from loguru import logger
from sqlalchemy import select

from infrastructure.database.models.prompt_template import PromptTemplate
from infrastructure.database.repositories.base_repository import BaseRepository
from infrastructure.database.sessions import get_config_session


class PromptTemplateRepository(BaseRepository[PromptTemplate, dict[str, Any]]):
    """Prompt 模板 repository。"""
    _session_factory = get_config_session
    _model_class = PromptTemplate
    _pk_name = 'pr_key_id'

    def _entity_to_dict(self, entity: PromptTemplate, session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'template_id': entity.template_id,
            'name': entity.name,
            'content': entity.content,
            'variables': entity.variables,
            'version': entity.version,
            'description': entity.description,
            'workspace_id': entity.workspace_id,
            'enabled': entity.enabled,
            'create_time': str(entity.create_time) if entity.create_time else None,
            'update_time': str(entity.update_time) if entity.update_time else None,
        }

    def get_by_name(self, name: str) -> dict[str, Any] | None:
        """按名称查询模板。"""
        try:
            with self._get_session() as session:
                stmt = select(PromptTemplate).where(PromptTemplate.name == name)
                entity = session.scalar(stmt)
                return self._entity_to_dict(entity, session) if entity else None
        except Exception as e:
            logger.error(f"PromptTemplateRepository.get_by_name ({name}): {e}", exc_info=True)
            return None

    def list_enabled(self, workspace_id: int | None = None) -> list[dict[str, Any]]:
        """列出启用的模板（可选 workspace 过滤）。"""
        try:
            with self._get_session() as session:
                stmt = select(PromptTemplate).where(PromptTemplate.enabled == "1")
                if workspace_id is not None:
                    stmt = stmt.where(PromptTemplate.workspace_id == workspace_id)
                stmt = stmt.order_by(PromptTemplate.pr_key_id.desc())
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"PromptTemplateRepository.list_enabled: {e}", exc_info=True)
            return []
