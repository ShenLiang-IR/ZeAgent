# rag/rag_system/reranker.py
# Cross-encoder rerank
from loguru import logger
from typing import List, Dict, Any


class Reranker:
    """Cross-encoder rerank（BGE-reranker）。"""

    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        self._model = None
        self._model_name = model_name
        self._available = None  # None=未检查, True/False

    def _ensure_model(self):
        if self._available is not None:
            return self._available
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self._model_name)
            self._available = True
            logger.info(f"[Reranker] 模型加载: {self._model_name}")
        except ImportError:
            logger.warning("[Reranker] sentence-transformers 未装，跳过 rerank")
            self._available = False
        except Exception as e:
            logger.warning(f"[Reranker] 模型加载失败: {e}，跳过 rerank")
            self._available = False
        return self._available

    def rerank(self, query: str, chunks: List[Dict[str, Any]], top_k: int = 5) -> List[Dict]:
        """对 chunks rerank，返回 top_k。"""
        if not chunks:
            return []
        if not self._ensure_model():
            return chunks[:top_k]  # 降级：返回原序

        pairs = [(query, c.get("content", "")) for c in chunks]
        scores = self._model.predict(pairs)
        ranked = sorted(zip(chunks, scores), key=lambda x: -x[1])
        logger.info(f"[Reranker] rerank {len(chunks)} → {top_k}")
        return [c for c, s in ranked[:top_k]]
