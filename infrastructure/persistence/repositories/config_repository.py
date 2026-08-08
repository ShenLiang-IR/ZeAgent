from loguru import logger
from typing import Dict, Any, List
from ...database.repositories import SubAgentRepository, ModeRepository, ExternalToolRepository


class ConfigRepository:
    def __init__(self):
        self._subagent_repo = SubAgentRepository()
        self._mode_repo = ModeRepository()
        self._external_tool_repo = ExternalToolRepository()
    def get_all_subagents(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        try:
            return self._subagent_repo.get_all(enabled_only=enabled_only)
        except Exception as e:
            logger.error(f"SubAgent: {str(e)}", exc_info=True)
            return []
    def get_all_modes(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        try:
            return self._mode_repo.get_all(enabled_only=enabled_only)
        except Exception as e:
            logger.error(f"配置仓储操作失败: {e}", exc_info=True)
            return []
    def get_all_external_tools(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        try:
            return self._external_tool_repo.get_all(enabled_only=enabled_only)
        except Exception as e:
            logger.error(f"配置仓储操作失败: {e}", exc_info=True)
            return []