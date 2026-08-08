"""触发器 + 触发日志 repository。

参照 workspace_repository.py + agent_relation_repository.py 风格：
- BaseRepository[Model, Dict] 抽象基类
- 类属性 _session_factory / _model_class / _pk_name
- 重写 _entity_to_dict
- 业务方法（get_by_trigger_id / get_logs_by_trigger 等）
"""
from typing import Any

from loguru import logger
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from infrastructure.database.models.trigger import Trigger, TriggerLog
from infrastructure.database.repositories.base_repository import BaseRepository
from infrastructure.database.sessions import get_config_session


class TriggerRepository(BaseRepository[Trigger, dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = Trigger
    _pk_name = 'pr_key_id'

    def _entity_to_dict(self, entity: Trigger, session: Session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'trigger_id': entity.trigger_id,
            'trigger_name': entity.trigger_name or '',
            'trigger_type': entity.trigger_type or '',
            'config': entity.config or '',
            'target_agent_ids': entity.target_agent_ids or '',
            'target_mode': entity.target_mode or 'parallel',
            'message_template': entity.message_template or '',
            'workspace_id': entity.workspace_id,
            'enabled': entity.enabled or '1',
            'del_flag': entity.del_flag or '0',
            'creator_id': entity.creator_id,
            'create_time': str(entity.create_time) if entity.create_time else None,
            'update_time': str(entity.update_time) if entity.update_time else None,
        }

    def get_by_trigger_id(self, trigger_id: str) -> dict[str, Any] | None:
        """按业务 ID（TRG_xxx）查触发器。"""
        try:
            with self._get_session() as session:
                stmt = select(Trigger).where(
                    and_(Trigger.trigger_id == trigger_id, Trigger.del_flag == '0')
                )
                entity = session.scalar(stmt)
                return self._entity_to_dict(entity, session) if entity else None
        except Exception as e:
            logger.error(f"TriggerRepository.get_by_trigger_id ({trigger_id}): {e}", exc_info=True)
            return None

    def list_by_workspace(self, workspace_id: int, enabled_only: bool = False) -> list[dict[str, Any]]:
        """列出 workspace 下的所有触发器。"""
        try:
            with self._get_session() as session:
                stmt = select(Trigger).where(
                    and_(Trigger.workspace_id == workspace_id, Trigger.del_flag == '0')
                )
                if enabled_only:
                    stmt = stmt.where(Trigger.enabled == '1')
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"TriggerRepository.list_by_workspace ({workspace_id}): {e}", exc_info=True)
            return []

    def list_enabled(self) -> list[dict[str, Any]]:
        """列出所有启用的触发器（lifespan startup 时调用）。"""
        try:
            with self._get_session() as session:
                stmt = select(Trigger).where(
                    and_(Trigger.enabled == '1', Trigger.del_flag == '0')
                )
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"TriggerRepository.list_enabled: {e}", exc_info=True)
            return []

    def soft_delete(self, trigger_id: str) -> bool:
        """软删触发器。"""
        try:
            with self._get_session() as session:
                stmt = select(Trigger).where(Trigger.trigger_id == trigger_id)
                entity = session.scalar(stmt)
                if not entity:
                    return False
                entity.del_flag = '1'
                session.commit()
                return True
        except Exception as e:
            logger.error(f"TriggerRepository.soft_delete ({trigger_id}): {e}", exc_info=True)
            return False


class TriggerLogRepository(BaseRepository[TriggerLog, dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = TriggerLog
    _pk_name = 'pr_key_id'

    def _entity_to_dict(self, entity: TriggerLog, session: Session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'log_id': entity.log_id,
            'trigger_id': entity.trigger_id,
            'trigger_type': entity.trigger_type or '',
            'event_data': entity.event_data or '',
            'dispatch_id': entity.dispatch_id,
            'status': entity.status or 'running',
            'error': entity.error or '',
            'duration_ms': entity.duration_ms,
            'create_time': str(entity.create_time) if entity.create_time else None,
        }

    def list_by_trigger(self, trigger_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """查询某触发器的执行历史（按时间倒序）。"""
        try:
            with self._get_session() as session:
                stmt = (
                    select(TriggerLog)
                    .where(TriggerLog.trigger_id == trigger_id)
                    .order_by(TriggerLog.pr_key_id.desc())
                    .limit(limit)
                )
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"TriggerLogRepository.list_by_trigger ({trigger_id}): {e}", exc_info=True)
            return []

    def update_status(self, log_id: str, status: str, error: str | None = None,
                      dispatch_id: str | None = None) -> bool:
        """更新日志状态（用于 handle 完成后补写 status/dispatch_id/error）。"""
        try:
            with self._get_session() as session:
                stmt = select(TriggerLog).where(TriggerLog.log_id == log_id)
                entity = session.scalar(stmt)
                if not entity:
                    return False
                entity.status = status
                if error is not None:
                    entity.error = error[:500]
                if dispatch_id is not None:
                    entity.dispatch_id = dispatch_id
                session.commit()
                return True
        except Exception as e:
            logger.error(f"TriggerLogRepository.update_status ({log_id}): {e}", exc_info=True)
            return False
