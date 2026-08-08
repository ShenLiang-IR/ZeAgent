"""成本统计 repository：UsageRepository + QuotaRepository。

参照 trigger_repository.py 风格 + _ensure_table 幂等建表。
"""
from typing import Any

from loguru import logger
from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session

from infrastructure.database.models.usage import Quota, UsageRecord
from infrastructure.database.repositories.base_repository import BaseRepository
from infrastructure.database.sessions import get_config_session


class UsageRepository(BaseRepository[UsageRecord, dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = UsageRecord
    _pk_name = 'pr_key_id'
    _table_ensured = False

    def _ensure_table(self):
        """确保 tb_usage_record 表存在（幂等）。"""
        if UsageRepository._table_ensured:
            return
        try:
            from infrastructure.database.base import Base
            from infrastructure.database.engines import get_config_engine
            Base.metadata.create_all(get_config_engine(), tables=[UsageRecord.__table__], checkfirst=True)
            UsageRepository._table_ensured = True
        except Exception:
            pass

    def create(self, **kwargs):
        self._ensure_table()
        return super().create(**kwargs)

    def _entity_to_dict(self, entity: UsageRecord, session: Session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'usage_id': entity.usage_id,
            'dispatch_id': entity.dispatch_id,
            'trigger_id': entity.trigger_id,
            'workspace_id': entity.workspace_id,
            'agent_id': entity.agent_id,
            'user_id': entity.user_id,
            'model_id': entity.model_id,
            'prompt_tokens': entity.prompt_tokens,
            'completion_tokens': entity.completion_tokens,
            'total_tokens': entity.total_tokens,
            'cost_usd': float(entity.cost_usd) if entity.cost_usd else 0.0,
            'duration_ms': entity.duration_ms,
            'create_time': str(entity.create_time) if entity.create_time else None,
        }

    def get_workspace_usage(self, workspace_id: int, start_date: str | None = None,
                            end_date: str | None = None, group_by: str = "day") -> list[dict[str, Any]]:
        """按 workspace 聚合用量（按日期分组）。"""
        self._ensure_table()
        try:
            with self._get_session() as session:
                stmt = (
                    select(UsageRecord)
                    .where(UsageRecord.workspace_id == workspace_id)
                    .order_by(UsageRecord.pr_key_id.desc())
                )
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            # 用 opt(exception=True) 避免 loguru .format() 把异常字符串里的 {xxx} 当占位符
            logger.opt(exception=True).error("UsageRepository.get_workspace_usage failed: " + str(e).replace("{", "{{").replace("}", "}}"))
            return []


class QuotaRepository(BaseRepository[Quota, dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = Quota
    _pk_name = 'pr_key_id'
    _table_ensured = False

    def _ensure_table(self):
        """确保 tb_quota 表存在（幂等）。"""
        if QuotaRepository._table_ensured:
            return
        try:
            from infrastructure.database.base import Base
            from infrastructure.database.engines import get_config_engine
            Base.metadata.create_all(get_config_engine(), tables=[Quota.__table__], checkfirst=True)
            QuotaRepository._table_ensured = True
        except Exception:
            pass

    def create(self, **kwargs):
        self._ensure_table()
        return super().create(**kwargs)

    def _entity_to_dict(self, entity: Quota, session: Session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'workspace_id': entity.workspace_id,
            'quota_type': entity.quota_type,
            'limit_value': entity.limit_value,
            'period': entity.period,
            'used_value': entity.used_value,
            'over_limit_action': entity.over_limit_action,
            'status': entity.status,
        }

    def list_by_workspace(self, workspace_id: int) -> list[dict[str, Any]]:
        """列出 workspace 的所有配额（当前 period）。"""
        self._ensure_table()
        try:
            with self._get_session() as session:
                stmt = select(Quota).where(and_(
                    Quota.workspace_id == workspace_id,
                    Quota.status == "active",
                ))
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.opt(exception=True).error("QuotaRepository.list_by_workspace failed: " + str(e).replace("{", "{{").replace("}", "}}"))
            return []

    def update_used(self, workspace_id: int, quota_type: str, period: str, delta: int) -> bool:
        """累加 used_value（原子更新）。"""
        self._ensure_table()
        try:
            with self._get_session() as session:
                stmt = (
                    update(Quota)
                    .where(and_(
                        Quota.workspace_id == workspace_id,
                        Quota.quota_type == quota_type,
                        Quota.period == period,
                    ))
                    .values(used_value=Quota.used_value + delta)
                )
                session.execute(stmt)
                session.commit()
                return True
        except Exception as e:
            logger.opt(exception=True).error("QuotaRepository.update_used failed: " + str(e).replace("{", "{{").replace("}", "}}"))
            return False
