from typing import Dict, List, Optional, Any
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, func
from infrastructure.database.sessions import get_config_session
from infrastructure.database.models.agent import AgentRelation, Agent
from infrastructure.database.repositories.base_repository import BaseRepository
class AgentRelationRepository(BaseRepository[AgentRelation, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = AgentRelation
    def _entity_to_dict(self, entity: AgentRelation, session: Session) -> Dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'agent_pr_key_id': entity.agent_id,
            'relation_id': entity.relation_id,
            'relation_flag': entity.relation_flag or '',
            'create_time': entity.create_time,
            'update_time': entity.update_time,
        }
    _pk_name = 'pr_key_id'
    def get_by_agent(self, agent_pr_key_id: int, relation_flag: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(AgentRelation).where(
                and_(
                    AgentRelation.agent_id == agent_pr_key_id,
                    AgentRelation.del_flag == '0'
                )
            )
            if relation_flag:
                stmt = stmt.where(AgentRelation.relation_flag == relation_flag)
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]
    def get_relation_ids(self, agent_pr_key_id: int, relation_flag: str) -> List[int]:
        with self._get_session() as session:
            stmt = select(AgentRelation.relation_id).where(
                and_(
                    AgentRelation.agent_id == agent_pr_key_id,
                    AgentRelation.relation_flag == relation_flag,
                    AgentRelation.del_flag == '0'
                )
            )
            result = session.execute(stmt)
            return [row[0] for row in result.all() if row[0]]
    def add_relation(self, agent_pr_key_id: int, relation_id: int, relation_flag: str) -> bool:
        try:
            existing = self.get_relation(agent_pr_key_id, relation_id, relation_flag)
            if existing:
                return True
            with self._get_session() as session:
                entity = AgentRelation(
                    agent_id=agent_pr_key_id,
                    relation_id=relation_id,
                    relation_flag=relation_flag,
                    del_flag='0'
                )
                session.add(entity)
                session.commit()
                return True
        except Exception as e:
            logger.error(f"Agent: {str(e)}", exc_info=True)
            return False
    def remove_relation(self, agent_pr_key_id: int, relation_id: Optional[int] = None,
                       relation_flag: Optional[str] = None) -> bool:
        try:
            with self._get_session() as session:
                stmt = select(AgentRelation).where(
                    and_(
                        AgentRelation.agent_id == agent_pr_key_id,
                        AgentRelation.del_flag == '0'
                    )
                )
                if relation_id:
                    stmt = stmt.where(AgentRelation.relation_id == relation_id)
                if relation_flag:
                    stmt = stmt.where(AgentRelation.relation_flag == relation_flag)
                entities = session.scalars(stmt).all()
                for entity in entities:
                    entity.del_flag = '1'
                session.commit()
                return True
        except Exception as e:
            logger.error(f"Agent: {str(e)}", exc_info=True)
            return False
    def update_relations(self, agent_pr_key_id: int, relation_flag: str,
                        relation_ids: List[int]) -> bool:
        try:
            self.remove_relation(agent_pr_key_id, relation_flag=relation_flag)
            with self._get_session() as session:
                for relation_id in relation_ids:
                    entity = AgentRelation(
                        agent_id=agent_pr_key_id,
                        relation_id=relation_id,
                        relation_flag=relation_flag,
                        del_flag='0'
                    )
                    session.add(entity)
                session.commit()
                return True
        except Exception as e:
            logger.error(f"Agent: {str(e)}", exc_info=True)
            return False
    def get_relation(self, agent_pr_key_id: int, relation_id: int,
                     relation_flag: str) -> Optional[AgentRelation]:
        with self._get_session() as session:
            stmt = select(AgentRelation).where(
                and_(
                    AgentRelation.agent_id == agent_pr_key_id,
                    AgentRelation.relation_id == relation_id,
                    AgentRelation.relation_flag == relation_flag,
                    AgentRelation.del_flag == '0'
                )
            )
            return session.scalar(stmt)
    def get_skill_ids(self, agent_pr_key_id: int) -> List[int]:
        return self.get_relation_ids(agent_pr_key_id, AgentRelation.RELATION_SKILL)
    def get_api_ids(self, agent_pr_key_id: int) -> List[int]:
        return self.get_relation_ids(agent_pr_key_id, AgentRelation.RELATION_API)
    def get_knowledge_base_ids(self, agent_pr_key_id: int) -> List[int]:
        return self.get_relation_ids(agent_pr_key_id, AgentRelation.RELATION_KB)
    def get_mcp_ids(self, agent_pr_key_id: int) -> List[int]:
        return self.get_relation_ids(agent_pr_key_id, AgentRelation.RELATION_MCP)

    def count_distinct_related(self, relation_flag: str, workspace_id: Optional[int] = None) -> int:
        """统计指定 relation_flag 的去重 relation_id 数量，可按 Agent 的 workspace 过滤。

        用于统计概览"工具数量"按用户(工作空间)筛选：
        - workspace_id=None：统计全部 Agent（不分空间）绑定的去重关系数
        - workspace_id=X：仅统计该空间 Agent（workspace_id==X 或 is_public==1）绑定的去重关系数

        Args:
            relation_flag: AgentRelation.RELATION_API / RELATION_MCP / RELATION_SKILL / RELATION_KB
            workspace_id: 工作空间 ID；None 表示不按空间过滤（全部空间聚合）
        """
        with self._get_session() as session:
            stmt = (
                select(func.count(func.distinct(AgentRelation.relation_id)))
                .join(Agent, AgentRelation.agent_id == Agent.pr_key_id)
                .where(
                    AgentRelation.del_flag == '0',
                    AgentRelation.relation_flag == relation_flag,
                    Agent.del_flag == '0',
                )
            )
            if workspace_id is not None:
                stmt = stmt.where(
                    (Agent.workspace_id == workspace_id) | (Agent.is_public == 1)
                )
            return session.scalar(stmt) or 0
