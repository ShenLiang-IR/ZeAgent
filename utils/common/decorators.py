"""通用装饰器 — 统一错误处理

从 150 处 try-except+logger.error+return 模式抽取。
支持同步和异步方法。
"""
import asyncio
import functools
from loguru import logger


def handle_db_errors(tag: str, default=None):
    """统一 DB 错误处理装饰器（支持同步和异步方法）。

    捕获 Exception → logger.error(exc_info=True) → 返回 default。

    用法:
        @handle_db_errors("MCP", default=False)
        def save_mcp(self, ...) -> bool:
            ...  # 不需要 try-except
            return True
    """
    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"[{tag}] {func.__name__} failed: {e}", exc_info=True)
                    return default
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"[{tag}] {func.__name__} failed: {e}", exc_info=True)
                    return default
            return sync_wrapper
    return decorator
