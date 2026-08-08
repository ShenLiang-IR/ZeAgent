# rag/rag_system/qdrant_store.py
# Qdrant 向量存储（Phase 3，可选，需 Docker）
# config rag.vector_store.backend = "qdrant" 时使用
from loguru import logger
from typing import Optional, List, Dict, Any


class QdrantVectorStore:
    """Qdrant 向量存储（与 ChromaDB RAGVectorStore 接口一致）。

    需：pip install qdrant-client + Docker 运行 Qdrant
    config: rag.vector_store.backend="qdrant", rag.vector_store.url="http://localhost:6333"
    """

    def __init__(self, url: str = "http://localhost:6333", collection_name: str = "knowledge_chunks"):
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams
            self._client = QdrantClient(url=url)
            self._collection_name = collection_name
            # 确保 collection 存在
            collections = self._client.get_collections().collections
            if not any(c.name == collection_name for c in collections):
                self._client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
                )
            logger.info(f"[QdrantVectorStore] init: url={url} collection={collection_name}")
        except ImportError:
            raise ImportError("qdrant-client 未安装：pip install qdrant-client")
        except Exception as e:
            raise RuntimeError(f"Qdrant 连接失败（需 Docker 运行）: {e}")

    def add(self, ids: List[str], embeddings: List[List[float]],
            documents: List[Dict], metadatas: List[Dict]) -> None:
        """添加 chunks。"""
        from qdrant_client.models import PointStruct
        points = [
            PointStruct(
                id=ids[i],
                vector=embeddings[i],
                payload={
                    "content": documents[i]["content"],
                    "doc_name": documents[i].get("doc_name", "unknown"),
                    "node_title": documents[i].get("node_title", ""),
                    **metadatas[i],
                },
            )
            for i in range(len(ids))
        ]
        self._client.upsert(collection_name=self._collection_name, points=points)

    def search(self, query_embedding: List[float], n_results: int = 5,
               where: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """相似性搜索。"""
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        query_filter = None
        if where:
            conditions = [FieldCondition(key=k, match=MatchValue(value=v)) for k, v in where.items()]
            query_filter = Filter(must=conditions)

        results = self._client.search(
            collection_name=self._collection_name,
            query_vector=query_embedding,
            limit=n_results,
            query_filter=query_filter,
        )
        return [
            {
                "content": r.payload.get("content", ""),
                "doc_name": r.payload.get("doc_name", "unknown"),
                "node_title": r.payload.get("node_title", ""),
                "score": r.score,
            }
            for r in results
        ]
