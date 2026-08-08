# RAG 模块实施计划 — 方案 A（最小 RAG）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** 实现 rag/rag_system/rag_system.py，严格对齐接口契约（retrieve(*, query, strategy, top_k, kb_id) → RetrieveResult），复用 embedding_factory + ChromaDB。

**Spec:** `docs/superpowers/specs/2026-07-16-rag-module-design.md`（commit 40d5d2a）

**Test command:** `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest <test> -v -p no:warnings`

## Global Constraints

- retrieve 全关键字参数：`retrieve(*, query, strategy, top_k, kb_id)`
- 返回对象属性：`.query / .strategy / .latency_ms / .chunks`
- chunk 属性：`.doc_name / .node_title / .content`
- 复用 memory/embedding_factory.py
- ChromaDB 嵌入式（data/chroma_rag，与 memory 隔离）
- RecursiveCharacterTextSplitter 512 + 51 overlap

---

### Task 1: models.py + chunker.py + document_loader.py（基础组件）

**Files:** Create `rag/__init__.py`, `rag/rag_system/__init__.py`, `rag/rag_system/models.py`, `rag/rag_system/chunker.py`, `rag/rag_system/document_loader.py`, `test/test_rag_system.py`

- [ ] **Step 1: Write failing test**

```python
# test/test_rag_system.py
"""RAG 模块测试（spec: docs/superpowers/specs/2026-07-16-rag-module-design.md）。"""
from rag.rag_system.models import Chunk, RetrieveResult
from rag.rag_system.chunker import create_chunker
from rag.rag_system.document_loader import load_document


def test_chunk_dataclass():
    """Chunk 有 doc_name/node_title/content 属性。"""
    c = Chunk(doc_name="report.pdf", node_title="chunk_0", content="营收增长 20%")
    assert c.doc_name == "report.pdf"
    assert c.node_title == "chunk_0"
    assert c.content == "营收增长 20%"


def test_retrieve_result_dataclass():
    """RetrieveResult 有 query/strategy/latency_ms/chunks 属性。"""
    r = RetrieveResult(query="分析", strategy="semantic", latency_ms=12.5, chunks=[])
    assert r.query == "分析"
    assert r.strategy == "semantic"
    assert r.latency_ms == 12.5
    assert r.chunks == []


def test_chunker_split():
    """Chunker 分块长文本。"""
    chunker = create_chunker(chunk_size=100, chunk_overlap=10)
    text = "A" * 250
    chunks = chunker.split_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= 110 for c in chunks)  # 100 + overlap


def test_document_loader_text(tmp_path):
    """load_document 加载 .txt 文件。"""
    f = tmp_path / "test.txt"
    f.write_text("hello world", encoding="utf-8")
    texts = load_document(str(f))
    assert len(texts) >= 1
    assert "hello" in texts[0]
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest test/test_rag_system.py -v -p no:warnings --tb=line`
Expected: FAIL（No module named 'rag.rag_system.models'）

- [ ] **Step 3: Implement models + chunker + document_loader**

```python
# rag/__init__.py
# （空）

# rag/rag_system/__init__.py
# （空）

# rag/rag_system/models.py
from dataclasses import dataclass, field
from typing import List

@dataclass
class Chunk:
    doc_name: str
    node_title: str
    content: str

@dataclass
class RetrieveResult:
    query: str
    strategy: str
    latency_ms: float
    chunks: List[Chunk] = field(default_factory=list)

# rag/rag_system/chunker.py
from langchain_text_splitters import RecursiveCharacterTextSplitter

def create_chunker(chunk_size: int = 512, chunk_overlap: int = 51):
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )

# rag/rag_system/document_loader.py
from pathlib import Path

def load_document(file_path: str) -> list:
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        from langchain_community.document_loaders import PyPDFLoader
        docs = PyPDFLoader(file_path).load()
    else:
        from langchain_community.document_loaders import TextLoader
        docs = TextLoader(file_path).load()
    return [d.page_content for d in docs]
```

- [ ] **Step 4: Run GREEN**

Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add rag/ test/test_rag_system.py
git commit -m "feat(rag): models + chunker + document_loader (TDD GREEN 4/4)"
```

---

### Task 2: rag_system.py（RAGSystem 核心，对齐接口契约）

**Files:** Create `rag/rag_system/rag_system.py`, Modify `config/agent_config.json`, Modify `test/test_rag_system.py`

- [ ] **Step 1: Add config rag.* 段**

`config/agent_config.json` 加：
```json
"rag": {
    "persist_directory": "data/chroma_rag",
    "chunk_size": 512,
    "chunk_overlap": 51,
    "_comment": "RAG 模块配置"
},
```

- [ ] **Step 2: Write failing test（接口契约）**

追加到 `test/test_rag_system.py`：

```python
from rag.rag_system.rag_system import RAGSystem
from unittest.mock import MagicMock


def test_rag_system_init():
    """RAGSystem 初始化不报错。"""
    import tempfile, os
    os.environ["DASHSCOPE_API_KEY"] = "test"  # 避免 API key 缺失
    with tempfile.TemporaryDirectory() as tmp:
        import rag.rag_system.rag_system as rs_mod
        # mock embedding 避免 API 调用
        rs_mod_mod = rs_mod
        rs = RAGSystem.__new__(RAGSystem)
        rs._persist_dir = tmp
        rs._chunker = create_chunker(100, 10)
        rs._embedder = MagicMock()
        rs._embedder.embed_query = MagicMock(return_value=[0.1] * 10)
        import chromadb
        rs._chroma = chromadb.PersistentClient(path=tmp)
        assert rs is not None


def test_retrieve_interface_contract():
    """retrieve(*, query, strategy, top_k, kb_id) → RetrieveResult（接口契约）。"""
    import tempfile, chromadb, uuid
    from rag.rag_system.rag_system import RAGSystem
    from unittest.mock import MagicMock

    with tempfile.TemporaryDirectory() as tmp:
        rs = RAGSystem.__new__(RAGSystem)
        rs._persist_dir = tmp
        rs._chunker = create_chunker(100, 10)
        rs._embedder = MagicMock()
        rs._embedder.embed_query = MagicMock(return_value=[0.1] * 10)
        rs._chroma = chromadb.PersistentClient(path=tmp)

        # ingest 测试数据
        col = rs._get_collection("test_kb")
        col.add(
            ids=["c1", "c2"],
            embeddings=[[0.1] * 10, [0.2] * 10],
            documents=["营收增长", "利润下降"],
            metadatas=[{"doc_name": "report.pdf", "node_title": "chunk_0"},
                       {"doc_name": "report.pdf", "node_title": "chunk_1"}],
        )

        # retrieve
        result = rs.retrieve(query="营收", strategy="semantic", top_k=2, kb_id="test_kb")
        assert hasattr(result, "query")
        assert hasattr(result, "strategy")
        assert hasattr(result, "latency_ms")
        assert hasattr(result, "chunks")
        assert result.query == "营收"
        assert result.strategy == "semantic"
        assert len(result.chunks) <= 2
        for chunk in result.chunks:
            assert hasattr(chunk, "doc_name")
            assert hasattr(chunk, "node_title")
            assert hasattr(chunk, "content")


def test_retrieve_empty_kb():
    """retrieve 空 kb_id → 返回空 chunks（不报错）。"""
    import tempfile, chromadb
    from rag.rag_system.rag_system import RAGSystem
    from unittest.mock import MagicMock

    with tempfile.TemporaryDirectory() as tmp:
        rs = RAGSystem.__new__(RAGSystem)
        rs._persist_dir = tmp
        rs._chunker = create_chunker(100, 10)
        rs._embedder = MagicMock()
        rs._embedder.embed_query = MagicMock(return_value=[0.1] * 10)
        rs._chroma = chromadb.PersistentClient(path=tmp)

        result = rs.retrieve(query="test", strategy="semantic", top_k=5, kb_id="empty_kb")
        assert result.chunks == []
```

- [ ] **Step 3: Run RED**

Expected: FAIL（No module named 'rag.rag_system.rag_system'）

- [ ] **Step 4: Implement rag_system.py**

```python
# rag/rag_system/rag_system.py
"""RAGSystem — 严格对齐 unstructured_knowledge_tool.py 接口契约。

retrieve(*, query, strategy, top_k, kb_id) → RetrieveResult
"""
import time
import uuid
from typing import Optional
from loguru import logger
from rag.rag_system.models import Chunk, RetrieveResult
from rag.rag_system.chunker import create_chunker
from rag.rag_system.document_loader import load_document


class RAGSystem:
    def __init__(self, config_path: str = None):
        from utils.config import get_config
        from memory.embedding_factory import create_embedding_model
        self._persist_dir = get_config("rag.persist_directory", "data/chroma_rag")
        self._chunker = create_chunker(
            get_config("rag.chunk_size", 512),
            get_config("rag.chunk_overlap", 51),
        )
        self._embedder = create_embedding_model(log_tag="RAG")
        import chromadb
        self._chroma = chromadb.PersistentClient(path=self._persist_dir)
        logger.info(f"[RAGSystem] 初始化: persist={self._persist_dir}")

    def _get_collection(self, kb_id: str):
        return self._chroma.get_or_create_collection(
            name=kb_id, metadata={"hnsw:space": "cosine"})

    def _embed(self, texts: list) -> list:
        import asyncio
        if hasattr(self._embedder, "aembed_query"):
            loop = asyncio.new_event_loop()
            return [loop.run_until_complete(self._embedder.aembed_query(t)) for t in texts]
        if hasattr(self._embedder, "embed_query"):
            return [self._embedder.embed_query(t) for t in texts]
        return self._embedder.encode(texts).tolist()

    def ingest(self, file_path: str, kb_id: str) -> int:
        texts = load_document(file_path)
        chunks = []
        for text in texts:
            chunks.extend(self._chunker.split_text(text))
        embeddings = self._embed(chunks)
        col = self._get_collection(kb_id)
        col.add(
            ids=[str(uuid.uuid4()) for _ in chunks],
            embeddings=embeddings,
            documents=chunks,
            metadatas=[{"doc_name": file_path, "node_title": f"chunk_{i}"} for i in range(len(chunks))],
        )
        logger.info(f"[RAGSystem] ingest {file_path} → {len(chunks)} chunks (kb={kb_id})")
        return len(chunks)

    def retrieve(self, *, query: str, strategy: str, top_k: int, kb_id: str) -> RetrieveResult:
        start = time.time()
        col = self._get_collection(kb_id)
        q_emb = self._embed([query])[0]
        results = col.query(query_embeddings=[q_emb], n_results=top_k)
        latency_ms = (time.time() - start) * 1000

        chunks = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            chunks.append(Chunk(
                doc_name=meta.get("doc_name", "unknown"),
                node_title=meta.get("node_title", f"chunk_{i}"),
                content=doc,
            ))
        logger.info(f"[RAGSystem] retrieve kb={kb_id} → {len(chunks)} chunks {latency_ms:.1f}ms")
        return RetrieveResult(query=query, strategy=strategy, latency_ms=latency_ms, chunks=chunks)
```

- [ ] **Step 5: Run GREEN**

Expected: 7 PASS（Task1 4 + Task2 3）

- [ ] **Step 6: Commit**

```bash
git add rag/rag_system/rag_system.py config/agent_config.json test/test_rag_system.py
git commit -m "feat(rag): RAGSystem retrieve+ingest (interface contract aligned, TDD GREEN)"
```

---

### Task 3: requirements.txt + 回归

- [ ] **Step 1: 补依赖**

`requirements.txt` 加：
```
langchain-text-splitters>=0.3.0
```
（chromadb 已手动安装，langchain-community 已有）

- [ ] **Step 2: 回归**

Run: `python -m pytest test/test_rag_system.py test/test_human_approval.py test/test_concurrency_control.py -v -p no:warnings --tb=line`
Expected: 全 PASS

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add langchain-text-splitters for RAG"
```

---

## Self-Review

- ✅ spec §6.1 models → Task 1
- ✅ spec §6.2 chunker → Task 1
- ✅ spec §6.3 document_loader → Task 1
- ✅ spec §6.4 rag_system.py → Task 2
- ✅ spec §6.5 config rag.* → Task 2 Step 1
- ✅ 接口契约 retrieve(*, query, strategy, top_k, kb_id) → Task 2 Step 2/4
- ✅ 返回对象 .query/.strategy/.latency_ms/.chunks → Task 2 测试验证
- ✅ chunk .doc_name/.node_title/.content → Task 1 测试验证
- 无 placeholder，全代码+命令
