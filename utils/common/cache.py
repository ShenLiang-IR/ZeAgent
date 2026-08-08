import time
from typing import Dict, Any, Optional, Callable
from threading import Lock
class SimpleCache:
    def __init__(self, default_ttl: int = 300):
        self._cache: Dict[str, tuple] = {}
        self._lock = Lock()
        self.default_ttl = default_ttl
    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                return None
            value, expire_time = self._cache[key]
            if time.time() > expire_time:
                del self._cache[key]
                return None
            return value
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        with self._lock:
            expire_time = time.time() + (ttl if ttl is not None else self.default_ttl)
            self._cache[key] = (value, expire_time)
    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    def clear(self):
        with self._lock:
            self._cache.clear()
    def clear_expired(self):
        with self._lock:
            now = time.time()
            expired_keys = [
                key for key, (_, expire_time) in self._cache.items()
                if now > expire_time
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)
    def size(self) -> int:
        with self._lock:
            return len(self._cache)
    def get_or_set(self, key: str, func: Callable[[], Any], ttl: Optional[int] = None) -> Any:
        value = self.get(key)
        if value is not None:
            return value
        value = func()
        self.set(key, value, ttl)
        return value
_query_cache = SimpleCache(default_ttl=300)
def get_query_cache() -> SimpleCache:
    return _query_cache
def clear_query_cache():
    _query_cache.clear()
def cache_result(key: str, ttl: Optional[int] = None):
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            cache_key = key
            if args or kwargs:
                try:
                    cache_key = key.format(*args, **kwargs)
                except (KeyError, IndexError):
                    pass
            cached = _query_cache.get(cache_key)
            if cached is not None:
                return cached
            result = func(*args, **kwargs)
            if result is not None:
                _query_cache.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator
from loguru import logger
class TTLCacheMixin:
    _ttl_seconds: int = 100
    _last_loaded: float = 0.0
    _is_refreshing: bool = False
    def _is_cache_expired(self) -> bool:
        return time.time() - self._last_loaded > self._ttl_seconds
    def _mark_loaded(self):
        self._last_loaded = time.time()
    def _invalidate_if_expired(self):
        if not self._is_cache_expired() or self._is_refreshing:
            return
        try:
            self._is_refreshing = True
            logger.debug(f"[{self.__class__.__name__}] ")
            self._clear_cache()
        finally:
            self._is_refreshing = False
    def _clear_cache(self):
        raise NotImplementedError