# RAG 模块设计 — 最小 RAG（方案 A，严格对齐接口契约）

> 日期：2026-07-16
> 方案：A（最小 RAG，复用 embedding_factory + ChromaDB 嵌入式，2-Step 检索）
> 前置：explore 确认 RAGSystem 接口契约（unstructured_knowledge_tool.py 反推）+ librarian 互联网 RAG 最新定位
> 触及模块：`rag/`（全新）、`config/agent_config.json`（新增 rag.* 段）、`requirements.txt`（补 chromadb）

---

## 1. 背景

### 1.1 现状

- `rag/` 目录空（git 无 tracked，磁盘空），RAGSystem **无任何实现**
- `unstructured_knowledge_tool.py:41` lazy import `from rag.rag_system.rag_system import RAGSystem`——首次调用 `rag_system.retrieve`（line 134）时触发 ImportError
- 用户明确"RAG 后面重点开发，模块叫 rag"——现在开发

### 1.2 接口契约（explore 从 unstructured_knowledge_tool.py 反推，开发必须严格对齐）

```python
class RAGSystem:
    def __init__(self, config_path: str = None): ...

    def retrieve(self, *, query: str, strategy: str, top_k: int, kb_id: str) -> RetrieveResult: ...
    # 全关键字参数！strategy: "semantic"/"metadata"/"global"

# 返回对象属性契约
result.query           # str
result.strategy        # str
result.latency_ms      # 数值（毫秒）
result.chunks          # 可迭代[Chunk]
    chunk.doc_name     # str
    chunk.node_title    # str
    chunk.content      # str
```

### 1.3 可复用资产（explore 确认）

| 资产 | 位置 | 复用 |
|---|---|---|
| embedding_factory | `memory/embedding_factory.py:9` create_embedding_model | 直接调（读 config embedding 段，dashscope text-embedding-v3） |
| ChromaDB | 已装 1.5.9，`memory/storage.py:204-229` _init_chromadb 模式 | 参考初始化，新建 chunk collection |
| KnowledgeMetadata | `domain/knowledge/entities.py:34` chunk_size(1000)/overlap_size(200) | 分块参数参考 |
| test_vector_storage | `test/test_vector_storage.py` | chromadb 测试模板 |

### 1.4 互联网调研关键（librarian）

- 2-Step RAG 适合 70-85% 生产流量（MVP 默认）
- ChromaDB 适合原型/本地（数据敏感）
- RecursiveCharacterTextSplitter 512 + 10% overlap（普适甜点）
- MVP ~130-200 行

---

## 2. 目标

- 实现 `rag/rag_system/rag_system.py`，**严格对齐接口契约**（`__init__(config_path)` + `retrieve(*, query, strategy, top_k, kb_id)`）
- 复用 embedding_factory + ChromaDB 嵌入式
- 2-Step RAG（检索→返回 chunks），unstructured_knowledge_tool 零改动兼容
- 文档加载（Text/PDF）+ 分块 + embedding + 向量存储 + 检索
- 数据本地化（ChromaDB 嵌入式 `data/chroma_rag`，金融研究数据敏感）

## 3. 非目标

- Agentic RAG（agent 决定检索时机 + query rewriting，后续 Phase 2）
- Cross-encoder Rerank / Hybrid Search（后续 Phase 2）
- Qdrant / pgvector（生产化时切换，MVP 用 ChromaDB）
- 知识库 DB 集成（KnowledgeBaseDocumentRepository，后续扩展）
- RAGAS 评估框架（后续）

---

## 4. 架构

```
文档 → [Loader] → [Chunker 512] → [Embedder] → [ChromaDB collection]
                                                          ↓
Query → [embed query] → [ChromaDB similarity_search] → [RetrieveResult]
```

**复用**：embedding_factory（create_embedding_model）+ ChromaDB 嵌入式（PersistentClient）
**新建**：chunk-oriented collection（不污染 memory 的 chroma）

---

## 5. 组件设计

### 5.1 文件结构

```
rag/
  __init__.py
  rag_system/
    __init__.py
    rag_system.py        # RAGSystem（核心，对齐接口契约）
    models.py            # RetrieveResult / Chunk dataclass
    document_loader.py   # 文档加载（Text/PDF）
    chunker.py           # RecursiveCharacterTextSplitter 512
    vector_store.py      # ChromaDB 嵌入式封装
```

### 5.2 models.py — RetrieveResult / Chunk dataclass

```python
from dataclasses import dataclass, field
from typing import List

@dataclass
class Chunk:
    """检索结果块（对齐接口契约：doc_name/node_title/content）。"""
    doc_name: str
    node_title: str
    content: str

@dataclass
class RetrieveResult:
    """检索结果（对齐接口契约：query/strategy/latency_ms/chunks）。"""
    query: str
    strategy: str
    latency_ms: float
    chunks: List[Chunk] = field(default_factory=list)
```

### 5.3 rag_system.py — RAGSystem（核心）

```python
import time
from typing import Optional
from loguru import logger
from rag.rag_system.models import RetrieveResult, Chunk
from rag.rag_system.chunker import Chunker
from rag.rag_system.vector_store import RAGVectorStore

class RAGSystem:
    """RAG 系统（严格对齐 unstructured_knowledge_tool.py 接口契约）。

    __init__(config_path) + retrieve(*, query, strategy, top_k, kb_id)
    """

    def __init__(self, config_path: str = None):
        """初始化 RAG 系统。

        Args:
            config_path: 配置路径（None 时读 config/agent_config.json 的 rag.* 段）
        """
        from utils.config import get_config
        self._chunker = Chunker(
            chunk_size=get_config("rag.chunk_size", 512),
            chunk_overlap=get_config("rag.chunk_overlap", 51),
        )
        self._vector_store = RAGVectorStore(
            persist_directory=get_config("rag.persist_directory", "data/chroma_rag"),
            collection_name=get_config("rag.collection_name", "knowledge_chunks"),
        )
        # 复用 embedding_factory
        from memory.embedding_factory import create_embedding_model
        self._embedding_model = create_embedding_model(log_tag="RAG")
        logger.info("[RAGSystem] 初始化完成")

    def retrieve(self, *, query: str, strategy: str = "semantic",
                 top_k: int = 5, kb_id: str = None) -> RetrieveResult:
        """检索知识库（对齐接口契约）。

        Args:
            query: 查询文本
            strategy: 检索策略（"semantic" 向量 / "metadata" 元数据过滤 / "global" 全局）
            top_k: 返回 top-k 结果
            kb_id: 知识库 ID（用于 metadata 过滤）

        Returns:
            RetrieveResult（含 query/strategy/latency_ms/chunks）
        """
        start = time.time()
        # embed query
        query_embedding = self._embed_query(query)
        # chromadb similarity search
        where_filter = {"kb_id": kb_id} if kb_id and strategy == "metadata" else None
        results = self._vector_store.search(
            query_embedding=query_embedding,
            n_results=top_k,
            where=where_filter,
        )
        # 构建 chunks
        chunks = [
            Chunk(
                doc_name=r.get("doc_name", "unknown"),
                node_title=r.get("node_title", ""),
                content=r.get("content", ""),
            )
            for r in results
        ]
        latency_ms = (time.time() - start) * 1000
        logger.info(f"[RAGSystem] retrieve: query='{query[:50]}', strategy={strategy}, "
                    f"top_k={top_k}, found={len(chunks)}, latency={latency_ms:.1f}ms")
        return RetrieveResult(
            query=query,
            strategy=strategy,
            latency_ms=latency_ms,
            chunks=chunks,
        )

    def ingest(self, file_path: str, kb_id: str = "default") -> int:
        """加载文档 → 分块 → embedding → 存储。

        Returns:
            存储的 chunk 数
        """
        from rag.rag_system.document_loader import DocumentLoader
        # load
        docs = DocumentLoader.load(file_path)
        # chunk
        chunks = self._chunker.split(docs)
        # embed
        texts = [c["content"] for c in chunks]
        embeddings = self._embed_texts(texts)
        # store
        self._vector_store.add(
            ids=[f"{kb_id}_{i}" for i in range(len(chunks))],
            embeddings=embeddings,
            documents=chunks,  # 含 doc_name/node_title/content
            metadatas=[{"kb_id": kb_id, "doc_name": c["doc_name"]} for c in chunks],
        )
        logger.info(f"[RAGSystem] ingest: {file_path}, {len(chunks)} chunks, kb_id={kb_id}")
        return len(chunks)

    def _embed_query(self, query: str):
        """嵌入查询（兼容 aembed_query/embed_query/encode）。"""
        if hasattr(self._embedding_model, "embed_query"):
            return self._embedding_model.embed_query(query)
        if hasattr(self._embedding_model, "encode"):
            return self._embedding_model.encode(query).tolist()
        raise RuntimeError("embedding model 无 embed_query/encode 方法")

    def _embed_texts(self, texts: list):
        """嵌入文本列表。"""
        if hasattr(self._embedding_model, "embed_documents"):
            return self._embedding_model.embed_documents(texts)
        if hasattr(self._embedding_model, "encode"):
            return [e.tolist() for e in self._embedding_model.encode(texts)]
        raise RuntimeError("embedding model 无 embed_documents/encode 方法")
```

### 5.4 chunker.py — RecursiveCharacterTextSplitter

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

class Chunker:
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 51):
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )

    def split(self, docs: list) -> list:
        """分块文档列表。返回 [{content, doc_name, node_title}, ...]。"""
        chunks = []
        for doc in docs:
            texts = self._splitter.split_text(doc["content"])
            for i, text in enumerate(texts):
                chunks.append({
                    "content": text,
                    "doc_name": doc.get("doc_name", "unknown"),
                    "node_title": f"chunk_{i}",
                })
        return chunks
```

### 5.5 document_loader.py — 文档加载

```python
from pathlib import Path

class DocumentLoader:
    @staticmethod
    def load(file_path: str) -> list:
        """加载文档（Text/PDF/Markdown）。返回 [{content, doc_name}, ...]。"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文档不存在: {file_path}")
        doc_name = path.name
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return DocumentLoader._load_pdf(file_path, doc_name)
        else:  # .txt/.md/其他
            return DocumentLoader._load_text(file_path, doc_name)

    @staticmethod
    def _load_text(file_path: str, doc_name: str) -> list:
        with open(file_path, "r", encoding="utf-8") as f:
            return [{"content": f.read(), "doc_name": doc_name}]

    @staticmethod
    def _load_pdf(file_path: str, doc_name: str) -> list:
        try:
            from langchain_community.document_loaders import PyPDFLoader
            loader = PyPDFLoader(file_path)
            pages = loader.load()
            return [{"content": p.page_content, "doc_name": doc_name} for p in pages]
        except ImportError:
            # fallback: 无 PyPDFLoader 时用 pypdf
            import pypdf
            reader = pypdf.PdfReader(file_path)
            return [{"content": p.extract_text(), "doc_name": doc_name} for p in reader.pages]
```

### 5.6 vector_store.py — ChromaDB 嵌入式

```python
import chromadb
from typing import Optional, List, Dict, Any

class RAGVectorStore:
    """ChromaDB 嵌入式向量存储（chunk-oriented，不污染 memory 的 chroma）。"""

    def __init__(self, persist_directory: str = "data/chroma_rag",
                 collection_name: str = "knowledge_chunks"):
        self._client = chromadb.PersistentClient(path=persist_directory)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, ids: List[str], embeddings: List[List[float]],
            documents: List[Dict], metadatas: List[Dict]) -> None:
        """添加 chunks（documents 含 content/doc_name/node_title）。"""
        # chromadb metadata 只支持 str/int/float/bool，序列化嵌套字段
        clean_metadatas = [
            {k: v for k, v in m.items() if v is not None}
            for m in metadatas
        ]
        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=[d["content"] for d in documents],
            metadatas=clean_metadatas,
        )

    def search(self, query_embedding: List[float], n_results: int = 5,
               where: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """相似性搜索。返回 [{content, doc_name, node_title, score}, ...]。"""
        kwargs = {"query_embeddings": [query_embedding], "n_results": n_results}
        if where:
            kwargs["where"] = where
        results = self._collection.query(**kwargs)
        if not results["documents"] or not results["documents"][0]:
            return []
        docs = results["documents"][0]
        metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
        return [
            {
                "content": doc,
                "doc_name": m.get("doc_name", "unknown"),
                "node_title": m.get("node_title", ""),
                "score": 1 - dist if dist else 0,  # chromadb 返回 distance，转 similarity
            }
            for doc, m, dist in zip(
                docs, metadatas,
                results.get("distances", [[0] * len(docs)])[0]
            )
        ]
```

### 5.7 config — 新增 rag.* 段

`config/agent_config.json` 加（顶层或 agent 段内）：

```json
"rag": {
    "chunk_size": 512,
    "_comment_chunk_size": "文档分块大小（token 数，512 是普适甜点）",
    "chunk_overlap": 51,
    "_comment_chunk_overlap": "分块重叠（10%）",
    "persist_directory": "data/chroma_rag",
    "_comment_persist_directory": "ChromaDB 持久化目录（与 memory 的 chroma 分开）",
    "collection_name": "knowledge_chunks",
    "_comment_collection_name": "ChromaDB collection 名"
}
```

### 5.8 requirements.txt — 补 chromadb

```
chromadb>=1.5.0
langchain-text-splitters>=0.3.0
```

（langchain_community 已有用于 PyPDFLoader）

---

## 6. 数据流

```
ingest("report.pdf", kb_id="kb1"):
  DocumentLoader.load → [{content, doc_name}]
  Chunker.split(512) → [{content, doc_name, node_title}, ...]
  embedding_factory.embed_documents → [[float, ...], ...]
  RAGVectorStore.add → ChromaDB collection（metadata: kb_id/doc_name）

retrieve(query="营收增长", strategy="semantic", top_k=5, kb_id="kb1"):
  embed_query → [float, ...]
  ChromaDB.query(query_embeddings, n_results=5, where={kb_id: "kb1"})
  → [{content, doc_name, node_title, score}, ...]
  → RetrieveResult(query, strategy, latency_ms, [Chunk, ...])
```

---

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| 文档不存在 | FileNotFoundError |
| PDF 加载失败 | fallback pypdf |
| embedding API 不可用 | embedding_factory 已有降级（OpenAIEmbeddings → RuntimeError） |
| ChromaDB 初始化失败 | except + log + raise（无法降级） |
| retrieve 无结果 | 返回空 chunks 的 RetrieveResult |
| chromadb metadata 嵌套字段 | 序列化为 JSON 字符串 + None 过滤（参考 memory/storage.py） |

---

## 8. 测试策略

### 8.1 单元测试 `test/test_rag_system.py`（新建，不依赖外部 API）

| 测试 | 验证 |
|---|---|
| Chunker split | 输入长文本 → 输出 chunks（含 content/doc_name/node_title） |
| DocumentLoader text | .txt 文件 → [{content, doc_name}] |
| RAGVectorStore add + search | add chunks → search → 返回相似结果 |
| RAGSystem retrieve 接口契约 | retrieve(*, query, strategy, top_k, kb_id) → RetrieveResult（含 .query/.strategy/.latency_ms/.chunks） |
| RAGSystem retrieve 无结果 | 空 collection → 返回空 chunks |
| Chunk dataclass | Chunk(doc_name, node_title, content) 属性正确 |

**mock embedding**：测试用 mock embedding_model（避免依赖 dashscope API）。

### 8.2 集成测试（可选，需 embedding API）

- ingest 文档 → retrieve → 验证相关性

---

## 9. 文件变更清单

| 文件 | 变更类型 |
|---|---|
| `rag/__init__.py` | 新建 |
| `rag/rag_system/__init__.py` | 新建 |
| `rag/rag_system/rag_system.py` | 新建（RAGSystem 核心） |
| `rag/rag_system/models.py` | 新建（RetrieveResult / Chunk） |
| `rag/rag_system/document_loader.py` | 新建 |
| `rag/rag_system/chunker.py` | 新建 |
| `rag/rag_system/vector_store.py` | 新建 |
| `config/agent_config.json` | 改（新增 rag.* 段） |
| `requirements.txt` | 改（补 chromadb） |
| `test/test_rag_system.py` | 新建 |

---

## 10. 风险与回退

| 风险 | 等级 | 缓解 |
|---|---|---|
| embedding API key 不可用（dashscope） | 中 | embedding_factory 已有降级；测试用 mock |
| chromadb metadata 嵌套字段 | 低 | 序列化为 JSON 字符串（参考 memory/storage.py） |
| PyPDFLoader 依赖 langchain_community | 低 | fallback pypdf |
| 接口契约不符（unstructured_knowledge_tool 调用失败） | 中 | 严格对齐 retrieve(*, query, strategy, top_k, kb_id) + 返回对象属性 |
| ChromaDB 与 memory 的 chroma 冲突 | 低 | 独立 persist_directory（data/chroma_rag vs data/chroma） |

**回退**：rag/ 目录空时，unstructured_knowledge_tool 的 rag_system property 不触发（lazy import）。实现后自然生效。

---

## 11. 后续（非本期）

- Phase 2：Cross-encoder Rerank + Hybrid Search（Dense+BM25 RRF）
- Phase 2：Query Rewriting（仅对失败查询）
- Phase 3：Agentic RAG（LangGraph agentic loop + multi-query / HyDE）
- Phase 3：Qdrant 切换（生产化）+ RAGAS 评估
- 知识库 DB 集成（KnowledgeBaseDocumentRepository）
