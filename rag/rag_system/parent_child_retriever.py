# rag/rag_system/parent_child_retriever.py
# ParentDocumentRetriever 集成 — 检索子块返回父块
# librarist 调研：langchain_classic.retrievers.ParentDocumentRetriever
# 子块→vectorstore（精度高），父块→docstore（上下文完整）
from loguru import logger
from typing import Optional, List, Dict, Any


class ParentChildRetriever:
    """ParentDocumentRetriever 封装。

    模式 A：parent_splitter=None → 父块=完整文档
    模式 B：parent_splitter=RecursiveCharacterTextSplitter → 父块=大段落

    检索时：query → 匹配子块 → 通过 parent_id 查 docstore → 返回父块
    """

    def __init__(self, vector_store, embedder,
                 parent_chunk_size: int = 1000, parent_overlap: int = 100,
                 child_chunk_size: int = 200, child_overlap: int = 20):
        """
        Args:
            vector_store: ChromaDB collection（存子块向量）
            embedder: embedding 模型
            parent_chunk_size: 父块大小
            child_chunk_size: 子块大小
        """
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        from langchain_core.stores import InMemoryStore

        self._embedder = embedder
        self._docstore = InMemoryStore()
        self._parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=parent_chunk_size,
            chunk_overlap=parent_overlap,
            separators=["\n\n", "\n", " ", ""],
        )
        self._child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_chunk_size,
            chunk_overlap=child_overlap,
            separators=["\n", " ", ""],
        )
        # vector_store 是 ChromaDB collection，包装为 langchain VectorStore
        self._collection = vector_store
        self._child_ids_map = {}  # parent_id → [child_ids]
        self._parent_docs = {}     # parent_id → parent_content
        logger.info(f"[ParentChildRetriever] parent={parent_chunk_size} child={child_chunk_size}")

    def add_documents(self, texts: List[str], doc_name: str = "unknown", collection=None) -> int:
        """添加文档：父块→docstore，子块→vector_store。

        Args:
            collection: 请求级 collection 覆盖（None 时用 self._collection），
                        不写共享实例属性，防并发污染。

        Returns:
            添加的子块数
        """
        import uuid
        total_children = 0
        col = collection if collection is not None else self._collection

        for text in texts:
            # 1. 父块切分
            parent_chunks = self._parent_splitter.split_text(text)
            for parent_text in parent_chunks:
                parent_id = str(uuid.uuid4())
                self._parent_docs[parent_id] = {
                    "content": parent_text,
                    "doc_name": doc_name,
                }

                # 2. 子块切分
                child_chunks = self._child_splitter.split_text(parent_text)
                child_ids = []
                child_embeddings = self._embed(child_chunks)

                # 3. 子块存入 vector_store（含 parent_id metadata）
                col_child_ids = []
                col_embeddings = []
                col_documents = []
                col_metadatas = []
                for i, (child_text, emb) in enumerate(zip(child_chunks, child_embeddings)):
                    cid = f"{parent_id}_{i}"
                    child_ids.append(cid)
                    col_child_ids.append(cid)
                    col_embeddings.append(emb)
                    col_documents.append(child_text)
                    col_metadatas.append({
                        "parent_id": parent_id,
                        "doc_name": doc_name,
                        "node_title": f"child_{i}",
                    })

                if col_child_ids:
                    col.add(
                        ids=col_child_ids,
                        embeddings=col_embeddings,
                        documents=col_documents,
                        metadatas=col_metadatas,
                    )
                    total_children += len(col_child_ids)

                self._child_ids_map[parent_id] = child_ids

        logger.info(f"[ParentChildRetriever] add_documents: {len(texts)} docs → {total_children} children")
        return total_children

    def retrieve(self, query: str, top_k: int = 5, collection=None) -> List[Dict[str, Any]]:
        """检索：query → 匹配子块 → 返回父块。

        Args:
            collection: 请求级 collection 覆盖（None 时用 self._collection），
                        不写共享实例属性，防并发污染。

        Returns:
            [{content, doc_name, node_title, score}, ...]（父块内容）
        """
        col = collection if collection is not None else self._collection
        # 1. embed query
        q_emb = self._embed([query])[0]

        # 2. 搜索子块（多取一些，因为多个子块可能映射到同一父块）
        results = col.query(
            query_embeddings=[q_emb],
            n_results=top_k * 3,  # 多取 3x，去重父块后取 top_k
        )

        if not results.get("documents") or not results["documents"][0]:
            return []

        docs = results["documents"][0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        # 3. 通过 parent_id 去重 + 取父块
        seen_parents = set()
        parent_results = []
        for i, (doc, meta, dist) in enumerate(zip(docs, metas, distances)):
            parent_id = meta.get("parent_id", "")
            if parent_id in seen_parents:
                continue
            seen_parents.add(parent_id)

            parent_doc = self._parent_docs.get(parent_id, {})
            parent_results.append({
                "content": parent_doc.get("content", doc),
                "doc_name": parent_doc.get("doc_name", meta.get("doc_name", "unknown")),
                "node_title": f"parent_{parent_id[:8]}",
                "score": 1 - dist if dist else 0,
            })

            if len(parent_results) >= top_k:
                break

        logger.info(f"[ParentChildRetriever] retrieve: query='{query[:30]}' → "
                    f"{len(docs)} children → {len(parent_results)} unique parents")
        return parent_results[:top_k]

    def _embed(self, texts: list) -> list:
        """嵌入文本（委托共享助手 embed_list，零向量回退开启以兼容 MagicMock embedder）。"""
        from rag.rag_system.embed_utils import embed_list
        return embed_list(self._embedder, texts, zero_fallback=True)
