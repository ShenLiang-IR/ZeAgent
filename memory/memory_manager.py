"""记忆系统管理器（已拆分到 memory/tiers/ + memory/manager.py）。

本文件保留为 re-export 桥接，保 `from memory.memory_manager import X` 旧路径兼容。
原 1331 行单文件已按职责拆为：
- memory/tiers/base.py        MemoryTier 基类
- memory/tiers/immediate.py   ImmediateMemory 瞬时层
- memory/tiers/short_term.py  ShortTermMemory 短期层
- memory/tiers/long_term.py   LongTermMemory 长期层
- memory/manager.py           MemoryManager 编排 + get/reset 工厂

新代码建议直接用 memory.tiers / memory.manager 路径。
"""
from .tiers import MemoryTier, ImmediateMemory, ShortTermMemory, LongTermMemory
from .manager import MemoryManager, get_memory_manager, reset_memory_manager

__all__ = [
    "MemoryTier",
    "ImmediateMemory",
    "ShortTermMemory",
    "LongTermMemory",
    "MemoryManager",
    "get_memory_manager",
    "reset_memory_manager",
]
