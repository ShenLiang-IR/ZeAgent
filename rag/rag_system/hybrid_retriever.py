# rag/rag_system/hybrid_retriever.py
# 混合检索（BM25 + 向量 RRF 融合）
import jieba
from collections import Counter
from typing import List, Dict, Any
from loguru import logger


class HybridRetriever:
    """BM25 + 向量 RRF 融合检索。"""

    def __init__(self, embedder, ratio: float = 0.7):
        """
        Args:
            embedder: embedding 模型（embed_query/encode）
            ratio: 语义占比（0=纯BM25, 1=纯向量, 0.7=默认）
        """
        self._embedder = embedder
        self._ratio = ratio

    def retrieve(self, query: str, top_k: int = 5,
                 collection=None, ratio: float = None) -> List[Dict[str, Any]]:
        """混合检索：向量 + BM25 RRF 融合。

        Args:
            ratio: 请求级语义占比覆盖（None 时用 self._ratio）。不写共享实例
                   的 _ratio，防并发请求互相污染。
        """
        eff_ratio = ratio if ratio is not None else self._ratio
        # 1. 向量检索（top_k * 2）
        q_emb = self._embed([query])[0]
        vec_results = collection.query(query_embeddings=[q_emb], n_results=top_k * 2)
        vec_docs = vec_results.get("documents", [[]])[0]
        vec_metas = vec_results.get("metadatas", [[]])[0]

        # 2. BM25 检索（所有 documents）
        all_data = collection.get()
        bm25_results = self._bm25_search(query, all_data, top_k * 2)

        # 3. RRF 融合
        fused = self._rrf_fuse(vec_docs, vec_metas, bm25_results, top_k, ratio=eff_ratio)
        logger.info(f"[HybridRetriever] query='{query[:30]}' vec={len(vec_docs)} "
                    f"bm25={len(bm25_results)} fused={len(fused)} ratio={eff_ratio}")
        return fused[:top_k]

    def retrieve_bm25_only(self, query: str, collection, top_k: int = 5) -> List[Dict[str, Any]]:
        """纯 BM25 关键词检索（不走向量）。"""
        all_data = collection.get()
        bm25_results = self._bm25_search(query, all_data, top_k)
        logger.info(f"[HybridRetriever] bm25_only query='{query[:30]}' → {len(bm25_results)} results")
        return [
            {"content": doc,
             "doc_name": meta.get("doc_name", "unknown"),
             "node_title": meta.get("node_title", ""),
             **self._locator_from_meta(meta),
             "score": 0}
            for doc, meta in bm25_results
        ]

    @staticmethod
    def _locator_from_meta(meta: Dict[str, Any] | None) -> Dict[str, Any]:
        """从 chroma metadata 提取引用定位（page 用 -1 哨兵表示无页码）。"""
        m = meta or {}
        page = m.get("page")
        return {
            "page": page if page not in (None, -1) else None,
            "char_start": m.get("char_start"),
            "char_end": m.get("char_end"),
        }

    def _bm25_search(self, query: str, all_data: dict, top_k: int) -> List[tuple]:
        """BM25 关键词检索。返回 [(doc, meta), ...]。"""
        docs = all_data.get("documents", [])
        if not docs:
            return []
        metas = all_data.get("metadatas", [{}] * len(docs))
        query_tokens = [t for t in jieba.cut(query) if t.strip()]
        doc_tokens_list = [[t for t in jieba.cut(d) if t.strip()] for d in docs]
        avgdl = sum(len(dt) for dt in doc_tokens_list) / max(len(doc_tokens_list), 1)

        scores = []
        for i, doc_tokens in enumerate(doc_tokens_list):
            score = self._bm25_score(query_tokens, doc_tokens, avgdl)
            scores.append((score, i, docs[i], metas[i] if i < len(metas) else {}))
        scores.sort(reverse=True, key=lambda x: x[0])
        return [(s[2], s[3]) for s in scores[:top_k]]

    def _bm25_score(self, query_tokens, doc_tokens, avgdl, k1=1.5, b=0.75) -> float:
        if not doc_tokens:
            return 0.0
        doc_freq = Counter(doc_tokens)
        dl = len(doc_tokens)
        score = 0.0
        for qt in query_tokens:
            if qt in doc_freq:
                tf = doc_freq[qt]
                idf = 1.0  # 简化 IDF
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / max(avgdl, 1)))
        return score

    def _rrf_fuse(self, vec_docs, vec_metas, bm25_results, top_k, k=60, ratio=None) -> List[Dict]:
        """RRF 融合（委托共享助手 rrf_fuse）。ratio 为请求级覆盖（None 时用 self._ratio）。"""
        from rag.rag_system.embed_utils import rrf_fuse

        eff_ratio = ratio if ratio is not None else self._ratio

        def _meta_of(meta):
            m = meta or {}
            return {
                "doc_name": m.get("doc_name", "unknown"),
                "node_title": m.get("node_title", ""),
                **self._locator_from_meta(m),
            }

        vec_list = [
            {"content": doc, **_meta_of(meta)}
            for doc, meta in (zip(vec_docs, vec_metas) if vec_docs and vec_metas else [])
        ]
        bm25_list = [
            {"content": doc, **_meta_of(meta)}
            for doc, meta in bm25_results
        ]
        return rrf_fuse(
            [vec_list, bm25_list], top_k, k=k,
            weights=[eff_ratio, 1 - eff_ratio],
        )

    def _embed(self, texts: list) -> list:
        """逐条嵌入（委托共享助手 embed_list，零向量回退关闭）。"""
        from rag.rag_system.embed_utils import embed_list
        return embed_list(self._embedder, texts, zero_fallback=False)
