from typing import Any, Dict
from loguru import logger
from .base import StorageBackend
from .in_memory import InMemoryStorage
from .sqlite import SQLiteStorage
from .vector import VectorStorage


class StorageFactory:
    @staticmethod
    def create(storage_type: str, **kwargs) -> StorageBackend:
        if storage_type == "memory":
            return InMemoryStorage(**kwargs)
        elif storage_type == "sqlite":
            return SQLiteStorage(**kwargs)
        elif storage_type in ("vector", "chromadb"):
            return VectorStorage(backend="chromadb", **kwargs)
        elif storage_type == "pgvector":
            return VectorStorage(backend="pgvector", **kwargs)
        else:
            logger.warning(f"未知的向量存储类型，降级 InMemory: {storage_type}")
            return InMemoryStorage()

    @staticmethod
    def create_from_config(config: Dict[str, Any]) -> StorageBackend:
        storage_type = config.get("type", "memory")
        params = {k: v for k, v in config.items() if k != "type"}
        return StorageFactory.create(storage_type, **params)
