"""短期记忆层（ShortTermMemory）：进程内 + TTL 过期 + 可选落盘。"""
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List
from loguru import logger
from ..blocks import MemoryBlock
from .base import MemoryTier


class ShortTermMemory(MemoryTier):
    def __init__(self, max_size: int = 1000, ttl_hours: int = 24, storage: Optional[Any] = None):
        super().__init__("short_term", max_size)
        self._session_memories: Dict[str, Dict[str, MemoryBlock]] = {}
        self._ttl_hours = ttl_hours
        self._lock = asyncio.Lock()
        self._storage = storage
        self._tier = "short_term"
    async def add(self, memory: MemoryBlock, session_id: Optional[str] = None) -> bool:
        session_id = session_id or memory.session_id or "default"
        async with self._lock:
            if session_id not in self._session_memories:
                self._session_memories[session_id] = {}
            await self._cleanup_session(session_id)
            self._session_memories[session_id][memory.id] = memory
        if self._storage is not None:
            try:
                await self._storage.save(memory, tier=self._tier)
            except Exception as e:
                logger.warning(f"[ShortTermMemory] 落盘失败 {memory.id}: {e}")
        return True
    async def _cleanup_session(self, session_id: str) -> None:
        if session_id not in self._session_memories:
            return
        cutoff_time = datetime.now() - timedelta(hours=self._ttl_hours)
        expired_ids = [
            mid for mid, mem in self._session_memories[session_id].items()
            if mem.last_accessed < cutoff_time
        ]
        for mid in expired_ids:
            del self._session_memories[session_id][mid]
        if expired_ids and self._storage is not None:
            for mid in expired_ids:
                try:
                    await self._storage.delete(mid)
                except Exception as e:
                    logger.warning(f"[ShortTermMemory] 过期落盘删除失败 {mid}: {e}")
        if expired_ids:
            logger.debug(f"[ShortTermMemory]  {session_id}  {len(expired_ids)} ")
    async def _cleanup_all_sessions(self) -> int:
        cutoff_time = datetime.now() - timedelta(hours=self._ttl_hours)
        expired_all: List[str] = []
        for session_id in list(self._session_memories.keys()):
            expired_ids = [
                mid for mid, mem in self._session_memories[session_id].items()
                if mem.last_accessed < cutoff_time
            ]
            for mid in expired_ids:
                del self._session_memories[session_id][mid]
                expired_all.append(mid)
            if session_id in self._session_memories and not self._session_memories[session_id]:
                del self._session_memories[session_id]
            if expired_ids:
                logger.debug(f"[ShortTermMemory]  {session_id}  {len(expired_ids)} ")
        if expired_all and self._storage is not None:
            for mid in expired_all:
                try:
                    await self._storage.delete(mid)
                except Exception as e:
                    logger.warning(f"[ShortTermMemory] 过期落盘删除失败 {mid}: {e}")
        return len(expired_all)
    async def cleanup_expired(self) -> int:
        """主动巡检清理所有 session 的 TTL 过期短期记忆（内存+SQLite）。

        供 decay trigger 定时调用，避免低活跃 session 过期记忆堆积。
        """
        return await self._cleanup_all_sessions()
    async def get(self, memory_id: str, session_id: Optional[str] = None) -> Optional[MemoryBlock]:
        async with self._lock:
            if session_id:
                session_data = self._session_memories.get(session_id, {})
                memory = session_data.get(memory_id)
                if memory:
                    if memory.last_accessed < datetime.now() - timedelta(hours=self._ttl_hours):
                        del session_data[memory_id]
                        if self._storage is not None:
                            try:
                                await self._storage.delete(memory_id)
                            except Exception:
                                pass
                        return None
                    memory.touch()
                return memory
            else:
                for session_data in self._session_memories.values():
                    if memory_id in session_data:
                        memory = session_data[memory_id]
                        if memory.last_accessed < datetime.now() - timedelta(hours=self._ttl_hours):
                            del session_data[memory_id]
                            if self._storage is not None:
                                try:
                                    await self._storage.delete(memory_id)
                                except Exception:
                                    pass
                            return None
                        memory.touch()
                        return memory
                return None
    async def search(
        self,
        query: str,
        limit: int = 10,
        session_id: Optional[str] = None
    ) -> List[MemoryBlock]:
        query_lower = query.lower()
        cutoff_time = datetime.now() - timedelta(hours=self._ttl_hours)
        async with self._lock:
            if session_id:
                session_data = self._session_memories.get(session_id, {})
                candidates = [
                    mem for mem in session_data.values()
                    if mem.last_accessed >= cutoff_time and
                       query_lower in mem.content.lower()
                ]
            else:
                candidates = []
                for session_data in self._session_memories.values():
                    for mem in session_data.values():
                        if mem.last_accessed >= cutoff_time and query_lower in mem.content.lower():
                            candidates.append(mem)
        candidates.sort(key=lambda m: m.get_combined_score(), reverse=True)
        return candidates[:limit]
    async def delete(self, memory_id: str, session_id: Optional[str] = None) -> bool:
        deleted = False
        async with self._lock:
            if session_id:
                session_data = self._session_memories.get(session_id, {})
                if memory_id in session_data:
                    del session_data[memory_id]
                    deleted = True
            else:
                for session_data in self._session_memories.values():
                    if memory_id in session_data:
                        del session_data[memory_id]
                        deleted = True
        if deleted and self._storage is not None:
            try:
                await self._storage.delete(memory_id)
            except Exception as e:
                logger.warning(f"[ShortTermMemory] 删除落盘失败 {memory_id}: {e}")
        return deleted
    async def clear(self) -> None:
        async with self._lock:
            self._session_memories.clear()
        if self._storage is not None:
            try:
                await self._storage.delete_by_tier(self._tier)
            except Exception as e:
                logger.warning(f"[ShortTermMemory] clear 落盘失败: {e}")
    async def get_all(self, session_id: Optional[str] = None) -> List[MemoryBlock]:
        cutoff_time = datetime.now() - timedelta(hours=self._ttl_hours)
        async with self._lock:
            if session_id:
                session_data = self._session_memories.get(session_id, {})
                return [mem for mem in session_data.values()
                        if mem.last_accessed >= cutoff_time]
            else:
                all_memories = []
                for session_data in self._session_memories.values():
                    all_memories.extend([
                        mem for mem in session_data.values()
                        if mem.last_accessed >= cutoff_time
                    ])
                return all_memories
    async def clear_session(self, session_id: str) -> int:
        count = 0
        async with self._lock:
            if session_id in self._session_memories:
                count = len(self._session_memories[session_id])
                del self._session_memories[session_id]
                logger.debug(f"[ShortTermMemory]  {session_id}  {count} ")
        if count and self._storage is not None:
            try:
                await self._storage.delete_by_session_and_tier(session_id, self._tier)
            except Exception as e:
                logger.warning(f"[ShortTermMemory] clear_session 落盘失败 {session_id}: {e}")
        return count
    async def update(self, memory: MemoryBlock) -> bool:
        """更新内存中的记忆并落盘。"""
        session_id = memory.session_id or "default"
        async with self._lock:
            if session_id not in self._session_memories:
                self._session_memories[session_id] = {}
            self._session_memories[session_id][memory.id] = memory
        if self._storage is not None:
            try:
                await self._storage.save(memory, tier=self._tier)
            except Exception as e:
                logger.warning(f"[ShortTermMemory] update 落盘失败 {memory.id}: {e}")
        return True
    async def load_from_storage(self) -> int:
        """从 SQLite 回灌到内存；TTL 已过期的不回灌。"""
        if self._storage is None:
            return 0
        try:
            stored = await self._storage.list_by_tier(self._tier, limit=100000)
        except Exception as e:
            logger.warning(f"[ShortTermMemory] 回灌读取失败: {e}")
            return 0
        cutoff_time = datetime.now() - timedelta(hours=self._ttl_hours)
        loaded = 0
        async with self._lock:
            for m in stored:
                if m.last_accessed < cutoff_time:
                    continue  # 过期不回灌
                sid = m.session_id or "default"
                if sid not in self._session_memories:
                    self._session_memories[sid] = {}
                self._session_memories[sid][m.id] = m
                loaded += 1
        logger.info(f"[ShortTermMemory] 回灌 {loaded} 条")
        return loaded
