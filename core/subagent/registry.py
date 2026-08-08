from typing import Dict, List, Optional, Any
from pathlib import Path
from loguru import logger
from .base import BaseSubAgent
from utils.common.cache import TTLCacheMixin
class SubAgentRegistry(TTLCacheMixin):
    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            agent_dir = Path(__file__).parent.parent
            config_dir = agent_dir / "config" / "subagents"
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._subagents: Dict[str, BaseSubAgent] = {}
        self._load_subagents()
    def _load_subagents(self):
        try:
            from utils.config import get_config_db
            config_db = get_config_db()
            # 读生效配置（已发布版本快照优先），使 agent 间委派也走已发布版本
            subagent_configs = config_db.get_all_effective_agents(enabled_only=True)
            for config in subagent_configs:
                try:
                    full_config = {
                        'name': config['agent_name'],
                        'description': config.get('agent_description', ''),
                        'system_prompt': config.get('system_prompt', ''),
                        'tools': config.get('tools', []),
                        'external_tools': config.get('external_tools', []),
                        'model': config.get('model_id'),
                        'mcp_tools': config.get('mcp_tools', [])
                    }
                    subagent = BaseSubAgent(
                        name=config['agent_name'],
                        description=config.get('agent_description', ''),
                        config=full_config
                    )
                    self._subagents[config['agent_name']] = subagent
                except Exception as e:
                    logger.error(f"SubAgent {config.get('agent_name', 'unknown')}: {str(e)}", exc_info=True)
            self._mark_loaded()
        except Exception as e:
            pass
    def register(self, subagent: BaseSubAgent, name: Optional[str] = None):
        agent_name = name or subagent.name
        self._subagents[agent_name] = subagent
    def _clear_cache(self) -> None:
        self._subagents.clear()
    def _ensure_loaded(self) -> None:
        if not self._subagents:
            self._load_subagents()
    def get(self, name: str) -> Optional[BaseSubAgent]:
        self._invalidate_if_expired()
        self._ensure_loaded()
        return self._subagents.get(name)
    def get_all(self) -> List[BaseSubAgent]:
        self._invalidate_if_expired()
        self._ensure_loaded()
        return list(self._subagents.values())
    def get_agent_configs(self) -> List[Dict[str, Any]]:
        self._invalidate_if_expired()
        self._ensure_loaded()
        return [subagent.to_agent_config() for subagent in self._subagents.values()]
    def reload(self):
        self._subagents.clear()
        self._load_subagents()
_subagent_registry: Optional[SubAgentRegistry] = None
def get_subagent_registry(config_dir: Optional[Path] = None) -> SubAgentRegistry:
    global _subagent_registry
    if _subagent_registry is None:
        _subagent_registry = SubAgentRegistry(config_dir)
    return _subagent_registry