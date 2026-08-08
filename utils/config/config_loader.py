import json
import os
import re
from typing import Dict, Any, Optional
from pathlib import Path
class ConfigLoader:
    def __init__(self, config_file: Optional[str] = None):
        if config_file is None:
            config_dir = os.getenv('AGENT_CONFIG_DIR')
            if config_dir:
                config_file = Path(config_dir) / "agent_config.json"
            else:
                agent_dir = Path(__file__).parent.parent.parent
                config_file = agent_dir / "config" / "agent_config.json"
        self.config_file = Path(config_file)
        self.config: Dict[str, Any] = {}
        self._load_config()
    def _load_config(self):
        if not self.config_file.exists():
            example_file = self.config_file.parent / f"{self.config_file.stem}.example{self.config_file.suffix}"
            if example_file.exists():
                print(f"配置文件不存在: {self.config_file}，请参考示例: {example_file}")
                self.config_file = example_file
            else:
                raise FileNotFoundError(f"配置文件不存在: {self.config_file}")
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            self.config = self._expand_env_vars(self.config)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"加载配置文件失败: {str(e)}")

    _ENV_PATTERN = re.compile(r'\$\{(\w+):([^}]*)\}')

    def _expand_env_vars(self, value: Any) -> Any:
        """递归解析 ${VAR:default} -> os.getenv(VAR) or default（env 空串也用 default）。"""
        if isinstance(value, str):
            def _repl(m):
                var, default = m.group(1), m.group(2)
                env_val = os.getenv(var)
                return env_val if env_val else default
            return self._ENV_PATTERN.sub(_repl, value)
        if isinstance(value, dict):
            return {k: self._expand_env_vars(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._expand_env_vars(v) for v in value]
        return value

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value if value is not None else default
    def get_section(self, section: str) -> Dict[str, Any]:
        return self.config.get(section, {})
    def reload(self):
        self._load_config()
    def validate(self) -> bool:
        required_sections = ['llm']
        for section in required_sections:
            if section not in self.config:
                raise ValueError(f"配置缺少必需段落: {section}")
        llm_config = self.config.get('llm', {})
        default_llm = llm_config.get('default', {})
        if not default_llm.get('base_url') or not default_llm.get('model'):
            raise ValueError("LLM: base_url  model")
        return True
_config_loader: Optional[ConfigLoader] = None
def get_config_loader(config_file: Optional[str] = None) -> ConfigLoader:
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader(config_file)
    return _config_loader
def _decrypt_if_needed(value: Any) -> Any:
    """对敏感配置值自动解密 enc: 密文；无 enc: 前缀原样返回（向下兼容）。

    用于 llm.default.api_key 等敏感字段：当 agent_config.json 里存的是 enc: 密文时
    自动解密为明文；明文（无 enc: 前缀）原样返回，保证旧配置不破坏。
    解密失败（主密钥未设/不匹配）返回原值，不抛异常。
    """
    if not value:
        return value
    try:
        from utils.crypto.secret_store import decrypt_secret
        return decrypt_secret(value)
    except Exception:
        return value


def get_config(key: str, default: Any = None) -> Any:
    if key == 'llm.default.api_key':
        env_api_key = os.getenv('OPENAI_API_KEY') or os.getenv('LLM_API_KEY') or os.getenv('API_KEY')
        if env_api_key:
            return _decrypt_if_needed(env_api_key)
        try:
            agent_dir = Path(__file__).parent.parent.parent
            config_py_path = agent_dir / "config.py"
            if config_py_path.exists():
                import importlib.util
                spec = importlib.util.spec_from_file_location("config", config_py_path)
                if spec and spec.loader:
                    config_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(config_module)
                    if hasattr(config_module, 'API_CONFIG') and isinstance(config_module.API_CONFIG, dict):
                        api_key = config_module.API_CONFIG.get('api_key')
                        if api_key and api_key.strip():
                            return _decrypt_if_needed(api_key)
        except Exception as e:
            pass
    value = get_config_loader().get(key, default)
    if key == 'llm.default.api_key':
        if not value:  # None 或空串
            return None
        return _decrypt_if_needed(value)
    return value


def get_agent_config(
    key: str,
    default: Any = None,
    agent_id: int | None = None,
    workspace_id: int | None = None,
) -> Any:
    """三级优先级读取 Agent 执行配置。

    1. Agent 级 `tb_agent.agent_config` (JSON)
    2. 工作空间级 `tb_workspace.config` (JSON)
    3. 全局 `agent_config.json`

    agent_id / workspace_id 为 None 时跳过对应层。
    """
    import json as _json

    def _deep_get(d: dict, dot_key: str):
        keys = dot_key.split(".")
        for k in keys:
            if isinstance(d, dict):
                d = d.get(k)
                if d is None:
                    return None
            else:
                return None
        return d

    # 1. Agent 级（读生效配置：已发布版本快照优先，使委派开关等也走已发布版本）
    if agent_id is not None:
        try:
            from utils.config import get_config_db
            agent = get_config_db().get_effective_agent(str(agent_id))
            if agent and agent.get("agent_config"):
                cfg = _json.loads(agent["agent_config"])
                val = _deep_get(cfg, key)
                if val is not None:
                    return val
        except Exception:
            pass

    # 2. 工作空间级
    if workspace_id is not None:
        try:
            from infrastructure.database.repositories.workspace_repository import WorkspaceRepository
            repo = WorkspaceRepository()
            ws = repo.get_by_id(workspace_id)
            if ws and ws.get("config"):
                cfg = _json.loads(ws["config"])
                val = _deep_get(cfg, key)
                if val is not None:
                    return val
        except Exception:
            pass

    # 3. 全局默认
    return get_config(key, default)
