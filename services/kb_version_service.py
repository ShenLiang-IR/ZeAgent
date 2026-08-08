"""知识库版本与增量索引 service。

设计参见 当前文档分析.md §3.10：知识库版本控制 + 增量索引。

核心 API：
- create_snapshot(kb_id, version_no, description) → 保存 draft 快照
- publish(kb_id, version_no) → draft→published，旧 published→archived
- rollback(kb_id, version_no) → 恢复知识库配置到快照
- diff(kb_id, v1, v2) → 两版本配置 diff
- rebuild_index(kb_id) → 增量索引重建（调 RAG ingest）

snapshot 存 KnowledgeBase 可变配置 JSON。
rebuild_index 调 RAG 系统重新 ingest 所有文档（文件变更后重建向量索引）。
"""
import json

from loguru import logger

# KnowledgeBase 可变配置字段（版本快照保存这些，rollback 时恢复）
_SNAPSHOT_FIELDS = [
    "knowledge_name", "knowledge_type", "description", "business_type",
    "visible_scope", "embedding_model", "chunk_size", "overlap_size", "segment_strategy",
]


class KnowledgeBaseVersionService:
    """知识库版本与增量索引服务。"""

    _table_ensured = False

    def _ensure_table(self):
        """确保 tb_kb_version 表存在（幂等 lazy init）。"""
        if KnowledgeBaseVersionService._table_ensured:
            return
        try:
            from infrastructure.database.base import Base
            from infrastructure.database.engines import get_config_engine
            from infrastructure.database.models.kb_version import KnowledgeBaseVersion

            Base.metadata.create_all(
                get_config_engine(),
                tables=[KnowledgeBaseVersion.__table__],
                checkfirst=True,
            )
            KnowledgeBaseVersionService._table_ensured = True
        except Exception as e:
            logger.warning(f"[KbVersion] _ensure_table failed (non-fatal): {e}")

    def _snapshot_kb(self, knowledge_base_id: str) -> dict | None:
        """从 tb_knowledge_base 读取可变配置，返回快照 dict。"""
        try:
            from infrastructure.database.repositories.knowledge_repository import KnowledgeBaseRepository

            kb = KnowledgeBaseRepository().get_by_id(knowledge_base_id)
            if not kb:
                return None
            return {f: kb.get(f) for f in _SNAPSHOT_FIELDS}
        except Exception as e:
            logger.error(f"[KbVersion] _snapshot_kb ({knowledge_base_id}): {e}", exc_info=True)
            return None

    def create_snapshot(self, knowledge_base_id: str, version_no: str, version_description: str = "") -> dict | None:
        """保存当前知识库配置为 draft 快照。"""
        self._ensure_table()
        snapshot = self._snapshot_kb(knowledge_base_id)
        if not snapshot:
            return None
        try:
            from infrastructure.database.repositories.kb_version_repository import KnowledgeBaseVersionRepository
            from utils.id_generator import generate_uuid

            repo = KnowledgeBaseVersionRepository()
            entity = repo.create(
                version_id=f"KBV_{generate_uuid()[:16]}",
                knowledge_base_id=knowledge_base_id,
                version_no=version_no,
                version_description=version_description,
                snapshot=json.dumps(snapshot, ensure_ascii=False, default=str),
                status="draft",
            )
            return repo._entity_to_dict(entity, None) if entity else None
        except Exception as e:
            logger.error(f"[KbVersion] create_snapshot failed: {e}", exc_info=True)
            return None

    def publish(self, knowledge_base_id: str, version_no: str) -> dict | None:
        """发布版本：draft→published，旧 published→archived。"""
        self._ensure_table()
        try:
            from infrastructure.database.repositories.kb_version_repository import KnowledgeBaseVersionRepository

            repo = KnowledgeBaseVersionRepository()
            version = repo.get_by_version(knowledge_base_id, version_no)
            if not version:
                return None
            repo.archive_published(knowledge_base_id)
            repo.update(version["pr_key_id"], status="published")
            return repo.get_by_version(knowledge_base_id, version_no)
        except Exception as e:
            logger.error(f"[KbVersion] publish failed: {e}", exc_info=True)
            return None

    def rollback(self, knowledge_base_id: str, version_no: str) -> dict | None:
        """回滚：恢复知识库配置到指定版本快照。"""
        self._ensure_table()
        try:
            from infrastructure.database.repositories.kb_version_repository import KnowledgeBaseVersionRepository
            from infrastructure.database.repositories.knowledge_repository import KnowledgeBaseRepository

            repo = KnowledgeBaseVersionRepository()
            version = repo.get_by_version(knowledge_base_id, version_no)
            if not version:
                return None
            snapshot = json.loads(version["snapshot"]) if version["snapshot"] else {}
            if snapshot:
                KnowledgeBaseRepository().update(knowledge_base_id, **snapshot)
            return version
        except Exception as e:
            logger.error(f"[KbVersion] rollback failed: {e}", exc_info=True)
            return None

    def diff(self, knowledge_base_id: str, version_no_1: str, version_no_2: str) -> dict | None:
        """两版本配置 diff。"""
        self._ensure_table()
        try:
            from infrastructure.database.repositories.kb_version_repository import KnowledgeBaseVersionRepository

            repo = KnowledgeBaseVersionRepository()
            v1 = repo.get_by_version(knowledge_base_id, version_no_1)
            v2 = repo.get_by_version(knowledge_base_id, version_no_2)
            if not v1 or not v2:
                return None
            s1 = json.loads(v1["snapshot"]) if v1["snapshot"] else {}
            s2 = json.loads(v2["snapshot"]) if v2["snapshot"] else {}
            fields = set(s1.keys()) | set(s2.keys())
            result = {}
            for f in fields:
                changed = str(s1.get(f)) != str(s2.get(f))
                result[f] = {"v1": s1.get(f), "v2": s2.get(f), "changed": changed}
            return result
        except Exception as e:
            logger.error(f"[KbVersion] diff failed: {e}", exc_info=True)
            return None

    async def rebuild_index(self, knowledge_base_id: str, doc_dir: str | None = None) -> dict:
        """增量索引重建：重新 ingest 知识库文档到向量库。

        FileWatchTrigger 检测到文件变更后可调此方法重建索引。
        MVP：遍历知识库目录文档，对每个调 RAG ingest。

        Args:
            knowledge_base_id: 知识库 ID
            doc_dir: 文档目录（None 时从知识库配置推断，MVP 需调用方提供）

        Returns:
            {success, ingested_count, error?}
        """
        if not doc_dir:
            return {"success": False, "ingested_count": 0, "error": "doc_dir 未提供（MVP 需调用方指定文档目录）"}
        try:
            from pathlib import Path

            from rag.rag_system.rag_system import RAGSystem

            rag = RAGSystem()
            doc_path = Path(doc_dir)
            if not doc_path.exists():
                return {"success": False, "ingested_count": 0, "error": f"doc_dir 不存在: {doc_dir}"}

            # 遍历目录文档，对每个调 ingest（重建索引）
            extensions = {".md", ".txt", ".pdf", ".html", ".docx"}
            files = [f for f in doc_path.rglob("*") if f.suffix.lower() in extensions]
            ingested = 0
            for f in files:
                try:
                    rag.ingest(str(f), knowledge_base_id, f.name)
                    ingested += 1
                except Exception as e:
                    logger.warning(f"[KbVersion] rebuild ingest {f.name} failed (skip): {e}")
            logger.info(f"[KbVersion] rebuild_index kb={knowledge_base_id}: {ingested}/{len(files)} docs ingested")
            return {"success": True, "ingested_count": ingested, "total": len(files)}
        except Exception as e:
            logger.error(f"[KbVersion] rebuild_index failed: {e}", exc_info=True)
            return {"success": False, "ingested_count": 0, "error": str(e)}
