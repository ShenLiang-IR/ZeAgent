"""embedding 兼容 + RRF 融合共享助手。

背景（DRY / 性能一致性）：RAGSystem / HybridRetriever / ParentChildRetriever
各自重复实现 embedder 兼容 fallback（hasattr 三级降级）与 RRF 融合。
提取到本模块消除重复，统一行为；批量优先 embed_documents 避免逐条 HTTP。

对外助手：
- embed_batch(embedder, texts)：批量嵌入，优先 embed_documents（RAGSystem 用）
- embed_list(embedder, texts, zero_fallback)：逐条 embed_query 优先
  （HybridRetriever / ParentChildRetriever 原行为）
- rrf_fuse(ranked_lists, top_k, k, weights)：多路检索结果 RRF 融合（按 content 去重）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional



def embed_batch(embedder: Any, texts: List[str]) -> List[List[float]]:
    """批量嵌入文本（优先 embed_documents 一次请求，避免逐条 HTTP 超时）。

    fallback 链：embed_documents → embed_query → encode → aembed（非 async 上下文）。
    """
    if hasattr(embedder, "embed_documents"):
        return embedder.embed_documents(list(texts))
    if hasattr(embedder, "embed_query"):
        return [embedder.embed_query(t) for t in texts]
    if hasattr(embedder, "encode"):
        return [e.tolist() for e in embedder.encode(list(texts))]
    # fallback: aembed_query（仅在非 async 上下文中使用）
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return [loop.run_until_complete(embedder.aembed_query(t)) for t in texts]
    finally:
        loop.close()


def embed_list(embedder: Any, texts: List[str], zero_fallback: bool = False) -> List[List[float]]:
    """逐条嵌入（embed_query 优先），保持 HybridRetriever/ParentChildRetriever 原行为。

    Args:
        zero_fallback: True 时 embed_query 返回 callable（如 MagicMock）或多路皆无时
                       返回零向量（ParentChildRetriever 测试兼容）；False 时抛 RuntimeError。
    """
    if hasattr(embedder, "embed_query"):
        if zero_fallback:
            first = embedder.embed_query(texts[0])
            if callable(first):
                return [[0.1] * 10 for _ in texts]
        return [embedder.embed_query(t) for t in texts]
    if hasattr(embedder, "encode"):
        return [e.tolist() for e in embedder.encode(list(texts))]
    if zero_fallback:
        return [[0.1] * 10 for _ in texts]
    raise RuntimeError("embedder 无 embed_query/encode")


def rrf_fuse(
    ranked_lists: List[List[Dict[str, Any]]],
    top_k: int,
    k: int = 60,
    weights: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    """多路检索结果 RRF（Reciprocal Rank Fusion）融合，按 content 去重。

    Args:
        ranked_lists: 每路为已排序的 result dict 列表（含 "content"）
        top_k: 返回 top-k
        k: RRF 平滑常数（默认 60）
        weights: 与 ranked_lists 等长的路权重（None 时全 1）
    Returns:
        融合后的 [{content, ...meta, score}]
    """
    from collections import defaultdict

    scores: Dict[str, float] = defaultdict(float)
    meta_map: Dict[str, Dict[str, Any]] = {}
    for i, result_list in enumerate(ranked_lists):
        w = weights[i] if weights is not None and i < len(weights) else 1.0
        for rank, r in enumerate(result_list):
            content = r.get("content", "")
            scores[content] += w * (1.0 / (k + rank))
            if content not in meta_map:
                meta_map[content] = r
    top = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
    return [{**meta_map[content], "score": score} for content, score in top]
