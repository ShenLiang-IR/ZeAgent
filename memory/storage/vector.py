import json
import os
from typing import Any, Dict, List, Optional
from loguru import logger
from ..blocks import MemoryBlock


class VectorStorage:
    def __init__(
        self,
        embedding_model: Optional[Any] = None,
        collection_name: str = "memories",
        backend: str = "chromadb",
        persist_directory: Optional[str] = None,
        knowledge_base_id: Optional[str] = None,
        similarity_threshold: float = 0.7
    ):
        self._embedding_model = embedding_model
        self._collection_name = collection_name
        self._backend = backend
        self._persist_directory = persist_directory or "data/chroma"
        self._knowledge_base_id = knowledge_base_id or "agent_memory"
        self._similarity_threshold = similarity_threshold
        self._client: Optional[Any] = None
        self._collection: Optional[Any] = None
        self._fallback_store: Dict[str, MemoryBlock] = {}
        self._fallback_embeddings: Dict[str, List[float]] = {}
        self._initialized = False
        logger.info(
            f"[VectorStorage]  | backend={backend}, "
            f"collection={collection_name}"
        )
    async def _ensure_initialized(self) -> bool:
        if self._initialized:
            return True
        try:
            if self._backend == "chromadb":
                await self._init_chromadb()
            elif self._backend == "pgvector":
                await self._init_pgvector()
            else:
                pass
            self._initialized = True
            return True
        except Exception as e:
            logger.warning(f"[VectorStorage] : {e}")
            self._backend = "memory"
            self._initialized = True
            return True
    async def _init_chromadb(self) -> None:
        try:
            import chromadb
            from chromadb.config import Settings
            os.makedirs(self._persist_directory, exist_ok=True)
            self._client = chromadb.Client(Settings(
                persist_directory=self._persist_directory,
                is_persistent=True
            ))
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(
                f"[VectorStorage] ChromaDB  | "
                f"persist_dir={self._persist_directory}, "
                f"collection={self._collection_name}"
            )
        except ImportError:
            logger.warning(
                "[VectorStorage] chromadb : pip install chromadb"
            )
            raise
        except Exception as e:
            logger.error(f"[VectorStorage] ChromaDB : {e}")
            raise
    async def _init_pgvector(self) -> None:
        try:
            from db_skills.implementations.text2sql_rag.knowledge_client import KnowledgeClient
            client = KnowledgeClient(
                knowledge_base_id=self._knowledge_base_id,
                auto_create=True
            )
            stats = await client.get_stats()
            logger.info(
                f"[VectorStorage] pgvector  | "
                f"knowledge_base_id={self._knowledge_base_id}, "
                f"existing_chunks={stats.get('total_chunks', 0)}"
            )
            self._client = client
        except Exception as e:
            logger.error(f"[VectorStorage] pgvector : {e}")
            raise
    async def _get_embedding_model(self) -> Any:
        """获取 embedding 模型（委托给 embedding_factory 工厂函数）"""
        if self._embedding_model is not None:
            return self._embedding_model
        from memory.embedding_factory import create_embedding_model
        self._embedding_model = create_embedding_model("[VectorStorage]")
        return self._embedding_model
    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        try:
            model = await self._get_embedding_model()
            if hasattr(model, 'aembed_query'):
                return await model.aembed_query(text)
            elif hasattr(model, 'embed_query'):
                return model.embed_query(text)
            elif hasattr(model, 'encode'):
                return model.encode(text).tolist()
        except Exception as e:
            logger.warning(f"[VectorStorage] : {e}")
        return None
    def set_client(self, client: Any) -> None:
        self._client = client
    @staticmethod
    def _deserialize_meta(meta: dict) -> dict:
        """chromadb metadata 只支持标量值，嵌套字段存为 JSON 字符串，读取时反序列化"""
        for k in ('metadata', 'tags'):
            if k in meta and isinstance(meta[k], str):
                try:
                    meta[k] = json.loads(meta[k])
                except (json.JSONDecodeError, TypeError):
                    pass
        return meta
    async def save(self, memory: MemoryBlock) -> bool:
        await self._ensure_initialized()
        embedding = await self._get_embedding(memory.content)
        memory.embedding = embedding
        if self._backend == "chromadb" and self._collection:
            return await self._save_chromadb(memory, embedding)
        elif self._backend == "pgvector" and self._client:
            return await self._save_pgvector(memory, embedding)
        else:
            self._fallback_store[memory.id] = memory
            if embedding:
                self._fallback_embeddings[memory.id] = embedding
            return True
    async def _save_chromadb(
        self,
        memory: MemoryBlock,
        embedding: Optional[List[float]]
    ) -> bool:
        try:
            metadata = memory.to_dict()
            metadata.pop('embedding', None)
            for k in ('metadata', 'tags'):
                if k in metadata and isinstance(metadata[k], (dict, list)):
                    metadata[k] = json.dumps(metadata[k], ensure_ascii=False)
            metadata = {k: v for k, v in metadata.items() if v is not None}
            self._collection.add(
                ids=[memory.id],
                documents=[memory.content],
                embeddings=[embedding] if embedding else None,
                metadatas=[metadata]
            )
            logger.debug(f"[VectorStorage] ChromaDB : {memory.id}")
            return True
        except Exception as e:
            logger.error(f"[VectorStorage] ChromaDB : {e}")
            self._fallback_store[memory.id] = memory
            if embedding:
                self._fallback_embeddings[memory.id] = embedding
            return True
    async def _save_pgvector(
        self,
        memory: MemoryBlock,
        embedding: Optional[List[float]]
    ) -> bool:
        try:
            success = await self._client.save(
                content=memory.content,
                metadata=memory.to_dict()
            )
            if success:
                logger.debug(f"[VectorStorage] pgvector : {memory.id}")
            return success
        except Exception as e:
            logger.error(f"[VectorStorage] pgvector : {e}")
            return False
    async def load(self, memory_id: str) -> Optional[MemoryBlock]:
        await self._ensure_initialized()
        if self._backend == "chromadb" and self._collection:
            try:
                results = self._collection.get(ids=[memory_id])
                if results and results.get('metadatas'):
                    return MemoryBlock.from_dict(self._deserialize_meta(results['metadatas'][0]))
            except Exception as e:
                logger.error(f"[VectorStorage] ChromaDB : {e}")
        elif self._backend == "pgvector" and self._client:
            pass
        return self._fallback_store.get(memory_id)
    async def delete(self, memory_id: str) -> bool:
        await self._ensure_initialized()
        if self._backend == "chromadb" and self._collection:
            try:
                self._collection.delete(ids=[memory_id])
                return True
            except Exception as e:
                logger.error(f"[VectorStorage] ChromaDB : {e}")
                return False
        elif self._backend == "pgvector" and self._client:
            return False
        else:
            if memory_id in self._fallback_store:
                del self._fallback_store[memory_id]
                self._fallback_embeddings.pop(memory_id, None)
                return True
            return False
    async def search(self, query: str, limit: int = 10,
                     user_id: Optional[str] = None,
                     session_id: Optional[str] = None,
                     workspace_id: Optional[str] = None) -> List[MemoryBlock]:
        await self._ensure_initialized()
        if self._backend == "chromadb" and self._collection:
            return await self._search_chromadb(query, limit, user_id, session_id, workspace_id)
        elif self._backend == "pgvector" and self._client:
            return await self._search_pgvector(query, limit, user_id, session_id, workspace_id)
        else:
            return await self._search_memory(query, limit, user_id, session_id, workspace_id)
    @staticmethod
    def _build_where(user_id: Optional[str], session_id: Optional[str],
                     workspace_id: Optional[str] = None) -> Optional[dict]:
        """构造 ChromaDB where 过滤条件（元数据预过滤，避免 post-filter 召回率下降）。"""
        conds = []
        if user_id:
            conds.append({"user_id": user_id})
        if session_id:
            conds.append({"session_id": session_id})
        if workspace_id:
            conds.append({"workspace_id": workspace_id})
        if not conds:
            return None
        return conds[0] if len(conds) == 1 else {"$and": conds}
    async def _search_chromadb(self, query: str, limit: int,
                               user_id: Optional[str] = None,
                               session_id: Optional[str] = None,
                               workspace_id: Optional[str] = None) -> List[MemoryBlock]:
        try:
            query_embedding = await self._get_embedding(query)
            where = self._build_where(user_id, session_id, workspace_id)
            results = self._collection.query(
                query_embeddings=[query_embedding] if query_embedding else None,
                query_texts=[query] if not query_embedding else None,
                n_results=limit,
                where=where,
                include=['metadatas', 'distances']
            )
            if results and results.get('metadatas'):
                memories = []
                for i, meta in enumerate(results['metadatas'][0]):
                    memory = MemoryBlock.from_dict(self._deserialize_meta(meta))
                    if results.get('distances') and i < len(results['distances'][0]):
                        distance = results['distances'][0][i]
                        memory.metadata['similarity'] = 1 - distance
                    memories.append(memory)
                return memories
        except Exception as e:
            logger.error(f"[VectorStorage] ChromaDB : {e}")
        return []
    async def _search_pgvector(self, query: str, limit: int,
                               user_id: Optional[str] = None,
                               session_id: Optional[str] = None,
                               workspace_id: Optional[str] = None) -> List[MemoryBlock]:
        try:
            results = await self._client.search(
                query=query,
                top_k=limit,
                similarity_threshold=self._similarity_threshold
            )
            memories = []
            for r in results:
                memory = MemoryBlock(
                    id=r.get('chunk_id', ''),
                    content=r.get('content', ''),
                    type='note',
                    metadata={'similarity': r.get('similarity', 0)}
                )
                memories.append(memory)
            return memories
        except Exception as e:
            logger.error(f"[VectorStorage] pgvector : {e}")
            return []
    async def _search_memory(self, query: str, limit: int,
                             user_id: Optional[str] = None,
                             session_id: Optional[str] = None,
                             workspace_id: Optional[str] = None) -> List[MemoryBlock]:
        import math
        query_embedding = await self._get_embedding(query)
        if not query_embedding:
            results = []
            query_lower = query.lower()
            for memory in self._fallback_store.values():
                if user_id and memory.user_id != user_id:
                    continue
                if session_id and memory.session_id != session_id:
                    continue
                if workspace_id and memory.workspace_id != workspace_id:
                    continue
                if query_lower in memory.content.lower():
                    results.append(memory)
            return results[:limit]
        def cosine_similarity(a: List[float], b: List[float]) -> float:
            dot_product = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            if norm_a == 0 or norm_b == 0:
                return 0
            return dot_product / (norm_a * norm_b)
        scored = []
        for memory_id, memory in self._fallback_store.items():
            if user_id and memory.user_id != user_id:
                continue
            if session_id and memory.session_id != session_id:
                continue
            if workspace_id and memory.workspace_id != workspace_id:
                continue
            embedding = self._fallback_embeddings.get(memory_id)
            if embedding:
                similarity = cosine_similarity(query_embedding, embedding)
                if similarity >= self._similarity_threshold:
                    memory.metadata['similarity'] = similarity
                    scored.append((similarity, memory))
            else:
                if query.lower() in memory.content.lower():
                    memory.metadata['similarity'] = 0.5
                    scored.append((0.5, memory))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:limit]]
    async def list_all(self, limit: int = 100, offset: int = 0) -> List[MemoryBlock]:
        await self._ensure_initialized()
        if self._backend == "chromadb" and self._collection:
            try:
                results = self._collection.get(
                    limit=limit,
                    offset=offset,
                    include=['metadatas']
                )
                if results and results.get('metadatas'):
                    return [
                        MemoryBlock.from_dict(self._deserialize_meta(meta))
                        for meta in results['metadatas']
                    ]
            except Exception as e:
                logger.error(f"[VectorStorage] ChromaDB : {e}")
        elif self._backend == "pgvector" and self._client:
            try:
                results = await self._client.get_all()
                memories = []
                for r in results[offset:offset + limit]:
                    memory = MemoryBlock(
                        id=r.get('chunk_id', ''),
                        content=r.get('content', ''),
                        type='note'
                    )
                    memories.append(memory)
                return memories
            except Exception as e:
                logger.error(f"[VectorStorage] pgvector : {e}")
        return list(self._fallback_store.values())[offset:offset + limit]
    async def clear(self) -> bool:
        await self._ensure_initialized()
        if self._backend == "chromadb" and self._client:
            try:
                self._client.delete_collection(self._collection_name)
                self._collection = self._client.get_or_create_collection(
                    name=self._collection_name,
                    metadata={"hnsw:space": "cosine"}
                )
                return True
            except Exception as e:
                logger.error(f"[VectorStorage] ChromaDB : {e}")
                return False
        elif self._backend == "pgvector" and self._client:
            try:
                await self._client.clear()
                return True
            except Exception as e:
                logger.error(f"[VectorStorage] pgvector : {e}")
                return False
        else:
            self._fallback_store.clear()
            self._fallback_embeddings.clear()
            return True
    async def get_stats(self) -> Dict[str, Any]:
        await self._ensure_initialized()
        stats = {
            "backend": self._backend,
            "collection_name": self._collection_name,
            "initialized": self._initialized
        }
        if self._backend == "chromadb" and self._collection:
            try:
                count = self._collection.count()
                stats["total_count"] = count
            except Exception:
                pass
        elif self._backend == "pgvector" and self._client:
            try:
                pg_stats = await self._client.get_stats()
                stats["total_count"] = pg_stats.get("total_chunks", 0)
            except Exception:
                pass
        else:
            stats["total_count"] = len(self._fallback_store)
        return stats
