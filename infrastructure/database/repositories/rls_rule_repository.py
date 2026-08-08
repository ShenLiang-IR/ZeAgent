from typing import Dict, List, Optional, Any
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, delete as sa_delete
from infrastructure.database.sessions import get_config_session
from infrastructure.database.models.rls import RLSSysRule
from infrastructure.database.repositories.base_repository import BaseRepository
class RLSRuleRepository(BaseRepository[RLSSysRule, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = RLSSysRule
    def _entity_to_dict(self, entity: RLSSysRule, session: Session) -> Dict[str, Any]:
        return {
            "id": entity.id,
            "rule_id": entity.rule_id,
            "table_name": entity.table_name,
            "column_name": entity.column_name,
            "operator": entity.operator,
            "value_source": entity.value_source,
            "value_key": entity.value_key,
            "fixed_value": entity.fixed_value,
            "priority": entity.priority,
            "enabled": entity.enabled,
            "kb_id": entity.kb_id,
            "description": entity.description,
            "created_at": entity.create_time.isoformat() if entity.create_time else None,
            "updated_at": entity.update_time.isoformat() if entity.update_time else None,
        }
    def _get_primary_key_name(self) -> str:
        return "rule_id"
    def get_by_id(self, rule_id: str, return_dict: bool = True) -> Optional[RLSSysRule | Dict[str, Any]]:
        return super().get_by_id(rule_id, return_dict=return_dict)
    def get_all(
        self,
        kb_id: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(RLSSysRule)
            conditions = []
            if kb_id is not None:
                conditions.append(
                    (RLSSysRule.kb_id.is_(None)) | (RLSSysRule.kb_id == kb_id)
                )
            if enabled is not None:
                conditions.append(RLSSysRule.enabled == (1 if enabled else 0))
            if conditions:
                stmt = stmt.where(and_(*conditions))
            stmt = stmt.order_by(RLSSysRule.priority.asc(), RLSSysRule.id.asc())
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]
    def save(
        self,
        rule_id: str,
        table_name: str,
        operator: str = "=",
        value_source: str = "user",
        description: str = "",
        column_name: Optional[str] = None,
        value_key: Optional[str] = None,
        fixed_value: Optional[str] = None,
        priority: int = 100,
        enabled: bool = True,
        kb_id: Optional[str] = None,
    ) -> bool:
        try:
            data = {
                "rule_id": rule_id,
                "table_name": table_name,
                "column_name": column_name,
                "operator": operator,
                "value_source": value_source,
                "value_key": value_key,
                "fixed_value": fixed_value,
                "priority": priority,
                "enabled": 1 if enabled else 0,
                "kb_id": kb_id,
                "description": description,
            }
            entity = self.upsert(rule_id, **data)
            return entity is not None
        except Exception:
            logger.error(f" RLS : {rule_id}", exc_info=True)
            return False
    def delete(self, rule_id: str) -> bool:
        try:
            with self._get_session() as session:
                stmt = sa_delete(RLSSysRule).where(RLSSysRule.rule_id == rule_id)
                result = session.execute(stmt)
                session.commit()
                success = result.rowcount > 0
                if success:
                    logger.info(f"[RLSRuleRepository] : {rule_id}")
                return success
        except Exception as e:
            logger.error(f"[RLSRuleRepository]  ({rule_id}): {e}", exc_info=True)
            return False
    def batch_delete(self, rule_ids: List[str]) -> int:
        try:
            with self._get_session() as session:
                stmt = sa_delete(RLSSysRule).where(RLSSysRule.rule_id.in_(rule_ids))
                result = session.execute(stmt)
                session.commit()
                logger.info(f"[RLSRuleRepository]  {result.rowcount} ")
                return result.rowcount
        except Exception as e:
            logger.error(f"[RLSRuleRepository] : {e}", exc_info=True)
            return 0
    def toggle_enabled(self, rule_id: str, enabled: bool) -> bool:
        return self.update(rule_id, enabled=1 if enabled else 0)
    def exists(self, rule_id: str) -> bool:
        return self.get_by_id(rule_id) is not None