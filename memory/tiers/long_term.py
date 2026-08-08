"""长期记忆层（LongTermMemory）：SQLite 持久化 + 可选向量检索（chromadb/pgvector）。"""
import threading
from typing import Any, Dict, Optional, List
from loguru import logger
from ..blocks import MemoryBlock
from .base import MemoryTier


class LongTermMemory(MemoryTier):
    def __init__(
        self,
        max_size: int = 10000,
        storage_backend: str = "sqlite",
        vector_backend: Optional[str] = None,
        vector_config: Optional[Dict[str, Any]] = None,
        storage: Optional[Any] = None,
    ):
        super().__init__("long_term", max_size)
        self._lock = threading.RLock()
        self._vector_backend = vector_backend
        self._vector_config = vector_config or {}
        if storage is not None:
            self._storage = storage
            logger.info("[LongTermMemory] 注入共享 SQLiteStorage")
        elif storage_backend == "sqlite":
            from ..storage import SQLiteStorage
            self._storage = SQLiteStorage(db_path="data/memory.db")
            logger.info("[LongTermMemory]  SQLite ")
        else:
            from ..storage import InMemoryStorage
            self._storage = InMemoryStorage(max_size=max_size)
            logger.info("[LongTermMemory] ")
        self._tier = "long_term"
        self._vector_storage: Optional[Any] = None
        self._vector_initialized = False
    async def _ensure_vector_storage(self) -> Optional[Any]:
        if self._vector_initialized:
            return self._vector_storage
        self._vector_initialized = True
        if not self._vector_backend:
            return None
        try:
            from ..storage import VectorStorage
            if self._vector_backend == "chromadb":
                self._vector_storage = VectorStorage(
                    backend="chromadb",
                    collection_name=self._vector_config.get("collection_name", "agent_memories"),
                    persist_directory=self._vector_config.get("persist_directory", "data/chroma")
                )
                logger.info("[LongTermMemory] ChromaDB ")
            elif self._vector_backend == "pgvector":
                self._vector_storage = VectorStorage(
                    backend="pgvector",
                    knowledge_base_id=self._vector_config.get("knowledge_base_id", "agent_memory"),
                    similarity_threshold=self._vector_config.get("similarity_threshold", 0.7)
                )
                logger.info("[LongTermMemory] pgvector ")
            else:
                logger.warning(f"[LongTermMemory] : {self._vector_backend}")
        except Exception as e:
            logger.warning(f"[LongTermMemory] : {e}")
            self._vector_storage = None
        return self._vector_storage
    def set_vector_client(self, client: Any) -> None:
        self._vector_storage = client
        self._vector_initialized = True
    async def add(self, memory: MemoryBlock) -> bool:
        result = await self._storage.save(memory, tier=self._tier)
        if result and self._vector_backend:
            vector_storage = await self._ensure_vector_storage()
            if vector_storage:
                try:
                    await vector_storage.save(memory)
                    logger.debug(f"[LongTermMemory] : {memory.id}")
                except Exception as e:
                    logger.warning(f"[LongTermMemory] : {e}")
        return result
    async def get(self, memory_id: str) -> Optional[MemoryBlock]:
        memory = await self._storage.load(memory_id)
        if memory:
            memory.touch()
        return memory
    async def search(
        self,
        query: str,
        limit: int = 10,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None
    ) -> List[MemoryBlock]:
        results = []
        seen_ids = set()
        if self._vector_backend:
            vector_storage = await self._ensure_vector_storage()
            if vector_storage:
                try:
                    vector_results = await vector_storage.search(query, limit, user_id=user_id, session_id=session_id, workspace_id=workspace_id)
                    for memory in vector_results:
                        # user_id 优先（跨 session 按 user），其次 session_id
                        if user_id and memory.user_id != user_id:
                            continue
                        elif session_id and memory.session_id != session_id:
                            continue
                        if memory.id not in seen_ids:
                            results.append(memory)
                            seen_ids.add(memory.id)
                    logger.debug(
                        f"[LongTermMemory]  {len(vector_results)} "
                    )
                except Exception as e:
                    logger.warning(f"[LongTermMemory] : {e}")
        if len(results) < limit:
            keyword_results = await self._storage.search(query, limit, tier=self._tier, workspace_id=workspace_id)
            for memory in keyword_results:
                if user_id and memory.user_id != user_id:
                    continue
                elif session_id and memory.session_id != session_id:
                    continue
                if memory.id not in seen_ids:
                    results.append(memory)
                    seen_ids.add(memory.id)
        results.sort(key=lambda m: m.get_final_recall_score(0.15), reverse=True)
        return results[:limit]
    async def delete(self, memory_id: str) -> bool:
        result = await self._storage.delete(memory_id)
        if result and self._vector_backend:
            vector_storage = await self._ensure_vector_storage()
            if vector_storage:
                try:
                    await vector_storage.delete(memory_id)
                except Exception as e:
                    logger.warning(f"[LongTermMemory] : {e}")
        return result
    async def update(self, memory: MemoryBlock) -> bool:
        """更新已有记忆内容并重嵌（SQLite INSERT OR REPLACE + 向量层 delete-then-add）。"""
        result = await self._storage.save(memory, tier=self._tier)
        if result and self._vector_backend:
            vector_storage = await self._ensure_vector_storage()
            if vector_storage:
                try:
                    await vector_storage.delete(memory.id)
                    await vector_storage.save(memory)
                    logger.debug(f"[LongTermMemory] update 重嵌: {memory.id}")
                except Exception as e:
                    logger.warning(f"[LongTermMemory] update 向量重嵌失败: {e}")
        return result
    async def clear(self) -> None:
        if hasattr(self._storage, 'delete_by_tier'):
            await self._storage.delete_by_tier(self._tier)
        else:
            await self._storage.clear()
        if self._vector_backend:
            vector_storage = await self._ensure_vector_storage()
            if vector_storage:
                try:
                    await vector_storage.clear()
                except Exception as e:
                    logger.warning(f"[LongTermMemory] : {e}")
    async def delete_by_session(self, session_id: str) -> int:
        if hasattr(self._storage, 'delete_by_session'):
            deleted = await self._storage.delete_by_session(session_id)
            logger.info(f"[LongTermMemory]  SQLite  {deleted} : {session_id}")
            return deleted
        else:
            deleted_count = 0
            memories = await self.get_all()
            normalized = session_id.replace('-', '') if session_id else ''
            for memory in memories:
                memory_session = (memory.session_id or '').replace('-', '')
                if memory_session == normalized:
                    await self.delete(memory.id)
                    deleted_count += 1
            return deleted_count
    async def delete_by_user(self, user_id: str) -> int:
        if hasattr(self._storage, 'delete_by_user'):
            deleted = await self._storage.delete_by_user(user_id)
            logger.info(f"[LongTermMemory]  SQLite  {deleted} : {user_id}")
            return deleted
        else:
            deleted_count = 0
            memories = await self.get_all()
            for memory in memories:
                if memory.user_id == user_id:
                    await self.delete(memory.id)
                    deleted_count += 1
            return deleted_count
    async def get_all(self, session_id: Optional[str] = None) -> List[MemoryBlock]:
        all_memories = await self._storage.list_by_tier(self._tier, limit=10000)
        if session_id:
            normalized = session_id.replace('-', '')
            return [m for m in all_memories
                    if (m.session_id or '').replace('-', '') == normalized]
        return all_memories
    async def get_stats(self) -> Dict[str, Any]:
        # 用 COUNT 聚合而非 list 全量，避免大库 OOM/慢
        try:
            total_count = await self._storage.count_by_tier(self._tier)
        except Exception:
            total_count = len(await self.get_all())
        stats = {
            "storage_backend": "sqlite" if "SQLiteStorage" in str(type(self._storage)) else "memory",
            "vector_backend": self._vector_backend,
            "total_count": total_count
        }
        if self._vector_storage:
            try:
                vector_stats = await self._vector_storage.get_stats()
                stats["vector_stats"] = vector_stats
            except Exception:
                pass
        return stats
