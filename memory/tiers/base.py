"""记忆层级基类（MemoryTier）。"""
from typing import Optional, List
from ..blocks import MemoryBlock


class MemoryTier:
    def __init__(self, name: str, max_size: int = 1000):
        self.name = name
        self.max_size = max_size
    async def add(self, memory: MemoryBlock) -> bool:
        raise NotImplementedError
    async def get(self, memory_id: str) -> Optional[MemoryBlock]:
        raise NotImplementedError
    async def search(self, query: str, limit: int = 10) -> List[MemoryBlock]:
        raise NotImplementedError
    async def delete(self, memory_id: str) -> bool:
        raise NotImplementedError
    async def clear(self) -> None:
        raise NotImplementedError
    async def get_all(self) -> List[MemoryBlock]:
        raise NotImplementedError
