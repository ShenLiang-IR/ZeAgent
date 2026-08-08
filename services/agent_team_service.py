"""Agent 团队 + 邮箱 repository + service。

团队协作：create_team / add_member / list_teams / get_members / dispatch by team
Agent 邮箱：send_message / poll_messages / ack_message

设计参见 docs/specs/2026-07-19-team-collaboration-design.md（G2-G4）。
"""
import json
from typing import Any

from loguru import logger
from sqlalchemy import and_, select

from infrastructure.database.models.agent_team import AgentMailbox, AgentTeam
from infrastructure.database.repositories.base_repository import BaseRepository
from infrastructure.database.sessions import get_config_session


class AgentTeamRepository(BaseRepository[AgentTeam, dict[str, Any]]):
    """Agent 团队 repository。"""
    _session_factory = get_config_session
    _model_class = AgentTeam
    _pk_name = 'pr_key_id'

    def _entity_to_dict(self, entity: AgentTeam, session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'team_id': entity.team_id,
            'name': entity.name,
            'workspace_id': entity.workspace_id,
            'visibility': entity.visibility or '',
            'creator_id': entity.creator_id,
            'description': entity.description,
            'members': entity.members,
            'enabled': entity.enabled,
            'create_time': str(entity.create_time) if entity.create_time else None,
            'update_time': str(entity.update_time) if entity.update_time else None,
        }

    def get_by_team_id(self, team_id: str) -> dict[str, Any] | None:
        """按 team_id 查询。"""
        try:
            with self._get_session() as session:
                stmt = select(AgentTeam).where(AgentTeam.team_id == team_id)
                entity = session.scalar(stmt)
                return self._entity_to_dict(entity, session) if entity else None
        except Exception as e:
            logger.error(f"AgentTeamRepository.get_by_team_id ({team_id}): {e}", exc_info=True)
            return None

    def list_by_workspace(self, workspace_id: int | None = None) -> list[dict[str, Any]]:
        """列出团队（可选 workspace 过滤）。"""
        try:
            with self._get_session() as session:
                stmt = select(AgentTeam).where(AgentTeam.enabled == "1")
                if workspace_id is not None:
                    stmt = stmt.where(AgentTeam.workspace_id == workspace_id)
                stmt = stmt.order_by(AgentTeam.pr_key_id.desc())
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"AgentTeamRepository.list_by_workspace: {e}", exc_info=True)
            return []


class AgentMailboxRepository(BaseRepository[AgentMailbox, dict[str, Any]]):
    """Agent 邮箱 repository。"""
    _session_factory = get_config_session
    _model_class = AgentMailbox
    _pk_name = 'pr_key_id'

    def _entity_to_dict(self, entity: AgentMailbox, session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'message_id': entity.message_id,
            'team_id': entity.team_id,
            'from_agent': entity.from_agent,
            'to_agent': entity.to_agent,
            'content': entity.content,
            'msg_type': entity.msg_type,
            'status': entity.status,
            'workspace_id': entity.workspace_id,
            'create_time': str(entity.create_time) if entity.create_time else None,
        }

    def list_pending_for_agent(self, agent_name: str, limit: int = 50) -> list[dict[str, Any]]:
        """查询某 agent 的待处理消息（pending）。"""
        try:
            with self._get_session() as session:
                stmt = (
                    select(AgentMailbox)
                    .where(and_(
                        AgentMailbox.to_agent == agent_name,
                        AgentMailbox.status == "pending",
                    ))
                    .order_by(AgentMailbox.pr_key_id.asc())
                    .limit(limit)
                )
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"AgentMailboxRepository.list_pending_for_agent ({agent_name}): {e}", exc_info=True)
            return []

    def ack_message(self, message_id: str) -> bool:
        """确认消息（pending→acked）。"""
        try:
            with self._get_session() as session:
                stmt = select(AgentMailbox).where(AgentMailbox.message_id == message_id)
                entity = session.scalar(stmt)
                if not entity:
                    return False
                entity.status = "acked"
                session.commit()
                return True
        except Exception as e:
            logger.error(f"AgentMailboxRepository.ack_message ({message_id}): {e}", exc_info=True)
            return False


class AgentTeamService:
    """Agent 团队 + 邮箱服务。"""

    _table_ensured = False

    def _ensure_table(self):
        """确保 tb_agent_team + tb_agent_mailbox 表存在（幂等）。"""
        if AgentTeamService._table_ensured:
            return
        try:
            from infrastructure.database.base import Base
            from infrastructure.database.engines import get_config_engine
            from infrastructure.database.models.agent_team import AgentMailbox, AgentTeam
            Base.metadata.create_all(
                get_config_engine(),
                tables=[AgentTeam.__table__, AgentMailbox.__table__],
                checkfirst=True,
            )
            AgentTeamService._table_ensured = True
        except Exception as e:
            logger.warning(f"[AgentTeam] _ensure_table failed (non-fatal): {e}")

    # ===== 团队管理 =====

    def create_team(self, name: str, members: list[dict], workspace_id: int | None = None,
                    description: str = "", visibility: str | None = None,
                    creator_id: int | None = None) -> dict | None:
        """创建团队。

        Args:
            name: 团队名称
            members: [{agent_id, role}] 如 [{"agent_id": "7", "role": "researcher"}]
            workspace_id: workspace
            description: 说明
            visibility: 可见性 private/workspace/public（新建默认 private）
            creator_id: 创建者用户 ID
        """
        from utils.common.visibility import normalize_visibility
        self._ensure_table()
        try:
            from utils.id_generator import generate_uuid
            repo = AgentTeamRepository()
            entity = repo.create(
                team_id=f"TEAM_{generate_uuid()[:16]}",
                name=name,
                workspace_id=workspace_id,
                visibility=normalize_visibility(visibility),
                creator_id=creator_id,
                description=description,
                members=json.dumps(members, ensure_ascii=False),
                enabled="1",
            )
            return repo._entity_to_dict(entity, None) if entity else None
        except Exception as e:
            logger.error(f"[AgentTeam] create_team failed: {e}", exc_info=True)
            return None

    def get_team(self, team_id: str) -> dict | None:
        """查询团队。"""
        self._ensure_table()
        return AgentTeamRepository().get_by_team_id(team_id)

    def list_teams(self, workspace_id: int | None = None) -> list[dict]:
        """列出团队。"""
        self._ensure_table()
        return AgentTeamRepository().list_by_workspace(workspace_id)

    def add_member(self, team_id: str, agent_id: str, role: str = "member") -> dict | None:
        """向团队添加成员。"""
        self._ensure_table()
        try:
            repo = AgentTeamRepository()
            team = repo.get_by_team_id(team_id)
            if not team:
                return None
            members = json.loads(team["members"]) if team["members"] else []
            # 去重（同 agent_id 不重复加）
            if not any(m.get("agent_id") == agent_id for m in members):
                members.append({"agent_id": agent_id, "role": role})
            entity = repo.update(team["pr_key_id"], members=json.dumps(members, ensure_ascii=False))
            return repo._entity_to_dict(entity, None) if entity else None
        except Exception as e:
            logger.error(f"[AgentTeam] add_member failed: {e}", exc_info=True)
            return None

    def get_member_agent_ids(self, team_id: str) -> list[str]:
        """取团队成员的 agent_id 列表（dispatch by team 用）。"""
        self._ensure_table()
        team = AgentTeamRepository().get_by_team_id(team_id)
        if not team or not team["members"]:
            return []
        try:
            members = json.loads(team["members"])
            return [m["agent_id"] for m in members if m.get("agent_id")]
        except Exception:
            return []

    # ===== Agent 邮箱 =====

    def send_message(self, from_agent: str, to_agent: str, content: str,
                     team_id: str | None = None, msg_type: str = "text",
                     workspace_id: int | None = None) -> dict | None:
        """Agent 向另一个 Agent 发消息。"""
        self._ensure_table()
        try:
            from utils.id_generator import generate_uuid
            repo = AgentMailboxRepository()
            entity = repo.create(
                message_id=f"MSG_{generate_uuid()[:16]}",
                team_id=team_id,
                from_agent=from_agent,
                to_agent=to_agent,
                content=content,
                msg_type=msg_type,
                status="pending",
                workspace_id=workspace_id,
            )
            return repo._entity_to_dict(entity, None) if entity else None
        except Exception as e:
            logger.error(f"[AgentMailbox] send_message failed: {e}", exc_info=True)
            return None

    def poll_messages(self, agent_name: str, limit: int = 50) -> list[dict]:
        """Agent 拉取自己的待处理消息。"""
        self._ensure_table()
        return AgentMailboxRepository().list_pending_for_agent(agent_name, limit)

    def ack_message(self, message_id: str) -> bool:
        """确认消息（pending→acked）。"""
        self._ensure_table()
        return AgentMailboxRepository().ack_message(message_id)
