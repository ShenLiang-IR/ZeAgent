import time
from typing import Dict, List, Optional
from loguru import logger
from .base_extractor import (
    TableInfo,
    MetadataCacheEntry,
)
class MetadataCache:
    _instance = None
    _cache: Dict[str, MetadataCacheEntry] = {}
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    @classmethod
    def get_instance(cls) -> "MetadataCache":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    def _make_key(self, db_name: str, schema: str = "") -> str:
        if schema:
            return f"{db_name}:{schema}"
        return db_name
    def get_tables(self, db_name: str, schema: str = "") -> Optional[List[TableInfo]]:
        key = self._make_key(db_name, schema)
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.is_expired():
            logger.debug(f"[MetadataCache] : {key}")
            del self._cache[key]
            return None
        logger.debug(f"[MetadataCache] : {key}")
        return entry.tables
    def set_tables(
        self,
        db_name: str,
        tables: List[TableInfo],
        ttl_seconds: int = 3600,
        schema: str = ""
    ) -> None:
        key = self._make_key(db_name, schema)
        self._cache[key] = MetadataCacheEntry(
            tables=tables,
            timestamp=time.time(),
            ttl_seconds=ttl_seconds
        )
        logger.debug(f"[MetadataCache] : {key}, ={len(tables)}, TTL={ttl_seconds}s")
    def get_table_info(self, db_name: str, table_name: str, schema: str = "") -> Optional[TableInfo]:
        tables = self.get_tables(db_name, schema)
        if tables is None:
            return None
        for table in tables:
            if table.table_name == table_name:
                return table
        return None
    def invalidate(self, db_name: str, schema: str = "") -> None:
        key = self._make_key(db_name, schema)
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"[MetadataCache] : {key}")
    def clear_all(self) -> None:
        count = len(self._cache)
        self._cache.clear()
        logger.debug(f"[MetadataCache]  {count} ")
    def get_cache_stats(self) -> Dict[str, any]:
        stats = {
            "total_entries": len(self._cache),
            "entries": []
        }
        for key, entry in self._cache.items():
            remaining_ttl = entry.ttl_seconds - (time.time() - entry.timestamp)
            stats["entries"].append({
                "key": key,
                "table_count": len(entry.tables),
                "remaining_ttl_seconds": max(0, remaining_ttl)
            })
        return stats
_global_cache: Optional[MetadataCache] = None
def get_metadata_cache() -> MetadataCache:
    global _global_cache
    if _global_cache is None:
        _global_cache = MetadataCache()
    return _global_cache