import asyncio
from typing import Dict, Optional, List
from ..blocks import MemoryBlock


class InMemoryStorage:
    def __init__(self, max_size: int = 10000):
        self._store: Dict[str, MemoryBlock] = {}
        self._max_size = max_size
        self._lock = asyncio.Lock()
    async def save(self, memory: MemoryBlock, tier: str = "long_term") -> bool:
        async with self._lock:
            if len(self._store) >= self._max_size and memory.id not in self._store:
                oldest_id = min(
                    self._store.keys(),
                    key=lambda k: self._store[k].created_at
                )
                del self._store[oldest_id]
            self._store[memory.id] = memory
            return True
    async def load(self, memory_id: str) -> Optional[MemoryBlock]:
        async with self._lock:
            return self._store.get(memory_id)
    async def delete(self, memory_id: str) -> bool:
        async with self._lock:
            if memory_id in self._store:
                del self._store[memory_id]
                return True
            return False
    async def search(self, query: str, limit: int = 10, tier: Optional[str] = None,
                     workspace_id: Optional[str] = None) -> List[MemoryBlock]:
        results = []
        query_lower = query.lower()
        async with self._lock:
            for memory in self._store.values():
                if workspace_id and memory.workspace_id != workspace_id:
                    continue
                if query_lower in memory.content.lower():
                    results.append(memory)
        results.sort(key=lambda m: m.get_combined_score(), reverse=True)
        return results[:limit]
    async def list_all(self, limit: int = 100, offset: int = 0, tier: Optional[str] = None) -> List[MemoryBlock]:
        async with self._lock:
            all_memories = list(self._store.values())
            all_memories.sort(key=lambda m: m.created_at, reverse=True)
            return all_memories[offset:offset + limit]
    async def list_by_tier(self, tier: str, limit: int = 10000, offset: int = 0) -> List[MemoryBlock]:
        return await self.list_all(limit=limit, offset=offset, tier=tier)
    async def delete_by_tier(self, tier: str) -> int:
        # InMemoryStorage 不区分 tier，清空全部（通常单实例单 tier 使用）
        async with self._lock:
            n = len(self._store)
            self._store.clear()
            return n
    async def count_by_tier(self, tier: str) -> int:
        async with self._lock:
            return len(self._store)
    async def delete_by_session_and_tier(self, session_id: str, tier: str) -> int:
        async with self._lock:
            to_del = [mid for mid, m in self._store.items() if m.session_id == session_id]
            for mid in to_del:
                del self._store[mid]
            return len(to_del)
    async def delete_by_user_and_tier(self, user_id: str, tier: str) -> int:
        async with self._lock:
            to_del = [mid for mid, m in self._store.items() if m.user_id == user_id]
            for mid in to_del:
                del self._store[mid]
            return len(to_del)
    async def clear(self) -> bool:
        async with self._lock:
            self._store.clear()
            return True
    async def count(self) -> int:
        async with self._lock:
            return len(self._store)
