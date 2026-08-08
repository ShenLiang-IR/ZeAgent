from typing import Dict, List, Optional, Any
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import select, and_
from infrastructure.database.sessions import get_config_session
from infrastructure.database.models.agent import Agent, AgentRelation
from infrastructure.database.models.skill import Skill
from infrastructure.database.models.api import RkApi
from infrastructure.database.models.mcp import Mcp
from infrastructure.database.models.knowledge import KnowledgeBase
from infrastructure.database.repositories.base_repository import BaseRepository
from infrastructure.database.repositories.agent_relation_repository import AgentRelationRepository
class AgentRepository(BaseRepository[Agent, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = Agent
    _pk_name = 'pr_key_id'
    def __init__(self):
        super().__init__()
        self._relation_repo = AgentRelationRepository()
    def _entity_to_dict(self, entity: Agent, session: Session,
                        relations_map: dict[int, dict[str, list[str]]] = None) -> Dict[str, Any]:
        if relations_map is not None:
            agent_relations = relations_map.get(entity.pr_key_id, {})
            skills = agent_relations.get('skill', [])
            interfaces = agent_relations.get('api', [])
            mcps = agent_relations.get('mcp', [])
            knowledge_bases = agent_relations.get('kb', [])
        else:
            skills, interfaces, mcps, knowledge_bases = self._load_relations_single(entity.pr_key_id, session)
        return {
            'pr_key_id': entity.pr_key_id,
            'agent_name': entity.agent_name or '',
            'agent_description': entity.agent_description or '',
            'application_id': entity.application_id or '',
            'model_id': entity.model_id or '',
            'visible_scope': entity.visible_scope or '',
            'system_prompt': entity.system_prompt or '',
            'temperature': float(entity.temperature) if entity.temperature else 0.7,
            'topp': float(entity.topp) if entity.topp else None,
            'max_tokens': entity.max_tokens,
            'response_timeout': entity.response_timeout,
            'release_status': entity.release_status or '',
            'version_no': entity.version_no or '',
            'version_description': entity.version_description or '',
            'status': entity.status or '1',
            'tools': skills,
            'external_tools': interfaces,
            'mcp_tools': mcps,
            'knowledge_bases': knowledge_bases,
            'enabled': entity.status == '1',
            'is_public': entity.is_public if entity.is_public is not None else 0,
            'visibility': entity.visibility or '',
            'creator_id': entity.creator_id,
            'workspace_id': entity.workspace_id,
            'agent_config': entity.agent_config or None,
        }
    def _load_relations_single(self, agent_pr_key_id: int, session: Session) -> tuple:
        skill_ids = self._relation_repo.get_skill_ids(agent_pr_key_id or 0)
        api_ids = self._relation_repo.get_api_ids(agent_pr_key_id or 0)
        mcp_ids = self._relation_repo.get_mcp_ids(agent_pr_key_id or 0)
        kb_ids = self._relation_repo.get_knowledge_base_ids(agent_pr_key_id or 0)
        skills = []
        if skill_ids:
            result = session.execute(
                select(Skill.skill_name).where(
                    and_(Skill.pr_key_id.in_(skill_ids), Skill.del_flag == '0', Skill.enable_status == '1')
                )
            )
            skills = [r[0] for r in result.all() if r[0]]
        interfaces = []
        if api_ids:
            result = session.execute(
                select(RkApi.intfc_name).where(
                    and_(RkApi.pr_key_id.in_(api_ids), RkApi.del_flag == '0', RkApi.intfc_sta_cd == '1')
                )
            )
            interfaces = [r[0] for r in result.all() if r[0]]
        mcps = []
        if mcp_ids:
            result = session.execute(
                select(Mcp.mcp_name).where(
                    and_(Mcp.pr_key_id.in_(mcp_ids), Mcp.del_flag == '0', Mcp.status == '1')
                )
            )
            mcps = [r[0] for r in result.all() if r[0]]
        knowledge_bases = []
        if kb_ids:
            result = session.execute(
                select(KnowledgeBase.knowledge_name).where(
                    and_(KnowledgeBase.pr_key_id.in_(kb_ids), KnowledgeBase.del_flag == '0', KnowledgeBase.status == '1')
                )
            )
            knowledge_bases = [r[0] for r in result.all() if r[0]]
        return skills, interfaces, mcps, knowledge_bases
    def _batch_load_relations(self, agent_ids: list[int], session: Session) -> dict[int, dict[str, list[str]]]:
        if not agent_ids:
            return {}
        result_map = {aid: {'skill': [], 'api': [], 'mcp': [], 'kb': []} for aid in agent_ids}
        rel_stmt = select(
            AgentRelation.agent_id, AgentRelation.relation_id, AgentRelation.relation_flag
        ).where(
            and_(AgentRelation.agent_id.in_(agent_ids), AgentRelation.del_flag == '0')
        )
        rel_rows = session.execute(rel_stmt).all()
        skill_ids = set()
        api_ids = set()
        mcp_ids = set()
        kb_ids = set()
        agent_rel_map: dict[int, dict[str, list[str]]] = {}
        for row in rel_rows:
            aid, rid, flag = row[0], row[1], row[2]
            agent_rel_map.setdefault(aid, {}).setdefault(flag, []).append(rid)
            if flag == AgentRelation.RELATION_SKILL:
                skill_ids.add(rid)
            elif flag == AgentRelation.RELATION_API:
                api_ids.add(rid)
            elif flag == AgentRelation.RELATION_MCP:
                mcp_ids.add(rid)
            elif flag == AgentRelation.RELATION_KB:
                kb_ids.add(rid)
        skill_name_map = {}
        if skill_ids:
            rows = session.execute(
                select(Skill.pr_key_id, Skill.skill_name).where(
                    and_(Skill.pr_key_id.in_(skill_ids), Skill.del_flag == '0', Skill.enable_status == '1')
                )
            ).all()
            skill_name_map = {r[0]: r[1] for r in rows if r[1]}
        api_name_map = {}
        if api_ids:
            rows = session.execute(
                select(RkApi.pr_key_id, RkApi.intfc_name).where(
                    and_(RkApi.pr_key_id.in_(api_ids), RkApi.del_flag == '0', RkApi.intfc_sta_cd == '1')
                )
            ).all()
            api_name_map = {r[0]: r[1] for r in rows if r[1]}
        mcp_name_map = {}
        if mcp_ids:
            rows = session.execute(
                select(Mcp.pr_key_id, Mcp.mcp_name).where(
                    and_(Mcp.pr_key_id.in_(mcp_ids), Mcp.del_flag == '0', Mcp.status == '1')
                )
            ).all()
            mcp_name_map = {r[0]: r[1] for r in rows if r[1]}
        kb_name_map = {}
        if kb_ids:
            rows = session.execute(
                select(KnowledgeBase.pr_key_id, KnowledgeBase.knowledge_name).where(
                    and_(KnowledgeBase.pr_key_id.in_(kb_ids), KnowledgeBase.del_flag == '0', KnowledgeBase.status == '1')
                )
            ).all()
            kb_name_map = {r[0]: r[1] for r in rows if r[1]}
        for aid in agent_ids:
            rels = agent_rel_map.get(aid, {})
            result_map[aid]['skill'] = [skill_name_map.get(rid) for rid in rels.get(AgentRelation.RELATION_SKILL, []) if skill_name_map.get(rid)]
            result_map[aid]['api'] = [api_name_map.get(rid) for rid in rels.get(AgentRelation.RELATION_API, []) if api_name_map.get(rid)]
            result_map[aid]['mcp'] = [mcp_name_map.get(rid) for rid in rels.get(AgentRelation.RELATION_MCP, []) if mcp_name_map.get(rid)]
            result_map[aid]['kb'] = [kb_name_map.get(rid) for rid in rels.get(AgentRelation.RELATION_KB, []) if kb_name_map.get(rid)]
        return result_map
    _pk_name = 'pr_key_id'
    def get_by_id(self, pr_key_id: str, return_dict: bool = True) -> Optional[Agent | Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(Agent).where(
                and_(
                    Agent.pr_key_id == pr_key_id,
                    Agent.del_flag == '0'
                )
            )
            entity = session.scalar(stmt)
            if entity:
                if return_dict:
                    return self._entity_to_dict(entity, session)
                return entity
            return None
    def get_by_name(self, agent_name: str, workspace_id: int | None = None, include_public: bool = True) -> Optional[Dict[str, Any]]:
        """按名称查 Agent。传 workspace_id 时做可见性隔离（同空间 OR public）。

        Args:
            agent_name: Agent 名称
            workspace_id: 传则按可见性过滤（同空间 OR is_public）；None=不过滤（向后兼容，admin/重名检查用）
            include_public: workspace_id 过滤时是否包含 public agent
        """
        from sqlalchemy import or_
        with self._get_session() as session:
            conditions = [Agent.agent_name == agent_name, Agent.del_flag == '0']
            if workspace_id is not None:
                ws_cond = Agent.workspace_id == workspace_id
                if include_public:
                    ws_cond = or_(ws_cond, Agent.is_public == 1)
                conditions.append(ws_cond)
            stmt = select(Agent).where(and_(*conditions))
            result = session.execute(stmt)
            entity = result.scalar_one_or_none()
            if entity:
                return self._entity_to_dict(entity, session)
            return None
    def update(self, pr_key_id: str, **kwargs) -> Optional[Agent]:
        try:
            with self._get_session() as session:
                stmt = select(Agent).where(
                    and_(
                        Agent.pr_key_id == pr_key_id,
                        Agent.del_flag == '0'
                    )
                )
                entity = session.scalar(stmt)
                if not entity:
                    return None
                for key, value in kwargs.items():
                    if hasattr(entity, key):
                        setattr(entity, key, value)
                session.commit()
                session.refresh(entity)
                return entity
        except Exception as e:
            logger.error(f"Agent (pr_key_id={pr_key_id}): {str(e)}", exc_info=True)
            return None
    def _build_visibility_filter(self, viewer_user_id: int = None,
                                 viewer_workspace_id: int = None,
                                 is_admin: bool = False):
        """构建三层可见性过滤条件（委托通用函数）。

        C1 迁移后存量行 visibility 已显式化（无 NULL），故 NULL 回退分支不再触发，
        可安全复用 utils.common.visibility.build_visibility_orm_filter。
        admin 不过滤（全可见）；否则可见 = public | (workspace 且同空间) |
        (private 且创建者) | (NULL 行回退同空间，迁移后实际无此类行)。
        """
        from utils.common.visibility import build_visibility_orm_filter
        return build_visibility_orm_filter(
            Agent, viewer_user_id, viewer_workspace_id, is_admin,
        )

    def get_all(self, enabled_only: bool = False, workspace_id: int = None, creator_id: int = None,
                release_status: str = None, strict_creator: bool = False) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(Agent).where(Agent.del_flag == '0')
            if enabled_only:
                stmt = stmt.where(Agent.status == '1')
            # 多租户空间隔离 + 创建者隔离：用户看自己创建的 + 公开的
            if creator_id is not None:
                if strict_creator:
                    stmt = stmt.where(Agent.creator_id == creator_id)
                else:
                    stmt = stmt.where(
                        (Agent.creator_id == creator_id) | (Agent.is_public == 1)
                    )
            elif workspace_id is not None:
                stmt = stmt.where(
                    (Agent.workspace_id == workspace_id) | (Agent.is_public == 1)
                )
            if release_status is not None:
                stmt = stmt.where(Agent.release_status == release_status)
            stmt = stmt.order_by(Agent.pr_key_id)
            entities = session.scalars(stmt).all()
            agent_ids = [e.pr_key_id for e in entities]
            relations_map = self._batch_load_relations(agent_ids, session)
            result = [self._entity_to_dict(e, session, relations_map=relations_map) for e in entities]
            logger.debug(f"[AgentRepository] get_all: enabled_only={enabled_only}, ws={workspace_id}, {len(result)} agents")
            return result

    def list_agents(
        self,
        workspace_id: int = None,
        creator_id: int = None,
        search: str = "",
        app: str = "",
        enabled: bool | None = None,
        offset: int = 0,
        limit: int = 10,
        viewer_user_id: int = None,
        viewer_workspace_id: int = None,
        is_admin: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 Agent 列表（DB 级过滤 + 分页 + 总数）。

        替代在应用层全量加载后过滤/切片，避免大数据量下的内存压力。

        Args:
            workspace_id: 工作空间隔离（None=不过滤空间，旧逻辑）
            creator_id: 创建者隔离（None=不过滤创建者，旧逻辑）
            search: 模糊搜索 agent_name / agent_description
            app: 按 application_id 筛选
            enabled: 按启用状态筛选（None=不过滤）
            offset: 偏移量
            limit: 每页条数
            viewer_user_id: 三层可见性过滤——当前用户 ID（提供时启用可见性过滤，优先于 workspace_id/creator_id）
            viewer_workspace_id: 三层可见性过滤——当前用户工作空间
            is_admin: 三层可见性过滤——admin 全可见

        Returns:
            (agents_list, total_count)
        """
        from sqlalchemy import func, or_

        with self._get_session() as session:
            # ── 基础过滤 ──
            base_filters = [Agent.del_flag == '0']

            # 三层可见性过滤（优先）；未提供 viewer_user_id 时回退旧 workspace/creator 逻辑
            if viewer_user_id is not None or is_admin:
                vis_filter = self._build_visibility_filter(viewer_user_id, viewer_workspace_id, is_admin)
                if vis_filter is not None:
                    base_filters.append(vis_filter)
            elif creator_id is not None:
                base_filters.append(
                    (Agent.creator_id == creator_id) | (Agent.is_public == 1)
                )
            elif workspace_id is not None:
                base_filters.append(
                    (Agent.workspace_id == workspace_id) | (Agent.is_public == 1)
                )

            if enabled is not None:
                base_filters.append(Agent.status == ('1' if enabled else '0'))

            if app:
                base_filters.append(Agent.application_id == app)

            if search:
                search_pattern = f"%{search}%"
                base_filters.append(
                    or_(
                        Agent.agent_name.ilike(search_pattern),
                        Agent.agent_description.ilike(search_pattern),
                    )
                )

            # ── 总数查询 ──
            count_stmt = select(func.count()).select_from(Agent).where(*base_filters)
            total = session.scalar(count_stmt) or 0

            # ── 分页数据查询 ──
            data_stmt = (
                select(Agent)
                .where(*base_filters)
                .order_by(Agent.pr_key_id.desc())
                .offset(offset)
                .limit(limit)
            )
            entities = session.scalars(data_stmt).all()

            # ── 批加载关系 ──
            agent_ids = [e.pr_key_id for e in entities]
            relations_map = self._batch_load_relations(agent_ids, session)
            agents = [
                self._entity_to_dict(e, session, relations_map=relations_map)
                for e in entities
            ]
            logger.debug(
                f"[AgentRepository] list_agents: ws={workspace_id}, "
                f"search={search!r}, offset={offset}, limit={limit}, "
                f"total={total}, returned={len(agents)}"
            )
            return agents, total
    def save_agent(
        self,
        pr_key_id: str,
        agent_name: str,
        system_prompt: str,
        tools: List[str] = None,
        external_tools: List[str] = None,
        mcp_tools: List[str] = None,
        knowledge_bases: List[str] = None,
        agent_description: str = "",
        model_id: str = None,
        temperature: float = 0.7,
        topp: float = None,
        max_tokens: int = 2000,
        response_timeout: int = 60,
        visible_scope: str = "1",
        release_status: str = "1",
        version_no: str = "1.0.0",
        version_description: str = "",
        enabled: bool = True,
        visibility: str = None,
        creator_id: int = None,
        workspace_id: int = None,
        agent_config: str = None,
    ) -> bool:
        from utils.common.visibility import normalize_visibility, visibility_to_is_public
        try:
            agent_data = {
                'agent_name': agent_name,
                'agent_description': agent_description,
                'system_prompt': system_prompt,
                'model_id': model_id,
                'temperature': temperature,
                'topp': topp,
                'max_tokens': max_tokens,
                'response_timeout': response_timeout,
                'visible_scope': visible_scope,
                'release_status': release_status,
                'version_no': version_no,
                'version_description': version_description,
                'status': '1' if enabled else '0',
                'del_flag': '0'
            }
            # 三层可见性：visibility 为 source of truth，同步 is_public（仅当显式提供 visibility）
            if visibility is not None:
                visibility = normalize_visibility(visibility)
                agent_data['visibility'] = visibility
                agent_data['is_public'] = visibility_to_is_public(visibility)
            if agent_config is not None:
                agent_data['agent_config'] = agent_config
            with self._get_session() as session:
                existing = session.query(Agent).filter(
                    and_(Agent.pr_key_id == pr_key_id, Agent.del_flag == '0')
                ).first()
                if existing:
                    for key, value in agent_data.items():
                        if hasattr(existing, key):
                            setattr(existing, key, value)
                    # workspace_id 可更新；creator_id 不覆盖（保留原创建者）
                    if workspace_id is not None:
                        existing.workspace_id = workspace_id
                    entity = existing
                else:
                    if workspace_id is not None:
                        agent_data['workspace_id'] = workspace_id
                    if creator_id is not None:
                        agent_data['creator_id'] = creator_id
                    entity = Agent(**agent_data)
                    session.add(entity)
                session.flush()
                actual_pr_key_id = entity.pr_key_id
            with self._get_session() as session:
                skill_ids = []
                if tools:
                    for tool_name in tools:
                        skill = session.query(Skill).filter(
                            and_(
                                Skill.skill_name == tool_name,
                                Skill.del_flag == '0'
                            )
                        ).first()
                        if not skill:
                            from utils.id_generator import generate_skill_id
                            skill = Skill(
                                skill_id=generate_skill_id(tool_name),
                                skill_name=tool_name,
                                skill_desc='Agent',
                                enable_status='1',
                                del_flag='0'
                            )
                            session.add(skill)
                            session.flush()
                        skill_ids.append(skill.pr_key_id)
                self._relation_repo.update_relations(actual_pr_key_id, AgentRelation.RELATION_SKILL, skill_ids)
                api_ids = []
                if external_tools:
                    for tool_name in external_tools:
                        api = session.query(RkApi).filter(
                            and_(
                                RkApi.intfc_name == tool_name,
                                RkApi.del_flag == '0'
                            )
                        ).first()
                        if api:
                            api_ids.append(api.pr_key_id)
                self._relation_repo.update_relations(actual_pr_key_id, AgentRelation.RELATION_API, api_ids)
                mcp_ids = []
                if mcp_tools:
                    for mcp_ref in mcp_tools:
                        mcp_name = mcp_ref.split(':')[0]
                        mcp = session.query(Mcp).filter(
                            and_(
                                Mcp.mcp_name == mcp_name,
                                Mcp.del_flag == '0'
                            )
                        ).first()
                        if mcp:
                            mcp_ids.append(mcp.pr_key_id)
                self._relation_repo.update_relations(actual_pr_key_id, AgentRelation.RELATION_MCP, mcp_ids)
                kb_ids = []
                if knowledge_bases:
                    for kb_name in knowledge_bases:
                        kb = session.query(KnowledgeBase).filter(
                            and_(
                                KnowledgeBase.knowledge_name == kb_name,
                                KnowledgeBase.del_flag == '0'
                            )
                        ).first()
                        if kb:
                            kb_ids.append(kb.pr_key_id)
                self._relation_repo.update_relations(actual_pr_key_id, AgentRelation.RELATION_KB, kb_ids)
                session.commit()
            return True
        except Exception as e:
            logger.error(f"Agent: {str(e)}", exc_info=True)
            return False
    def delete_agent(self, pr_key_id: str) -> bool:
        try:
            self._relation_repo.remove_relation(pr_key_id)
            with self._get_session() as session:
                session.query(Agent).filter(Agent.pr_key_id == pr_key_id).update({'del_flag': '1'})
                session.commit()
            return True
        except Exception as e:
            logger.error(f"Agent: {str(e)}", exc_info=True)
            return False