# rag/rag_system/kb_integration.py
# 数据库知识库接入 — 从 KnowledgeBaseDocumentRepository 读取文档并 ingest
# 连接 DB 知识库 → RAGSystem.ingest
from loguru import logger
from typing import List, Dict, Any, Optional
from pathlib import Path


class KnowledgeBaseIntegrator:
    """数据库知识库接入 RAGSystem。

    从 DB 读取知识库文档列表（KnowledgeBaseDocumentRepository），
    下载/读取文件，调 RAGSystem.ingest 批量入库。
    """

    def __init__(self, rag_system):
        """
        Args:
            rag_system: RAGSystem 实例（ingest 方法）
        """
        self._rag = rag_system

    def sync_knowledge_base(self, knowledge_base_id: str) -> dict:
        """同步 DB 知识库到 RAG 向量库。

        流程：
        1. KnowledgeBaseRepository.get_by_id → 获取知识库元数据
        2. KnowledgeBaseDocumentRepository.get_by_kb → 获取文档列表
        3. 对每个文档（status=completed）→ 读取文件 → RAGSystem.ingest
        4. 返回统计

        Args:
            knowledge_base_id: 知识库 ID（DB 中的 knowledge_base_id）

        Returns:
            {"kb_id": ..., "total_docs": N, "ingested": N, "skipped": N, "errors": [...]}
        """
        from infrastructure.database.repositories.knowledge_repository import (
            KnowledgeBaseRepository, KnowledgeBaseDocumentRepository
        )

        stats = {
            "kb_id": knowledge_base_id,
            "total_docs": 0,
            "ingested": 0,
            "skipped": 0,
            "errors": [],
        }

        try:
            # 1. 验证知识库存在
            kb_repo = KnowledgeBaseRepository()
            kb = kb_repo.get_by_id(knowledge_base_id)
            if not kb:
                logger.warning(f"[KBIntegrator] 知识库 {knowledge_base_id} 不存在")
                stats["errors"].append(f"知识库 {knowledge_base_id} 不存在")
                return stats

            # 2. 获取文档列表
            doc_repo = KnowledgeBaseDocumentRepository()
            docs = doc_repo.get_by_kb(knowledge_base_id, status='completed')
            stats["total_docs"] = len(docs)
            logger.info(f"[KBIntegrator] kb={knowledge_base_id} → {len(docs)} docs")

            if not docs:
                logger.info(f"[KBIntegrator] kb={knowledge_base_id} 无已完成文档")
                return stats

            # 3. 逐个文档 ingest
            for doc in docs:
                file_path = doc.get("file_path", "")
                doc_name = doc.get("document_name", file_path)
                status = doc.get("status", "")

                if status != "completed":
                    stats["skipped"] += 1
                    logger.debug(f"[KBIntegrator] 跳过 {doc_name}（status={status}）")
                    continue

                if not file_path:
                    stats["skipped"] += 1
                    logger.debug(f"[KBIntegrator] 跳过 {doc_name}（无 file_path）")
                    continue

                # 尝试读取文件
                try:
                    path = Path(file_path)
                    if path.exists():
                        # 直接读本地文件
                        count = self._rag.ingest(str(path), knowledge_base_id)
                        stats["ingested"] += 1
                        logger.info(f"[KBIntegrator] ingest {doc_name} → {count} chunks")
                    else:
                        # file_path 不存在 → 尝试用 document_name 搜索
                        # 或从 DB 的 document_content 字段读取（如果有）
                        logger.warning(f"[KBIntegrator] 文件不存在: {file_path}，尝试 document_name")
                        # fallback: 用 description + document_name 作为内容
                        content = doc.get("description", "") or doc_name
                        if content:
                            # 临时写入 + ingest
                            import tempfile
                            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                                             delete=False, encoding="utf-8") as f:
                                f.write(content)
                                tmp_path = f.name
                            count = self._rag.ingest(tmp_path, knowledge_base_id)
                            stats["ingested"] += 1
                            Path(tmp_path).unlink(missing_ok=True)
                        else:
                            stats["skipped"] += 1
                except Exception as e:
                    stats["errors"].append(f"{doc_name}: {type(e).__name__}: {str(e)[:100]}")
                    logger.error(f"[KBIntegrator] ingest {doc_name} 失败: {e}")

        except Exception as e:
            logger.error(f"[KBIntegrator] 同步知识库失败: {e}", exc_info=True)
            stats["errors"].append(f"同步失败: {type(e).__name__}: {str(e)[:100]}")

        logger.info(f"[KBIntegrator] kb={knowledge_base_id} 完成: "
                    f"total={stats['total_docs']} ingested={stats['ingested']} "
                    f"skipped={stats['skipped']} errors={len(stats['errors'])}")
        return stats

    def list_knowledge_bases(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
        """列出所有非结构化知识库。"""
        try:
            from infrastructure.database.repositories.knowledge_repository import (
                KnowledgeBaseRepository
            )
            kb_repo = KnowledgeBaseRepository()
            return kb_repo.get_unstructured(enabled_only=enabled_only)
        except Exception as e:
            logger.error(f"[KBIntegrator] 列出知识库失败: {e}")
            return []
