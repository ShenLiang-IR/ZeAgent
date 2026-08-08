# rag/rag_system/kb_router.py
# KB 语义路由（KBRouter）— query 与 KB 画像 embedding 余弦相似度选库
"""KB 语义路由。

背景：Agent 选库原先靠 LLM 读工具描述中的 description 猜测，KB 多时易选错。
本路由将 KB 画像（名称+描述+文档名）embedding 化，与 query 算余弦相似度，
自动选出最匹配的 KB（供 knowledge_name="auto" / 未命中回退使用）。

对外契约：
- KBRouter(embedder)：注入 embedding 模型（embed_documents/embed_query，
  经 embed_utils fallback 链兼容多种 embedder）
- load(kbs)：装载 KB 列表（knowledge_name/description/_documents），重置缓存
- route(query, top_k=1) -> [(kb_name, similarity)] 按相似度降序；无 KB → []
- profile embedding 按画像指纹缓存：画像不变不重算，load 新数据后重算
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

# 画像最多纳入的文档名数量（防文档数巨大时 profile 过长拖慢 embedding）
_MAX_PROFILE_DOCS = 20


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """余弦相似度（纯 Python 实现；维度不一致取短维，零向量返回 0）。"""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    dot = sum(a[i] * b[i] for i in range(n))
    na = sum(x * x for x in a[:n]) ** 0.5
    nb = sum(x * x for x in b[:n]) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class KBRouter:
    """KB 语义路由器：query → 最匹配的 KB。"""

    def __init__(self, embedder: Any):
        """
        Args:
            embedder: embedding 模型（embed_documents/embed_query，兼容链见 embed_utils）
        """
        self._embedder = embedder
        self._profiles: List[Tuple[str, str]] = []  # [(kb_name, profile_text)]
        self._profile_embs: Optional[List[List[float]]] = None
        self._fingerprint: Optional[tuple] = None

    def load(self, kbs: List[Dict[str, Any]]) -> None:
        """装载 KB 列表并构建画像，重置 embedding 缓存。

        Args:
            kbs: KB dict 列表（knowledge_name/description/_documents，
                 与 KnowledgeBaseRepository.get_unstructured 返回结构一致）
        """
        profiles: List[Tuple[str, str]] = []
        for kb in kbs or []:
            name = (kb or {}).get("knowledge_name") or ""
            if not name:
                continue
            parts = [name]
            desc = kb.get("description") or ""
            if desc:
                parts.append(desc)
            for doc in (kb.get("_documents") or [])[:_MAX_PROFILE_DOCS]:
                doc_name = (doc or {}).get("document_name") or ""
                if doc_name:
                    parts.append(doc_name)
            profiles.append((name, " ".join(parts)))
        self._profiles = profiles
        self._profile_embs = None
        self._fingerprint = None
        logger.info(f"[KBRouter] loaded {len(profiles)} KB profiles")

    def route(self, query: str, top_k: int = 1) -> List[Tuple[str, float]]:
        """按相似度路由。返回 [(kb_name, similarity)] 按相似度降序。

        Args:
            query: 用户查询文本
            top_k: 返回前 k 条（<1 时返回全部）
        Returns:
            排序结果；无 KB 时返回空列表
        """
        if not self._profiles:
            return []
        fingerprint = tuple(self._profiles)
        if self._fingerprint != fingerprint or self._profile_embs is None:
            from rag.rag_system.embed_utils import embed_batch
            self._profile_embs = embed_batch(self._embedder, [p for _, p in self._profiles])
            self._fingerprint = fingerprint
        from rag.rag_system.embed_utils import embed_list
        q_emb = embed_list(self._embedder, [query])[0]
        scored = [
            (name, cosine_similarity(q_emb, emb))
            for (name, _), emb in zip(self._profiles, self._profile_embs)
        ]
        scored.sort(key=lambda x: -x[1])
        if top_k and top_k >= 1:
            return scored[:top_k]
        return scored
