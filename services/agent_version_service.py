"""Agent 版本与发布服务：快照 + publish + rollback + diff。

设计参见 当前文档分析.md §3.6：Agent 版本与发布流程。

核心 API：
- create_snapshot(agent_pr_key_id, version_no, description) → 保存当前 agent 配置为 draft 快照
- publish(agent_pr_key_id, version_no) → draft→published，旧 published 自动 archived，更新 tb_agent.version_no
- rollback(agent_pr_key_id, version_no) → 恢复 agent 配置到指定版本快照
- diff(agent_pr_key_id, v1, v2) → 两版本快照字段级 diff

snapshot 存 agent 可变配置 JSON：agent_name/agent_description/system_prompt/model_id/
temperature/topp/max_tokens/response_timeout。
"""
import json

from loguru import logger

# agent 可变配置字段（版本快照保存这些，rollback 时恢复）
# 含 skills/mcp 绑定、可见性、agent_config，确保回滚不丢字段
_SNAPSHOT_FIELDS = [
    "agent_name", "agent_description", "system_prompt", "model_id",
    "temperature", "topp", "max_tokens", "response_timeout",
    "tools", "mcp_tools", "visibility", "agent_config",
]


class AgentVersionService:
    """Agent 版本与发布服务。"""

    _table_ensured = False

    def _ensure_table(self):
        """确保 tb_agent_version 表存在（幂等 lazy init）。"""
        if AgentVersionService._table_ensured:
            return
        try:
            from infrastructure.database.base import Base
            from infrastructure.database.engines import get_config_engine
            from infrastructure.database.models.agent_version import AgentVersion

            Base.metadata.create_all(
                get_config_engine(),
                tables=[AgentVersion.__table__],
                checkfirst=True,
            )
            AgentVersionService._table_ensured = True
        except Exception as e:
            logger.warning(f"[AgentVersion] _ensure_table failed (non-fatal): {e}")

    def _invalidate_runtime_cache(self) -> None:
        """审批/回滚后失效子代理 registry 缓存，使 agent 间委派读到新已发布版本。"""
        try:
            from core.subagent.registry import get_subagent_registry
            get_subagent_registry().reload()
        except Exception:
            pass

    def _snapshot_agent(self, agent_pr_key_id: int) -> dict | None:
        """从 tb_agent 读取可变配置，返回快照 dict。"""
        try:
            from infrastructure.database.repositories.agent_repository import AgentRepository

            agent = AgentRepository().get_by_id(str(agent_pr_key_id), return_dict=True)
            if not agent:
                return None
            return {f: agent.get(f) for f in _SNAPSHOT_FIELDS}
        except Exception as e:
            logger.error(f"[AgentVersion] _snapshot_agent ({agent_pr_key_id}): {e}", exc_info=True)
            return None

    def create_snapshot(
        self,
        agent_pr_key_id: int,
        version_no: str,
        version_description: str = "",
    ) -> dict | None:
        """保存当前 agent 配置为 draft 快照。

        Args:
            agent_pr_key_id: agent 主键
            version_no: 版本号（如 1.0.1）
            version_description: 版本说明

        Returns:
            快照 dict；agent 不存在返回 None
        """
        self._ensure_table()
        snapshot = self._snapshot_agent(agent_pr_key_id)
        if not snapshot:
            return None
        try:
            from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository
            from utils.id_generator import generate_uuid

            repo = AgentVersionRepository()
            entity = repo.create(
                version_id=f"AGV_{generate_uuid()[:16]}",
                agent_pr_key_id=agent_pr_key_id,
                version_no=version_no,
                version_description=version_description,
                snapshot=json.dumps(snapshot, ensure_ascii=False, default=str),
                status="draft",
            )
            return repo._entity_to_dict(entity, None) if entity else None
        except Exception as e:
            logger.error(f"[AgentVersion] create_snapshot failed: {e}", exc_info=True)
            return None

    def publish(self, agent_pr_key_id: int, version_no: str) -> dict | None:
        """发布版本：draft→published，旧 published→archived，更新 tb_agent.version_no。

        Returns:
            发布后的版本 dict；版本不存在返回 None
        """
        self._ensure_table()
        try:
            from infrastructure.database.repositories.agent_repository import AgentRepository
            from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository

            repo = AgentVersionRepository()
            version = repo.get_by_version(agent_pr_key_id, version_no)
            if not version:
                return None
            # 1. archive 旧 published
            repo.archive_published(agent_pr_key_id)
            # 2. 新版本→published
            repo.update(version["pr_key_id"], status="published")
            # 3. 更新 tb_agent 的 version_no + release_status
            AgentRepository().update(str(agent_pr_key_id), version_no=version_no, release_status="1")
            return repo.get_by_version(agent_pr_key_id, version_no)
        except Exception as e:
            logger.error(f"[AgentVersion] publish failed: {e}", exc_info=True)
            return None

    def rollback(self, agent_pr_key_id: int, version_no: str) -> dict | None:
        """回滚：恢复工作副本到指定版本快照 + 回草稿 + 作废 pending。

        新语义：回滚不再直接生效——只恢复工作副本（含重建 skills/mcps 关系），
        agent 回草稿(0)，作废任何 pending_review 版本；需重新提交审批才上线。
        """
        self._ensure_table()
        try:
            from infrastructure.database.repositories.agent_repository import AgentRepository
            from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository
            from services.agent_crud_service import AgentCrudService

            repo = AgentVersionRepository()
            version = repo.get_by_version(agent_pr_key_id, version_no)
            if not version:
                return None
            snapshot = json.loads(version["snapshot"]) if version["snapshot"] else {}
            if snapshot:
                # 快照字段名 tools/mcp_tools → AgentCrudService 的 skills/mcps
                skills = snapshot.pop("tools", None)
                mcps = snapshot.pop("mcp_tools", None)
                AgentCrudService().update(
                    str(agent_pr_key_id), skills=skills, mcps=mcps, **snapshot
                )
            # 回草稿 + 作废 pending（防止遗留待审批版本）
            AgentRepository().update(str(agent_pr_key_id), release_status="0")
            pending = repo.get_pending(agent_pr_key_id)
            if pending:
                repo.update(pending["pr_key_id"], status="invalidated")
            logger.info(f"[AgentVersion] rollback: agent={agent_pr_key_id} -> {version_no} (reverted to draft)")
            self._invalidate_runtime_cache()
            return version
        except Exception as e:
            logger.error(f"[AgentVersion] rollback failed: {e}", exc_info=True)
            return None

    # ─────────── 审批流方法（审批 = 发布） ───────────

    def create_pending_submission(
        self, agent_pr_key_id: int, version_no: str, version_description: str = "",
    ) -> dict | None:
        """提交审批：冻结当前工作副本为 pending_review 版本。

        快照在此时拍取（含 skills/mcp 绑定、visibility、agent_config）。
        agent 的 release_status 由调用方（submit_for_review 路由）置为 2。
        """
        self._ensure_table()
        snapshot = self._snapshot_agent(agent_pr_key_id)
        if not snapshot:
            return None
        try:
            from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository
            from utils.id_generator import generate_uuid

            repo = AgentVersionRepository()
            entity = repo.create(
                version_id=f"AGV_{generate_uuid()[:16]}",
                agent_pr_key_id=agent_pr_key_id,
                version_no=version_no,
                version_description=version_description,
                snapshot=json.dumps(snapshot, ensure_ascii=False, default=str),
                status="pending_review",
            )
            return repo._entity_to_dict(entity, None) if entity else None
        except Exception as e:
            logger.error(f"[AgentVersion] create_pending_submission failed: {e}", exc_info=True)
            return None

    def publish_pending(self, agent_pr_key_id: int) -> dict | None:
        """审批通过 = 发布：pending_review → published，旧 published → archived，
        更新 tb_agent.version_no + release_status=1 + status=1。

        无 pending_review 版本返回 None。
        """
        self._ensure_table()
        try:
            from infrastructure.database.repositories.agent_repository import AgentRepository
            from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository

            repo = AgentVersionRepository()
            version = repo.get_pending(agent_pr_key_id)
            if not version:
                return None
            repo.archive_published(agent_pr_key_id)
            repo.update(version["pr_key_id"], status="published")
            AgentRepository().update(
                str(agent_pr_key_id),
                version_no=version["version_no"], release_status="1", status="1",
            )
            logger.info(f"[AgentVersion] publish_pending: agent={agent_pr_key_id} -> {version['version_no']}")
            self._invalidate_runtime_cache()
            return repo.get_by_version(agent_pr_key_id, version["version_no"])
        except Exception as e:
            logger.error(f"[AgentVersion] publish_pending failed: {e}", exc_info=True)
            return None

    def reject_pending(self, agent_pr_key_id: int, reason: str = "") -> dict | None:
        """审批拒绝：pending_review → rejected，agent 回草稿(0)。

        无 pending_review 版本返回 None。
        """
        self._ensure_table()
        try:
            from infrastructure.database.repositories.agent_repository import AgentRepository
            from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository

            repo = AgentVersionRepository()
            version = repo.get_pending(agent_pr_key_id)
            if not version:
                return None
            repo.update(version["pr_key_id"], status="rejected")
            AgentRepository().update(str(agent_pr_key_id), release_status="0")
            logger.info(f"[AgentVersion] reject_pending: agent={agent_pr_key_id}, reason={reason}")
            self._invalidate_runtime_cache()
            return repo.get_by_version(agent_pr_key_id, version["version_no"])
        except Exception as e:
            logger.error(f"[AgentVersion] reject_pending failed: {e}", exc_info=True)
            return None

    def next_version_no(self, agent_pr_key_id: int, current_version_no: str | None) -> str:
        """生成下一补丁版本号，与已有版本冲突则继续递增。"""
        self._ensure_table()
        base = current_version_no or "1.0.0"
        parts = base.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            parts = ["1", "0", "0"]
        major, minor, patch = parts
        try:
            from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository
            repo = AgentVersionRepository()
            for _ in range(100):
                patch = str(int(patch) + 1)
                candidate = f"{major}.{minor}.{patch}"
                if not repo.get_by_version(agent_pr_key_id, candidate):
                    return candidate
        except Exception as e:
            logger.warning(f"[AgentVersion] next_version_no check failed, fallback: {e}")
            patch = str(int(patch) + 1)
        return f"{major}.{minor}.{patch}"

    def invalidate_pending(self, agent_pr_key_id: int) -> None:
        """作废 agent 当前 pending_review 版本（编辑待审批 agent 时调用）。"""
        self._ensure_table()
        try:
            from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository
            repo = AgentVersionRepository()
            pending = repo.get_pending(agent_pr_key_id)
            if pending:
                repo.update(pending["pr_key_id"], status="invalidated")
                logger.info(f"[AgentVersion] invalidated pending: agent={agent_pr_key_id}")
        except Exception as e:
            logger.warning(f"[AgentVersion] invalidate_pending failed: {e}")

    def diff(self, agent_pr_key_id: int, version_no_1: str, version_no_2: str) -> dict | None:
        """两版本快照字段级 diff。

        Returns:
            {field: {v1, v2, changed: bool}}；任一版本不存在返回 None
        """
        self._ensure_table()
        try:
            from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository

            repo = AgentVersionRepository()
            v1 = repo.get_by_version(agent_pr_key_id, version_no_1)
            v2 = repo.get_by_version(agent_pr_key_id, version_no_2)
            if not v1 or not v2:
                return None
            s1 = json.loads(v1["snapshot"]) if v1["snapshot"] else {}
            s2 = json.loads(v2["snapshot"]) if v2["snapshot"] else {}
            fields = set(s1.keys()) | set(s2.keys())
            result = {}
            for f in fields:
                val1 = s1.get(f)
                val2 = s2.get(f)
                # 字符串化对比避免类型差异（Numeric vs str）
                changed = str(val1) != str(val2)
                result[f] = {"v1": val1, "v2": val2, "changed": changed}
            return result
        except Exception as e:
            logger.error(f"[AgentVersion] diff failed: {e}", exc_info=True)
            return None
