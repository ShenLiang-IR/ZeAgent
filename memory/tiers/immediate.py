"""瞬时记忆层（ImmediateMemory）：进程内 LRU + 可选落盘回灌。"""
import asyncio
from collections import OrderedDict
from typing import Any, Dict, Optional, List
from loguru import logger
from ..blocks import MemoryBlock
from .base import MemoryTier


class ImmediateMemory(MemoryTier):
    def __init__(self, max_size: int = 100, max_sessions: int = 50, storage: Optional[Any] = None):
        super().__init__("immediate", max_size)
        self._session_caches: Dict[str, "OrderedDict[str, MemoryBlock]"] = {}
        self._max_sessions = max_sessions
        self._session_lru: OrderedDict[str, None] = OrderedDict()
        self._lock = asyncio.Lock()
        self._storage = storage  # 可选 SQLiteStorage，落盘后重启可回灌
        self._tier = "immediate"
    def _ensure_session_capacity(self) -> None:
        while len(self._session_caches) >= self._max_sessions:
            oldest_session, _ = self._session_lru.popitem(last=False)
            evicted = self._session_caches.pop(oldest_session, None)
            if evicted and self._storage is not None:
                asyncio.ensure_future(self._evict_from_storage(list(evicted.keys())))
            logger.debug(f"[ImmediateMemory] : {oldest_session}")
    async def _evict_from_storage(self, ids: List[str]) -> None:
        for mid in ids:
            try:
                if self._storage is not None:
                    await self._storage.delete(mid)
            except Exception as e:
                logger.warning(f"[ImmediateMemory] 淘汰落盘删除失败 {mid}: {e}")
    async def add(self, memory: MemoryBlock, session_id: Optional[str] = None) -> bool:
        session_id = session_id or memory.session_id or "default"
        async with self._lock:
            if session_id not in self._session_caches:
                self._ensure_session_capacity()
                self._session_caches[session_id] = OrderedDict()
            cache = self._session_caches[session_id]
            if memory.id in cache:
                cache.move_to_end(memory.id)
            else:
                while len(cache) >= self.max_size:
                    evicted_id, _ = cache.popitem(last=False)
                    if self._storage is not None:
                        await self._storage.delete(evicted_id)
                cache[memory.id] = memory
            if session_id in self._session_lru:
                self._session_lru.move_to_end(session_id)
            else:
                self._session_lru[session_id] = None
        if self._storage is not None:
            try:
                await self._storage.save(memory, tier=self._tier)
            except Exception as e:
                logger.warning(f"[ImmediateMemory] 落盘失败 {memory.id}: {e}")
        return True
    async def get(self, memory_id: str, session_id: Optional[str] = None) -> Optional[MemoryBlock]:
        async with self._lock:
            if session_id:
                cache = self._session_caches.get(session_id, {})
                memory = cache.get(memory_id)
                if memory:
                    memory.touch()
                    cache.move_to_end(memory_id)
                return memory
            else:
                for cache in self._session_caches.values():
                    if memory_id in cache:
                        memory = cache[memory_id]
                        memory.touch()
                        cache.move_to_end(memory_id)
                        return memory
                return None
    async def search(
        self,
        query: str,
        limit: int = 10,
        session_id: Optional[str] = None
    ) -> List[MemoryBlock]:
        results = []
        query_lower = query.lower()
        async with self._lock:
            if session_id:
                cache = self._session_caches.get(session_id, OrderedDict())
                for memory in reversed(cache.values()):
                    if query_lower in memory.content.lower():
                        results.append(memory)
                        if len(results) >= limit:
                            break
            else:
                for session_cache in self._session_caches.values():
                    for memory in reversed(session_cache.values()):
                        if query_lower in memory.content.lower():
                            results.append(memory)
                            if len(results) >= limit:
                                break
                    if len(results) >= limit:
                        break
        return results
    async def delete(self, memory_id: str, session_id: Optional[str] = None) -> bool:
        deleted = False
        async with self._lock:
            if session_id:
                cache = self._session_caches.get(session_id, {})
                if memory_id in cache:
                    del cache[memory_id]
                    deleted = True
            else:
                for cache in self._session_caches.values():
                    if memory_id in cache:
                        del cache[memory_id]
                        deleted = True
        if deleted and self._storage is not None:
            try:
                await self._storage.delete(memory_id)
            except Exception as e:
                logger.warning(f"[ImmediateMemory] 删除落盘失败 {memory_id}: {e}")
        return deleted
    async def clear(self) -> None:
        async with self._lock:
            self._session_caches.clear()
            self._session_lru.clear()
        if self._storage is not None:
            try:
                await self._storage.delete_by_tier(self._tier)
            except Exception as e:
                logger.warning(f"[ImmediateMemory] clear 落盘失败: {e}")
    async def get_all(self, session_id: Optional[str] = None) -> List[MemoryBlock]:
        async with self._lock:
            if session_id:
                cache = self._session_caches.get(session_id, OrderedDict())
                return list(reversed(cache.values()))
            else:
                all_memories = []
                for session_cache in self._session_caches.values():
                    all_memories.extend(session_cache.values())
                return list(reversed(all_memories))
    async def clear_session(self, session_id: str) -> int:
        count = 0
        ids_to_drop: List[str] = []
        async with self._lock:
            if session_id in self._session_caches:
                ids_to_drop = list(self._session_caches[session_id].keys())
                count = len(ids_to_drop)
                del self._session_caches[session_id]
                self._session_lru.pop(session_id, None)
                logger.debug(f"[ImmediateMemory]  {session_id}  {count} ")
        if ids_to_drop and self._storage is not None:
            try:
                await self._storage.delete_by_session_and_tier(session_id, self._tier)
            except Exception as e:
                logger.warning(f"[ImmediateMemory] clear_session 落盘失败 {session_id}: {e}")
        return count
    async def update(self, memory: MemoryBlock) -> bool:
        """更新内存中的记忆并落盘（INSERT OR REPLACE）。"""
        session_id = memory.session_id or "default"
        async with self._lock:
            cache = self._session_caches.get(session_id, OrderedDict())
            if memory.id in cache:
                cache[memory.id] = memory
                cache.move_to_end(memory.id)
            else:
                cache[memory.id] = memory
        if self._storage is not None:
            try:
                await self._storage.save(memory, tier=self._tier)
            except Exception as e:
                logger.warning(f"[ImmediateMemory] update 落盘失败 {memory.id}: {e}")
        return True
    async def load_from_storage(self) -> int:
        """从 SQLite 回灌到内存（按 created_at 升序，超 max_size 的淘汰并删盘）。"""
        if self._storage is None:
            return 0
        try:
            stored = await self._storage.list_by_tier(self._tier, limit=100000)
        except Exception as e:
            logger.warning(f"[ImmediateMemory] 回灌读取失败: {e}")
            return 0
        stored.sort(key=lambda m: m.created_at, reverse=True)
        loaded = 0
        async with self._lock:
            for m in stored:
                sid = m.session_id or "default"
                if sid not in self._session_caches:
                    if len(self._session_caches) >= self._max_sessions:
                        break
                    self._session_caches[sid] = OrderedDict()
                    self._session_lru[sid] = None
                cache = self._session_caches[sid]
                if len(cache) >= self.max_size:
                    continue
                cache[m.id] = m
                loaded += 1
        logger.info(f"[ImmediateMemory] 回灌 {loaded} 条")
        return loaded
