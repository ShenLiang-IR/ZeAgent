# RAG 模块增强设计 — 5 项功能（分块/Embedding/混合检索/Rerank）

> 日期：2026-07-16
> 前置：RAG MVP 已完成（rag/rag_system/rag_system.py，7 GREEN + 33 回归）
> 决策（基于推荐）：ollama embedding / 复用 hybrid_search BM25+RRF / BGE-reranker

---

## 1. 需求（用户明确 5 项）

1. ChromaDB 隔离（data/chroma_rag）—— ✅ 已完成
2. 智能分块（文档类型 + 参数 config）
3. Embedding 双模式（本地 + 外部）
4. 混合检索（语义+关键词+比例 config）
5. Rerank 排序

## 2. 目标

- 增强 chunker：按文档类型调整 chunk_size/overlap + config 参数
- Embedding 支持 ollama（本地）+ openai（外部）+ huggingface（本地）
- 混合检索：BM25（jieba）+ 向量 RRF 融合 + ratio config
- Rerank：cross-encoder（BGE-reranker-base）
- 所有参数到 config rag.* 段

## 3. 非目标

- Phase 2/3（Agentic RAG / Qdrant / RAGAS / Query Rewriting / DB 知识库）——用户明确"后续"

---

## 4. 组件设计

### 4.1 chunker.py 增强（文档类型适配 + config）

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

DEFAULT_BY_TYPE = {"pdf": (1000, 200), "txt": (500, 100), "md": (512, 51)}

def create_chunker(chunk_size: int = 500, chunk_overlap: int = 100,
                   doc_type: str = None, by_doc_type: dict = None):
    if doc_type and by_doc_type:
        cfg = by_doc_type.get(doc_type)
        if cfg:
            chunk_size, chunk_overlap = cfg
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )
```

config `rag.chunk.*`:
```json
"chunk": {
    "size": 500,
    "overlap": 100,
    "by_doc_type": {"pdf": [1000, 200], "txt": [500, 100], "md": [512, 51]},
    "_comment": "分块参数。by_doc_type 按文档类型覆盖 size/overlap"
}
```

### 4.2 embedding 双模式

`memory/embedding_factory.py` 已支持 openai/huggingface。**加 ollama**：

```python
# embedding_factory.py create_embedding_model 加：
provider = get_config("embedding.provider", "openai")
if provider == "ollama":
    from langchain_ollama import OllamaEmbeddings
    return OllamaEmbeddings(
        model=get_config("embedding.model", "bge-large"),
        base_url=get_config("embedding.base_url", "http://127.0.0.1:11434"),
    )
```

config `embedding.provider`: `"openai"` | `"ollama"` | `"huggingface"`

### 4.3 hybrid_retriever.py（新 — BM25 + 向量 RRF）

```python
# rag/rag_system/hybrid_retriever.py
import jieba
from collections import defaultdict

class HybridRetriever:
    """BM25 + 向量 RRF 融合检索。"""

    def __init__(self, vector_store, embedder, ratio: float = 0.7):
        self._vs = vector_store
        self._embedder = embedder
        self._ratio = ratio  # 语义占比

    def retrieve(self, query: str, top_k: int = 5, kb_id: str = None,
                 collection=None) -> list:
        # 1. 向量检索（top_k * 2）
        q_emb = self._embed([query])[0]
        vec_results = collection.query(query_embeddings=[q_emb], n_results=top_k * 2)
        vec_docs = vec_results.get("documents", [[]])[0]
        vec_metas = vec_results.get("metadatas", [[]])[0]

        # 2. BM25 检索（所有 documents）
        all_docs = collection.get()
        bm25_results = self._bm25_search(query, all_docs, top_k * 2)

        # 3. RRF 融合
        fused = self._rrf_fuse(vec_docs, vec_metas, bm25_results, top_k)
        return fused[:top_k]

    def _bm25_search(self, query, all_data, top_k):
        if not all_data.get("documents"):
            return []
        docs = all_data["documents"]
        metas = all_data.get("metadatas", [{}] * len(docs))
        query_tokens = list(jieba.cut(query))
        scores = []
        for i, doc in enumerate(docs):
            doc_tokens = list(jieba.cut(doc))
            score = self._bm25_score(query_tokens, doc_tokens)
            scores.append((score, i, doc, metas[i] if i < len(metas) else {}))
        scores.sort(reverse=True, key=lambda x: x[0])
        return [(s[2], s[3]) for s in scores[:top_k]]

    def _bm25_score(self, query_tokens, doc_tokens, k1=1.5, b=0.75):
        if not doc_tokens:
            return 0
        from collections import Counter
        doc_freq = Counter(doc_tokens)
        dl = len(doc_tokens)
        avgdl = dl  # 简化
        score = 0
        for qt in query_tokens:
            if qt in doc_freq:
                tf = doc_freq[qt]
                idf = 1  # 简化
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
        return score

    def _rrf_fuse(self, vec_docs, vec_metas, bm25_results, top_k, k=60):
        scores = defaultdict(float)
        meta_map = {}
        for rank, (doc, meta) in enumerate(vec_docs and list(zip(vec_docs, vec_metas)) or []):
            scores[doc] += self._ratio * (1 / (k + rank))
            meta_map[doc] = meta
        for rank, (doc, meta) in enumerate(bm25_results):
            scores[doc] += (1 - self._ratio) * (1 / (k + rank))
            if doc not in meta_map:
                meta_map[doc] = meta
        sorted_docs = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
        return [{"content": doc, "doc_name": meta_map.get(doc, {}).get("doc_name", "unknown"),
                 "node_title": meta_map.get(doc, {}).get("node_title", ""), "score": score}
                for doc, score in sorted_docs]

    def _embed(self, texts):
        if hasattr(self._embedder, "embed_query"):
            return [self._embedder.embed_query(t) for t in texts]
        return self._embedder.encode(texts).tolist()
```

config `rag.hybrid.*`:
```json
"hybrid": {
    "enabled": true,
    "ratio": 0.7,
    "_comment": "混合检索。ratio=语义占比(0-1)，0=纯BM25，1=纯向量"
}
```

### 4.4 reranker.py（新 — cross-encoder）

```python
# rag/rag_system/reranker.py
from loguru import logger

class Reranker:
    """Cross-encoder rerank。"""

    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        self._model = None
        self._model_name = model_name

    def _ensure_model(self):
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(self._model_name)
            except ImportError:
                logger.warning("[Reranker] sentence-transformers 未装，跳过 rerank")
                self._model = False  # 标记不可用

    def rerank(self, query: str, chunks: list, top_k: int = 5) -> list:
        self._ensure_model()
        if not self._model:
            return chunks[:top_k]  # 降级：返回原序
        pairs = [(query, c["content"]) for c in chunks]
        scores = self._model.predict(pairs)
        ranked = sorted(zip(chunks, scores), key=lambda x: -x[1])
        return [c for c, s in ranked[:top_k]]
```

config `rag.rerank.*`:
```json
"rerank": {
    "enabled": true,
    "model": "BAAI/bge-reranker-base",
    "_comment": "Cross-encoder rerank。model=BGE-reranker（中文好）"
}
```

### 4.5 rag_system.py retrieve 增强

```python
def retrieve(self, *, query, strategy, top_k, kb_id) -> RetrieveResult:
    start = time.time()
    col = self._get_collection(kb_id)

    if self._hybrid_enabled:
        results = self._hybrid.retrieve(query, top_k, kb_id, col)
    else:
        q_emb = self._embed([query])[0]
        raw = col.query(query_embeddings=[q_emb], n_results=top_k)
        results = self._format_raw(raw)

    if self._reranker:
        results = self._reranker.rerank(query, results, top_k)

    chunks = [Chunk(doc_name=r["doc_name"], node_title=r["node_title"], content=r["content"])
              for r in results[:top_k]]
    latency_ms = (time.time() - start) * 1000
    return RetrieveResult(query=query, strategy=strategy, latency_ms=latency_ms, chunks=chunks)
```

### 4.6 config rag.* 完整段

```json
"rag": {
    "persist_directory": "data/chroma_rag",
    "chunk": {
        "size": 500,
        "overlap": 100,
        "by_doc_type": {"pdf": [1000, 200], "txt": [500, 100], "md": [512, 51]}
    },
    "hybrid": {
        "enabled": true,
        "ratio": 0.7
    },
    "rerank": {
        "enabled": true,
        "model": "BAAI/bge-reranker-base"
    }
}
```

---

## 5. 测试

| 测试 | 验证 |
|---|---|
| chunker 按文档类型 | pdf → chunk_size=1000, txt → 500 |
| hybrid_retriever BM25 | BM25 检索返回相关结果 |
| hybrid_retriever RRF | 向量+BM25 融合后排序 |
| reranker | rerank 后顺序变化（或降级返回原序） |
| retrieve hybrid+rerank | 集成：retrieve → hybrid → rerank → RetrieveResult |

## 6. 文件变更

| 文件 | 变更 |
|---|---|
| `rag/rag_system/chunker.py` | 改（文档类型适配） |
| `rag/rag_system/hybrid_retriever.py` | 新（BM25+RRF） |
| `rag/rag_system/reranker.py` | 新（cross-encoder） |
| `rag/rag_system/rag_system.py` | 改（retrieve 加 hybrid+rerank） |
| `config/agent_config.json` | 改（rag.chunk/hybrid/rerank） |
| `memory/embedding_factory.py` | 改（加 ollama provider） |
| `test/test_rag_system.py` | 改（加增强测试） |
