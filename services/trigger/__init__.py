"""services/trigger 包：统一抽象 + 3 个具体触发器 + Registry。

设计参见 docs/specs/2026-07-19-trigger-registry-design.md §6 服务层。

加载顺序说明：本包在 services 包下，加载时先触发 services/__init__.py
(from .agent_service import AgentService)，进而触发 utils.message 加载，
打破 utils 与 infrastructure.database.repositories.chat_repository 的循环 import。
"""
