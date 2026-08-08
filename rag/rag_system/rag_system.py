# rag/rag_system/rag_system.py
"""RAGSystem — 严格对齐 unstructured_knowledge_tool.py 接口契约。

retrieve(*, query, strategy, top_k, kb_id) → RetrieveResult
ingest(file_path, kb_id) → int
"""
import time
import uuid
from loguru import logger
from rag.rag_system.models import Chunk, RetrieveResult
from rag.rag_system.chunker import create_chunker
from rag.rag_system.document_loader import load_document_with_meta


class RAGSystem:
    """RAG 系统（对齐 unstructured_knowledge_tool 接口契约）。

    retrieve(query, strategy, top_k, kb_id) → RetrieveResult
    ingest(file_path, kb_id) → int（chunk 数）
    """

    def __init__(self, config_path: str = None):
        """初始化 RAG 系统。

        Args:
            config_path: 配置路径（None 时读 config/agent_config.json 的 rag.* 段）
        """
        from utils.config import get_config
        from memory.embedding_factory import create_embedding_model

        self._persist_dir = get_config("rag.persist_directory", "data/chroma_rag")
        # chunk 参数（增强：按文档类型 + config）
        chunk_cfg = get_config("rag.chunk", {})
        self._chunk_size = chunk_cfg.get("size", 500)
        self._chunk_overlap = chunk_cfg.get("overlap", 100)
        self._by_doc_type = chunk_cfg.get("by_doc_type", {})
        self._chunker = create_chunker(self._chunk_size, self._chunk_overlap)
        self._embedder = create_embedding_model(log_tag="RAG")
        import chromadb
        self._chroma = chromadb.PersistentClient(path=self._persist_dir)
        # 混合检索（增强）
        hybrid_cfg = get_config("rag.hybrid", {})
        self._hybrid_enabled = hybrid_cfg.get("enabled", False)
        if self._hybrid_enabled:
            from rag.rag_system.hybrid_retriever import HybridRetriever
            self._hybrid = HybridRetriever(self._embedder, hybrid_cfg.get("ratio", 0.7))
        else:
            self._hybrid = None
        # Rerank（增强）
        rerank_cfg = get_config("rag.rerank", {})
        self._rerank_enabled = rerank_cfg.get("enabled", False)
        if self._rerank_enabled:
            from rag.rag_system.reranker import Reranker
            self._reranker = Reranker(rerank_cfg.get("model", "BAAI/bge-reranker-base"))
        else:
            self._reranker = None
        # Query Rewriting（Phase 2）
        rewrite_cfg = get_config("rag.query_rewrite", {})
        self._rewrite_enabled = rewrite_cfg.get("enabled", False)
        if self._rewrite_enabled:
            from rag.rag_system.query_rewriter import QueryRewriter
            from utils.llm import get_default_llm
            self._rewriter = QueryRewriter(llm_model=get_default_llm(), enabled=True)
        else:
            self._rewriter = None
        # Parent-Child Retriever（ParentDocumentRetriever 集成）
        pc_cfg = get_config("rag.chunk.parent_child", {})
        self._parent_child_enabled = pc_cfg.get("enabled", False)
        if self._parent_child_enabled:
            from rag.rag_system.parent_child_retriever import ParentChildRetriever
            self._pc_retriever = ParentChildRetriever(
                vector_store=None,  # 延迟到 ingest 时绑定 collection
                embedder=self._embedder,
                parent_chunk_size=pc_cfg.get("parent_size", 1000),
                parent_overlap=pc_cfg.get("parent_overlap", 200),
                child_chunk_size=pc_cfg.get("child_size", 200),
                child_overlap=pc_cfg.get("child_overlap", 20),
            )
        else:
            self._pc_retriever = None
        # Adaptive（接入 A）：AgenticRAG 仅检索模式，懒初始化（需 LLM，避免 init 拖慢）
        self._agentic = None
        logger.info(f"[RAGSystem] init: persist={self._persist_dir} hybrid={self._hybrid_enabled} rerank={self._rerank_enabled} rewrite={self._rewrite_enabled} parent_child={self._parent_child_enabled}")

    def _get_agentic(self):
        """懒初始化 AgenticRAG（adaptive 仅检索模式）。"""
        if self._agentic is None:
            from rag.rag_system.agentic_rag import AgenticRAG
            from utils.llm import get_default_llm
            from utils.config import get_config
            max_attempts = int(get_config("rag.adaptive.max_attempts", 3))
            self._agentic = AgenticRAG(
                rag_system=self,
                llm_model=get_default_llm(),
                max_attempts=max_attempts,
            )
            logger.info(f"[RAGSystem] adaptive retriever 初始化 (max_attempts={max_attempts})")
        return self._agentic

    async def retrieve_adaptive_async(
        self, *, query: str, kb_id: str = "default", top_k: int = 5
    ) -> RetrieveResult:
        """Adaptive 检索策略：Agentic RAG 循环（检索→评估→改写重检索），返回改善后 chunks。

        异步实现（LangGraph ainvoke），调用方应在 async 上下文中 await
        （不经 to_thread）。不做最终生成，供外层 agent 继续生成。
        """
        start = time.time()
        agentic = self._get_agentic()
        chunk_dicts = await agentic.retrieve_adaptive(query=query, kb_id=kb_id, top_k=top_k)
        chunks = [
            Chunk(
                doc_name=c.get("doc_name", "unknown"),
                node_title=c.get("node_title", ""),
                content=c.get("content", ""),
                page=c.get("page"),
                char_start=c.get("char_start"),
                char_end=c.get("char_end"),
            )
            for c in chunk_dicts
        ]
        latency_ms = (time.time() - start) * 1000
        logger.info(f"[RAGSystem] adaptive retrieve kb={kb_id} q='{query[:30]}' → {len(chunks)} chunks {latency_ms:.1f}ms")
        return RetrieveResult(query=query, strategy="adaptive", latency_ms=latency_ms, chunks=chunks)

    def _get_collection(self, kb_id: str):
        return self._chroma.get_or_create_collection(
            name=kb_id, metadata={"hnsw:space": "cosine"})

    @property
    def embedder(self):
        """embedding 模型实例（供 KBRouter 等外部组件复用，避免重复初始化）。"""
        return self._embedder

    def _embed(self, texts: list) -> list:
        """嵌入文本（委托共享助手 embed_batch，优先批量 embed_documents 防逐条 HTTP 超时）。"""
        from rag.rag_system.embed_utils import embed_batch
        return embed_batch(self._embedder, texts)

    def ingest(self, file_path: str, kb_id: str, doc_name: str = None) -> int:
        """加载→分块→嵌入→存储。返回 chunk 数。

        parent_child 模式：父块→docstore，子块→vector store

        Args:
            file_path: 文件路径
            kb_id: 知识库 ID
            doc_name: 文档名（metadata 用），None 时用 file_path basename。
                      避免 metadata 存临时路径导致检索结果不可读。
        """
        from pathlib import Path
        doc_type = Path(file_path).suffix.lstrip(".").lower()
        effective_doc_name = doc_name or Path(file_path).name
        parts = load_document_with_meta(file_path)  # [{content, page}, ...]
        texts = [p["content"] for p in parts]

        # Parent-Child 模式
        if self._parent_child_enabled:
            col = self._get_collection(kb_id)
            count = self._pc_retriever.add_documents(texts, doc_name=effective_doc_name, collection=col)
            logger.info(f"[RAGSystem] ingest(parent-child) {file_path} → {count} children (kb={kb_id})")
            return count

        # 普通模式（带引用定位：page/char_start/char_end）
        chunker = create_chunker(self._chunk_size, self._chunk_overlap,
                                  doc_type=doc_type, by_doc_type=self._by_doc_type)
        overlap = getattr(chunker, "_chunk_overlap", self._chunk_overlap)
        chunks = []
        metadatas = []
        for part in parts:
            text = part.get("content") or ""
            if not text:
                continue
            page = part.get("page")
            page_meta = page if page is not None else -1  # chroma 无 None，用 -1 哨兵
            part_chunks = chunker.split_text(text)
            offsets = self._locate_chunks(text, part_chunks, overlap)
            for c, (cs, ce) in zip(part_chunks, offsets):
                metadatas.append({
                    "doc_name": effective_doc_name,
                    "node_title": f"chunk_{len(chunks)}",
                    "page": page_meta,
                    "char_start": cs,
                    "char_end": ce,
                })
                chunks.append(c)
        embeddings = self._embed(chunks)
        col = self._get_collection(kb_id)
        col.add(
            ids=[str(uuid.uuid4()) for _ in chunks],
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )
        logger.info(f"[RAGSystem] ingest {file_path} → {len(chunks)} chunks (kb={kb_id})")
        return len(chunks)

    @staticmethod
    def _locate_chunks(text: str, chunks: list, overlap: int) -> list:
        """计算每个 chunk 在分片文本内的字符偏移 [start, end)。

        分块器按序产出、子块间存在 overlap。游标每次前进 (len - overlap)
        （数学上 <= 下一块真实起点），故 text.find(chunk, cursor) 不会跳过
        真实起点；find 失败时回退全量搜索，保证不崩。
        """
        offsets = []
        cursor = 0
        for chunk in chunks:
            pos = text.find(chunk, cursor)
            if pos < 0:
                pos = text.find(chunk, 0)  # 回退：从头找（异常重叠/改写场景）
            if pos < 0:
                pos = cursor  # 兜底：保证递增，引用可溯源但可能不精确
            offsets.append((pos, pos + len(chunk)))
            cursor = pos + max(1, len(chunk) - overlap)
        return offsets

    def retrieve(self, *, query: str, strategy: str, top_k: int, kb_id: str,
                 metadata_filter: dict = None, ratio: float = None) -> RetrieveResult:
        """检索。对齐接口契约。支持 multi-query + hybrid + rerank + metadata 过滤。

        Args:
            query: 查询文本
            strategy: 检索策略（"semantic"/"metadata"/"global"）
            top_k: 返回 top-k 结果
            kb_id: 知识库 ID
            metadata_filter: 元数据过滤 {field: value}，如 {"doc_name": "report.pdf"}
        Returns:
            RetrieveResult（含 query/strategy/latency_ms/chunks）
        """
        import asyncio
        start = time.time()
        col = self._get_collection(kb_id)

        # 1. Multi-query / Query Rewriting（可选）
        queries = [query]
        if self._rewriter:
            try:
                loop = asyncio.new_event_loop()
                try:
                    queries = loop.run_until_complete(self._rewriter.rewrite(query))
                finally:
                    loop.close()
            except Exception as e:
                logger.warning(f"[RAGSystem] query rewrite 失败: {e}，用原查询")
                queries = [query]

        # ratio 覆盖 config 默认：请求级传递给 hybrid.retrieve（不写共享单例，防并发串库）

        # 2. strategy 控制检索模式（semantic=纯向量, hybrid=BM25+向量RRF, keyword=纯BM25）
        all_results = []
        for q in queries:
            if self._parent_child_enabled:
                partial = self._pc_retriever.retrieve(q, top_k, collection=col)
            elif strategy == "keyword" and self._hybrid is not None:
                partial = self._hybrid.retrieve_bm25_only(q, col, top_k * 2)
            elif strategy == "hybrid" and self._hybrid is not None:
                partial = self._hybrid.retrieve(q, top_k * 2, col, ratio=ratio)
            else:
                # semantic / metadata / global / fallback → 纯向量 + metadata 过滤
                partial = self._vector_search(q, col, top_k, metadata_filter)
            all_results.append(partial)

        # RRF 融合多路结果
        if len(all_results) > 1:
            results = self._rrf_fuse(all_results, top_k)
        else:
            results = all_results[0] if all_results else []

        # 3. Rerank（可选）
        if self._reranker:
            results = self._reranker.rerank(query, results, top_k)

        chunks = [
            Chunk(doc_name=r["doc_name"], node_title=r["node_title"], content=r["content"],
                  page=r.get("page"), char_start=r.get("char_start"), char_end=r.get("char_end"))
            for r in results[:top_k]
        ]
        latency_ms = (time.time() - start) * 1000
        logger.info(f"[RAGSystem] retrieve kb={kb_id} queries={len(queries)} → "
                    f"{len(chunks)} chunks {latency_ms:.1f}ms"
                    f"{' +metadata_filter' if metadata_filter else ''}")
        return RetrieveResult(query=query, strategy=strategy, latency_ms=latency_ms, chunks=chunks)

    @staticmethod
    def _locator_from_meta(meta: dict | None) -> dict:
        """从 chroma metadata 提取引用定位（page 用 -1 哨兵表示无页码）。"""
        meta = meta or {}
        page = meta.get("page")
        return {
            "page": page if page not in (None, -1) else None,
            "char_start": meta.get("char_start"),
            "char_end": meta.get("char_end"),
        }

    def _vector_search(self, query: str, col, top_k: int,
                       metadata_filter: dict = None) -> list:
        """纯向量检索 + metadata 过滤。"""
        q_emb = self._embed([query])[0]
        kwargs = {"query_embeddings": [q_emb], "n_results": top_k}
        if metadata_filter:
            kwargs["where"] = metadata_filter
        raw = col.query(**kwargs)
        docs = raw.get("documents", [[]])[0]
        metas = raw.get("metadatas", [[]])[0]
        return [
            {"content": doc,
             "doc_name": (metas[i] if i < len(metas) else {}).get("doc_name", "unknown"),
             "node_title": (metas[i] if i < len(metas) else {}).get("node_title", f"chunk_{i}"),
             **self._locator_from_meta(metas[i] if i < len(metas) else None),
             "score": 0}
            for i, doc in enumerate(docs)
        ]

    @staticmethod
    def _rrf_fuse(multi_results: list, top_k: int, k: int = 60) -> list:
        """RRF 融合多路检索结果（委托共享助手 rrf_fuse，多路等权）。"""
        from rag.rag_system.embed_utils import rrf_fuse
        return rrf_fuse(multi_results, top_k, k=k)
