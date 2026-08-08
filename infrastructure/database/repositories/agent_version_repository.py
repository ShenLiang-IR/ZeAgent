"""Agent 版本快照 repository。

参照 eval_repository.py 风格：BaseRepository[Model, Dict] + 业务查询方法。
"""
from typing import Any

from loguru import logger
from sqlalchemy import and_, select

from infrastructure.database.models.agent_version import AgentVersion
from infrastructure.database.repositories.base_repository import BaseRepository
from infrastructure.database.sessions import get_config_session


class AgentVersionRepository(BaseRepository[AgentVersion, dict[str, Any]]):
    """Agent 版本快照 repository。"""
    _session_factory = get_config_session
    _model_class = AgentVersion
    _pk_name = 'pr_key_id'

    def _entity_to_dict(self, entity: AgentVersion, session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'version_id': entity.version_id,
            'agent_pr_key_id': entity.agent_pr_key_id,
            'version_no': entity.version_no,
            'version_description': entity.version_description,
            'snapshot': entity.snapshot,
            'status': entity.status,
            'workspace_id': entity.workspace_id,
            'create_time': str(entity.create_time) if entity.create_time else None,
            'update_time': str(entity.update_time) if entity.update_time else None,
        }

    def list_by_agent(self, agent_pr_key_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """列出某 agent 的所有版本快照（按时间倒序）。"""
        try:
            with self._get_session() as session:
                stmt = (
                    select(AgentVersion)
                    .where(AgentVersion.agent_pr_key_id == agent_pr_key_id)
                    .order_by(AgentVersion.pr_key_id.desc())
                    .limit(limit)
                )
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"AgentVersionRepository.list_by_agent ({agent_pr_key_id}): {e}", exc_info=True)
            return []

    def get_by_version(self, agent_pr_key_id: int, version_no: str) -> dict[str, Any] | None:
        """按 agent + version_no 查询。"""
        try:
            with self._get_session() as session:
                stmt = select(AgentVersion).where(and_(
                    AgentVersion.agent_pr_key_id == agent_pr_key_id,
                    AgentVersion.version_no == version_no,
                ))
                entity = session.scalar(stmt)
                return self._entity_to_dict(entity, session) if entity else None
        except Exception as e:
            logger.error(f"AgentVersionRepository.get_by_version ({agent_pr_key_id}/{version_no}): {e}", exc_info=True)
            return None

    def get_published(self, agent_pr_key_id: int) -> dict[str, Any] | None:
        """取某 agent 当前 published 版本。"""
        try:
            with self._get_session() as session:
                stmt = select(AgentVersion).where(and_(
                    AgentVersion.agent_pr_key_id == agent_pr_key_id,
                    AgentVersion.status == "published",
                ))
                entity = session.scalar(stmt)
                return self._entity_to_dict(entity, session) if entity else None
        except Exception as e:
            logger.error(f"AgentVersionRepository.get_published ({agent_pr_key_id}): {e}", exc_info=True)
            return None

    def get_pending(self, agent_pr_key_id: int) -> dict[str, Any] | None:
        """取某 agent 当前 pending_review 版本（待审批，至多一个）。"""
        try:
            with self._get_session() as session:
                stmt = select(AgentVersion).where(and_(
                    AgentVersion.agent_pr_key_id == agent_pr_key_id,
                    AgentVersion.status == "pending_review",
                ))
                entity = session.scalar(stmt)
                return self._entity_to_dict(entity, session) if entity else None
        except Exception as e:
            logger.error(f"AgentVersionRepository.get_pending ({agent_pr_key_id}): {e}", exc_info=True)
            return None

    def archive_published(self, agent_pr_key_id: int) -> int:
        """将某 agent 的 published 版本改为 archived（publish 新版本时调用）。

        Returns:
            归档的版本数
        """
        try:
            with self._get_session() as session:
                stmt = select(AgentVersion).where(and_(
                    AgentVersion.agent_pr_key_id == agent_pr_key_id,
                    AgentVersion.status == "published",
                ))
                entities = session.scalars(stmt).all()
                for e in entities:
                    e.status = "archived"
                session.commit()
                return len(entities)
        except Exception as e:
            logger.error(f"AgentVersionRepository.archive_published ({agent_pr_key_id}): {e}", exc_info=True)
            return 0
