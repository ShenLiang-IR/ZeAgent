from typing import Dict, List, Optional, Any
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import select, and_
from infrastructure.database.sessions import get_config_session
from infrastructure.database.models.mode import Mode
from infrastructure.database.repositories.base_repository import BaseRepository
class ModeRepository(BaseRepository[Mode, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = Mode
    def _entity_to_dict(self, entity: Mode, session: Session) -> Dict[str, Any]:
        created_at = getattr(entity, 'create_stamp', None) or getattr(entity, 'create_time', None)
        updated_at = getattr(entity, 'upd_stamp', None) or getattr(entity, 'update_time', None)
        recommended_agents_str = entity.rem_pers_name or ''
        return {
            'pr_key_id': entity.pr_key_id,
            'dclr_ptn_name': entity.dclr_ptn_name or '',
            'en_name': entity.en_name or '',
            'thval_desc_desc': entity.thval_desc_desc or '',
            'status': entity.status or '1',
            'comprehe_sugg_content': entity.comprehe_sugg_content or '',
            'rem_pers_name': entity.rem_pers_name or '',
            'by_rem_pers_name': entity.by_rem_pers_name or '',
            'deal_num': entity.deal_num or 0,
            'data_use_scene_name': entity.data_use_scene_name or '',
            'apply_lmtms': entity.apply_lmtms or 0,
            'para_eff_scope_cd': entity.para_eff_scope_cd or '',
            'mode_type': entity.mode_type or 'Agent',
            'create_teller_no': entity.create_teller_no or '',
            'create_teller_name': entity.create_teller_name or '',
            'mod_teller_name': entity.mod_teller_name or '',
            'upd_teller_no': entity.upd_teller_no or '',
            'enabled': entity.status == '1',
            'preferred_subagents': self._parse_agent_list(recommended_agents_str),
            'system_prompt_suffix': entity.comprehe_sugg_content or '',
            'mode_name': entity.dclr_ptn_name or '',
            'mode_description': entity.thval_desc_desc or '',
            'system_prompt': entity.comprehe_sugg_content or '',
            'recommended_agents': recommended_agents_str,
            'priority_agent': entity.by_rem_pers_name or '',
        }
    def _parse_agent_list(self, agent_str: Optional[str]) -> List[str]:
        if not agent_str:
            return []
        return [a.strip() for a in agent_str.split(',') if a.strip()]
    _pk_name = 'pr_key_id'
    def get_all(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(Mode).where(Mode.del_flag == '0')
            if enabled_only:
                stmt = stmt.where(Mode.status == '1')
            stmt = stmt.order_by(Mode.pr_key_id)
            entities = session.scalars(stmt).all()
            result = [self._entity_to_dict(e, session) for e in entities]
            logger.debug(f"[Repository] get_all: enabled_only={enabled_only},  {len(result)} ")
            return result
    def get_by_id(self, pr_key_id: str, return_dict: bool = True) -> Optional[Mode | Dict[str, Any]]:
        return super().get_by_id(pr_key_id, return_dict=return_dict)
    def get_by_name(self, mode_name: str) -> Optional[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(Mode).where(
                and_(
                    Mode.dclr_ptn_name == mode_name,
                    Mode.del_flag == '0'
                )
            )
            result = session.execute(stmt)
            entity = result.scalar_one_or_none()
            if not entity:
                stmt = select(Mode).where(
                    and_(
                        Mode.en_name == mode_name,
                        Mode.del_flag == '0'
                    )
                )
                result = session.execute(stmt)
                entity = result.scalar_one_or_none()
            if entity:
                return self._entity_to_dict(entity, session)
            return None
    def save_mode(
        self,
        pr_key_id: str,
        mode_name: str,
        en_name: str = "",
        mode_description: str = "",
        system_prompt: str = "",
        recommended_agents: str = "",
        priority_agent: str = "",
        data_use_scene_name: str = "",
        para_eff_scope_cd: str = "1",
        enabled: bool = True,
        mode_type: str = "Agent"
    ) -> bool:
        try:
            mode_data = {
                'dclr_ptn_name': mode_name,
                'en_name': en_name,
                'thval_desc_desc': mode_description,
                'comprehe_sugg_content': system_prompt,
                'rem_pers_name': recommended_agents,
                'by_rem_pers_name': priority_agent,
                'data_use_scene_name': data_use_scene_name,
                'para_eff_scope_cd': para_eff_scope_cd,
                'status': '1' if enabled else '0',
                'del_flag': '0',
                'mode_type': mode_type
            }
            entity = self.upsert(pr_key_id, **mode_data)
            return entity is not None
        except Exception as e:
            logger.error(f"模式仓储操作失败: {e}", exc_info=True)
            return False
    def delete_mode(self, pr_key_id: str) -> bool:
        if self.is_system_mode(pr_key_id):
            logger.warning(f"系统模式不可删除: {pr_key_id}")
            return False
        try:
            with self._get_session() as session:
                session.query(Mode).filter(
                    Mode.pr_key_id == pr_key_id
                ).update({'del_flag': '1'})
                session.commit()
            return True
        except Exception as e:
            logger.error(f"模式仓储操作失败: {e}", exc_info=True)
            return False
    def get_by_type(self, mode_type: str) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(Mode).where(
                and_(
                    Mode.mode_type == mode_type,
                    Mode.del_flag == '0'
                )
            )
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]
    def get_system_modes(self) -> List[Dict[str, Any]]:
        return self.get_by_type('')
    def is_system_mode(self, pr_key_id: str) -> bool:
        mode = self.get_by_id(pr_key_id)
        if mode:
            return mode.get('mode_type') == ''
        return False