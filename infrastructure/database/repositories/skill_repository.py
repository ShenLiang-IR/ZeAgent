from utils.common.json_utils import parse_json_field
from loguru import logger
import json
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, and_
from infrastructure.database.sessions import get_config_session
from infrastructure.database.models.skill import Skill
from infrastructure.database.repositories.base_repository import BaseRepository
class SkillRepository(BaseRepository[Skill, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = Skill
    def _parse_input_json_param(self, input_json_param: Optional[str]) -> List[Dict[str, Any]]:
        if not input_json_param:
            return []
        try:
            params = parse_json_field(input_json_param)
            result = []
            for p in params:
                result.append({
                    'param_name': p.get('paramName', ''),
                    'param_type': p.get('paramType', 'string'),
                    'param_desc': p.get('paramDesc', ''),
                    'is_require': p.get('isRequire', '0'),
                    'required': p.get('isRequire', '0') == '1'
                })
            return result
        except (json.JSONDecodeError, TypeError):
            return []
    def _parse_config_param(self, config_param: Optional[str]) -> Dict[str, Any]:
        if not config_param:
            return {}
        try:
            return parse_json_field(config_param)
        except (json.JSONDecodeError, TypeError):
            return {}
    def _entity_to_dict(self, entity: Skill, session: Session) -> Dict[str, Any]:
        created_at = getattr(entity, 'create_stamp', None) or getattr(entity, 'create_time', None)
        updated_at = getattr(entity, 'upd_stamp', None) or getattr(entity, 'update_time', None)
        parameters = self._parse_input_json_param(entity.input_json_param)
        config = self._parse_config_param(entity.config_param)
        result = {
            'pr_key_id': entity.pr_key_id,
            'skill_id': entity.skill_id,
            'skill_name': entity.skill_name,
            'skill_desc': entity.skill_desc or '',
            'skill_description': entity.skill_desc or '',
            'skill_type': entity.skill_type or '',
            'category': config.get('category', 'general'),
            'module_path': config.get('module_path', ''),
            'class_name': config.get('class_name', ''),
            'function_name': config.get('function_name', ''),
            'lazy_load': config.get('lazy_load', True),
            'preload_priority': config.get('preload_priority', 0),
            'config_param': entity.config_param or '',
            'input_json_param': entity.input_json_param or '',
            'output_json_param': entity.output_json_param or '',
            'parameters': parameters,
            'parameters_list': parameters,
            'enabled': entity.enable_status == '1',
            'enable_status': entity.enable_status or '1',
            'status': entity.enable_status or '1',
            'created_at': created_at,
            'updated_at': updated_at,
            'workspace_id': entity.workspace_id,
            'is_public': entity.is_public if entity.is_public is not None else 0,
            'visibility': entity.visibility or '',
            'creator_id': entity.creator_id,
        }
        return result
    _pk_name = 'pr_key_id'
    def get_all(self, enabled_only: bool = False, workspace_id: int = None,
                viewer_user_id: int = None, viewer_workspace_id: int = None,
                is_admin: bool = False) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(Skill).where(Skill.del_flag == '0')
            if enabled_only:
                stmt = stmt.where(Skill.enable_status == '1')
            # 三层可见性过滤（优先）；未提供 viewer_user_id 时回退旧 workspace 精确匹配
            if viewer_user_id is not None or is_admin:
                from utils.common.visibility import build_visibility_orm_filter
                vis_filter = build_visibility_orm_filter(
                    Skill, viewer_user_id, viewer_workspace_id, is_admin,
                )
                if vis_filter is not None:
                    stmt = stmt.where(vis_filter)
            elif workspace_id is not None:
                stmt = stmt.where(Skill.workspace_id == workspace_id)
            stmt = stmt.order_by(Skill.pr_key_id)
            entities = session.scalars(stmt).all()
            result = [self._entity_to_dict(e, session) for e in entities]
            logger.debug(f"[Repository] get_all: enabled_only={enabled_only},  {len(result)} ")
            return result
    def get_by_id(self, pr_key_id: str, return_dict: bool = True) -> Optional[Skill | Dict[str, Any]]:
        return super().get_by_id(pr_key_id, return_dict=return_dict)
    def get_by_name(self, skill_name: str) -> Optional[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(Skill).where(
                and_(
                    Skill.skill_name == skill_name,
                    Skill.del_flag == '0'
                )
            )
            result = session.execute(stmt)
            entity = result.scalar_one_or_none()
            if entity:
                return self._entity_to_dict(entity, session)
            return None
    def get_by_skill_id(self, skill_id: str, return_dict: bool = True) -> Optional[Skill | Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(Skill).where(
                and_(
                    Skill.skill_id == skill_id,
                    Skill.del_flag == '0'
                )
            )
            entity = session.scalar(stmt)
            if entity:
                if return_dict:
                    return self._entity_to_dict(entity, session)
                session.expunge(entity)
                return entity
            return None
    def save_skill(
        self,
        pr_key_id: str,
        skill_name: str,
        skill_description: str = "",
        enabled: bool = True,
        workspace_id: int = None,
        visibility: str = None,
        creator_id: int = None,
    ) -> bool:
        from utils.common.visibility import normalize_visibility, visibility_to_is_public
        try:
            skill_data = {
                'skill_name': skill_name,
                'skill_desc': skill_description,
                'enable_status': '1' if enabled else '0',
                'del_flag': '0'
            }
            if workspace_id is not None:
                skill_data['workspace_id'] = workspace_id
            if visibility is not None:
                visibility = normalize_visibility(visibility)
                skill_data['visibility'] = visibility
                skill_data['is_public'] = visibility_to_is_public(visibility)
            if creator_id is not None:
                skill_data['creator_id'] = creator_id
            with self._get_session() as session:
                existing = session.query(Skill).filter(
                    and_(Skill.pr_key_id == pr_key_id, Skill.del_flag == '0')
                ).first()
                if existing:
                    for key, value in skill_data.items():
                        if hasattr(existing, key):
                            setattr(existing, key, value)
                else:
                    entity = Skill(**skill_data)
                    session.add(entity)
                session.commit()
            return True
        except Exception as e:
            logger.error(f"技能仓储操作失败: {e}", exc_info=True)
            return False
    def delete_skill(self, pr_key_id: str) -> bool:
        try:
            with self._get_session() as session:
                session.query(Skill).filter(
                    Skill.pr_key_id == pr_key_id
                ).update({'del_flag': '1'})
                session.commit()
            return True
        except Exception as e:
            logger.error(f"技能仓储操作失败: {e}", exc_info=True)
            return False