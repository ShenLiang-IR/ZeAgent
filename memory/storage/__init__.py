"""记忆存储层（memory/storage 包）。

按 backend 拆分：
- base.py: StorageBackend Protocol（接口契约）
- in_memory.py: InMemoryStorage（进程内 LRU）
- sqlite.py: SQLiteStorage（持久化 + 审计）
- vector.py: VectorStorage（chromadb / pgvector 向量检索）
- factory.py: StorageFactory（按 type 创建实例）

向后兼容：`from memory.storage import X` 仍可用（本 __init__ re-export 全部公共符号）。
原 memory/storage.py 单文件已拆为本包，旧 import 路径不变。
"""
from .base import StorageBackend
from .in_memory import InMemoryStorage
from .sqlite import SQLiteStorage
from .vector import VectorStorage
from .factory import StorageFactory

__all__ = [
    "StorageBackend",
    "InMemoryStorage",
    "SQLiteStorage",
    "VectorStorage",
    "StorageFactory",
]
