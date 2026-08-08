"""Agent CRUD 服务层：创建/更新/删除 Agent 并管理其与 Skills/MCP 的绑定关系。

复用 tb_agent + tb_agent_relation 两张表：
  - tb_agent 存 Agent 基本信息（system_prompt / model_id 等）
  - tb_agent_relation 存多对多关系（relation_flag: 3=MCP 4=SKILL）

注意：不用 AgentRepository.save_agent（其创建新 Agent 时用传入的 pr_key_id 绑定关系，
而新建记录的 pr_key_id 由 DB 自增，导致关系错位）。本服务用 repo.create 先拿到真实
pr_key_id，再通过 AgentRelationRepository.update_relations 绑定关系。
"""
from typing import Dict, List, Any, Optional
from loguru import logger
from infrastructure.database.models.agent import AgentRelation
from infrastructure.database.repositories.agent_repository import AgentRepository
from infrastructure.database.repositories.agent_relation_repository import AgentRelationRepository
from infrastructure.database.repositories.mcp_repository import McpRepository


class AgentCrudService:
    """Agent 配置 + Skills/MCP 绑定的业务服务。"""

    def __init__(self):
        self.agent_repo = AgentRepository()
        self.relation_repo = AgentRelationRepository()
        self.mcp_repo = McpRepository()

    # ─────────────────────── 基础 CRUD ───────────────────────

    def create(
        self,
        agent_name: str,
        system_prompt: str,
        agent_description: str = "",
        model_id: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_timeout: int = 60,
        visible_scope: str = "1",
        release_status: str = "0",
        version_no: str = "1.0.0",
        skills: Optional[List[str]] = None,
        mcps: Optional[List[str]] = None,
        enabled: bool = True,
        is_public: int = 0,
        creator_id: int | None = None,
        workspace_id: int | None = None,
        visibility: str | None = None,
        agent_config: str | None = None,
        is_admin: bool = False,
    ) -> Dict[str, Any]:
        """创建 Agent 并绑定 Skills/MCP（按名称）。

        Args:
            agent_name: Agent 唯一名称
            system_prompt: 系统提示词
            skills: 要绑定的 skill_name 列表（查 tb_skill）
            mcps: 要绑定的 mcp_name 列表（查 tb_mcp）
            visibility: 可见性 private/workspace/public（新 source of truth）；
                        提供时同步 is_public；未提供则由旧 is_public 反推（向后兼容）
        Returns: Agent dict（含 tools/mcp_tools 名称列表）
        """
        from utils.common.visibility import (
            normalize_visibility, visibility_to_is_public, is_public_to_visibility,
        )
        if not agent_name:
            raise ValueError("agent_name 不能为空")
        if self.agent_repo.get_by_name(agent_name):
            raise ValueError(f"Agent 名称已存在: {agent_name}")
        # visibility 与旧 is_public 双向同步：visibility 优先，否则由 is_public 反推
        if visibility is not None:
            visibility = normalize_visibility(visibility)
            is_public = visibility_to_is_public(visibility)
        else:
            visibility = is_public_to_visibility(is_public)
        # 先创建 Agent 拿到 DB 自增的 pr_key_id
        entity = self.agent_repo.create(
            agent_name=agent_name,
            agent_description=agent_description,
            system_prompt=system_prompt,
            model_id=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            response_timeout=response_timeout,
            visible_scope=visible_scope,
            release_status=release_status,
            version_no=version_no,
            status="1" if enabled else "0",
            del_flag="0",
            is_public=is_public,
            visibility=visibility,
            creator_id=creator_id,
            workspace_id=workspace_id,
            agent_config=agent_config,
        )
        if not entity:
            raise RuntimeError("创建 Agent 失败")
        pr_key_id = entity.pr_key_id
        # 用真实 pr_key_id 绑定关系（按可见性过滤，防越权绑定不可见对象）
        self._bind_relations(
            pr_key_id, skills=skills, mcps=mcps,
            viewer_user_id=creator_id, viewer_workspace_id=workspace_id,
            is_admin=is_admin,
        )
        result = self.agent_repo.get_by_id(pr_key_id)
        if not result:
            raise RuntimeError("创建后查询失败")
        logger.info(f"[AgentCrudService] create: {agent_name} -> pr_key_id={pr_key_id}")
        return result

    def get_by_id(self, pr_key_id) -> Optional[Dict[str, Any]]:
        """Agent 详情（含已绑定的 tools/skills/mcp_tools 名称列表）。"""
        return self.agent_repo.get_by_id(pr_key_id)

    def update(self, pr_key_id, **kwargs) -> bool:
        """更新 Agent 基本信息 + 重新绑定关系（仅当传入 skills/mcps 时）。

        传入 skills=None 表示不改绑定；传入 skills=[] 表示清空绑定。
        非 admin 时按可见性过滤可绑定的 skill/mcp（viewer_* 可选参数）。
        """
        existing = self.agent_repo.get_by_id(pr_key_id)
        if not existing:
            return False
        skills = kwargs.pop("skills", None)
        mcps = kwargs.pop("mcps", None)
        viewer_user_id = kwargs.pop("viewer_user_id", None)
        viewer_workspace_id = kwargs.pop("viewer_workspace_id", None)
        is_admin = kwargs.pop("is_admin", False)
        # 三层可见性：visibility 更新时同步 is_public
        if kwargs.get("visibility") is not None:
            from utils.common.visibility import normalize_visibility, visibility_to_is_public
            kwargs["visibility"] = normalize_visibility(kwargs["visibility"])
            kwargs["is_public"] = visibility_to_is_public(kwargs["visibility"])
        # 更新基本信息字段
        update_data: Dict[str, Any] = {}
        for k, v in kwargs.items():
            if v is not None and hasattr(self.agent_repo._model_class, k):
                update_data[k] = v
        if update_data:
            self.agent_repo.update(pr_key_id, **update_data)
        # 重新绑定关系（传了才改，按可见性过滤）
        if skills is not None:
            skill_ids = self._resolve_skill_ids(
                skills, viewer_user_id, viewer_workspace_id, is_admin,
            )
            self.relation_repo.update_relations(
                pr_key_id, AgentRelation.RELATION_SKILL, skill_ids
            )
        if mcps is not None:
            mcp_ids = self._resolve_mcp_ids(
                mcps, viewer_user_id, viewer_workspace_id, is_admin,
            )
            self.relation_repo.update_relations(
                pr_key_id, AgentRelation.RELATION_MCP, mcp_ids
            )
        logger.info(f"[AgentCrudService] update pr_key_id={pr_key_id}")
        return True

    def update_status(self, pr_key_id, status: str) -> bool:
        """启用/禁用。status: '1' 启用 / '0' 禁用。"""
        result = self.agent_repo.update(pr_key_id, status=status)
        return result is not None

    def delete(self, pr_key_id) -> bool:
        """软删 Agent 并清理所有关系（复用 AgentRepository.delete_agent）。"""
        ok = self.agent_repo.delete_agent(pr_key_id)
        logger.info(f"[AgentCrudService] delete pr_key_id={pr_key_id} ok={ok}")
        return ok

    def delete_by_name(self, agent_name: str) -> bool:
        """按名称删除（测试/清理用）。"""
        existing = self.agent_repo.get_by_name(agent_name)
        if existing:
            return self.agent_repo.delete_agent(existing["pr_key_id"])
        return False

    # ─────────────────── 选择器数据 ───────────────────

    def get_selections(
        self,
        viewer_user_id: int | None = None,
        viewer_workspace_id: int | None = None,
        is_admin: bool = False,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """返回前端选择器所需的可选项：内置 tools / skills / mcps。

        非 admin 时按三层可见性过滤（普通用户只看到本空间可见的 skill/mcp）；
        admin 全可见。viewer 参数缺省时回退旧逻辑（不过滤全量）。
        """
        # 内置 tools（全局可用，不绑定关系表）
        tool_list: List[Dict[str, Any]] = []
        try:
            from tools.registry import get_tool_registry
            for t in get_tool_registry().get_all():
                if hasattr(t, "name") and hasattr(t, "invoke"):
                    tool_list.append({
                        "name": getattr(t, "name", ""),
                        "description": getattr(t, "description", "") or "",
                    })
        except Exception as e:
            logger.warning(f"[AgentCrudService] get_selections tools: {e}")
        # skills（数据库，按可见性过滤）
        skills: List[Dict[str, Any]] = []
        try:
            skills = self._get_skill_repo().get_all(
                viewer_user_id=viewer_user_id,
                viewer_workspace_id=viewer_workspace_id,
                is_admin=is_admin,
            ) or []
        except Exception as e:
            logger.warning(f"[AgentCrudService] get_selections skills: {e}")
        # mcps（数据库，按可见性过滤）
        mcps: List[Dict[str, Any]] = self.mcp_repo.get_all(
            viewer_user_id=viewer_user_id,
            viewer_workspace_id=viewer_workspace_id,
            is_admin=is_admin,
        ) or []
        return {"tools": tool_list, "skills": skills, "mcps": mcps}

    # ─────────────────────── 内部辅助 ───────────────────────

    def _bind_relations(
        self, pr_key_id, skills=None, mcps=None,
        viewer_user_id: int | None = None,
        viewer_workspace_id: int | None = None,
        is_admin: bool = False,
    ) -> None:
        """绑定 Skills/MCP 关系（先清旧再建新）。

        非 admin 时按可见性过滤——只能绑定当前用户可见的 skill/mcp
        （防绕过选器传入不可见对象的 pr_key_id）。
        """
        skill_ids = self._resolve_skill_ids(
            skills or [], viewer_user_id, viewer_workspace_id, is_admin,
        )
        self.relation_repo.update_relations(
            pr_key_id, AgentRelation.RELATION_SKILL, skill_ids
        )
        mcp_ids = self._resolve_mcp_ids(
            mcps or [], viewer_user_id, viewer_workspace_id, is_admin,
        )
        self.relation_repo.update_relations(
            pr_key_id, AgentRelation.RELATION_MCP, mcp_ids
        )

    def _resolve_skill_ids(
        self, skill_names: List[str],
        viewer_user_id: int | None = None,
        viewer_workspace_id: int | None = None,
        is_admin: bool = False,
    ) -> List[int]:
        """将 skill_name 列表转为 tb_skill.pr_key_id 列表。

        非 admin 时只解析可见的 skill（不可见的静默跳过 + warning）。
        """
        if not skill_names:
            return []
        try:
            all_skills = self._get_skill_repo().get_all(
                viewer_user_id=viewer_user_id,
                viewer_workspace_id=viewer_workspace_id,
                is_admin=is_admin,
            ) or []
            # 同时支持 skill_name 和 skill_id 匹配（避免传 skill_id 时静默失败）
            name_to_id = {}
            for s in all_skills:
                name_to_id[s.get("skill_name")] = s.get("pr_key_id")
                name_to_id[s.get("skill_id")] = s.get("pr_key_id")
            resolved = [name_to_id[n] for n in skill_names if n in name_to_id]
            skipped = [n for n in skill_names if n not in name_to_id]
            if skipped:
                logger.warning(f"[AgentCrudService] 以下 skill 不存在或不可见，已跳过: {skipped}")
            return resolved
        except Exception as e:
            logger.warning(f"[AgentCrudService] resolve skill ids: {e}")
            return []

    def _resolve_mcp_ids(
        self, mcp_names: List[str],
        viewer_user_id: int | None = None,
        viewer_workspace_id: int | None = None,
        is_admin: bool = False,
    ) -> List[int]:
        """将 mcp_name 列表转为 tb_mcp.pr_key_id 列表。

        非 admin 时只解析可见的 mcp（不可见的静默跳过 + warning）。
        """
        if not mcp_names:
            return []
        all_mcps = self.mcp_repo.get_all(
            viewer_user_id=viewer_user_id,
            viewer_workspace_id=viewer_workspace_id,
            is_admin=is_admin,
        ) or []
        # 同时支持 mcp_name 和 mcp_id 匹配（避免传 mcp_id 时静默失败）
        name_to_id = {}
        for m in all_mcps:
            name_to_id[m.get("mcp_name")] = m.get("pr_key_id")
            name_to_id[m.get("mcp_id")] = m.get("pr_key_id")
        resolved = [name_to_id[n] for n in mcp_names if n in name_to_id]
        skipped = [n for n in mcp_names if n not in name_to_id]
        if skipped:
            logger.warning(f"[AgentCrudService] 以下 mcp 不存在或不可见，已跳过: {skipped}")
        return resolved

    def _get_skill_repo(self):
        """懒加载 SkillRepository（避免 utils 包循环 import）。"""
        from infrastructure.database.repositories.skill_repository import SkillRepository
        return SkillRepository()
