"""Langfuse 配置加载器（从 agent_config.json 的 observability.langfuse 段读取）。

原 langfuse.json 已合并到 agent_config.json 的 observability.langfuse 段。
"""
import time
from typing import Dict, Any, Optional
from .config_loader import get_config_loader

_langfuse_config_cache: Optional[Dict[str, Any]] = None
_langfuse_config_cache_time: Optional[float] = None


def load_langfuse_config_file(force_reload: bool = False) -> Optional[Dict[str, Any]]:
    """加载 langfuse 配置段（从 agent_config.json 读取，带缓存）。

    返回格式与原 langfuse.json 一致：{"langfuse": {...}}
    """
    global _langfuse_config_cache, _langfuse_config_cache_time
    if not force_reload and _langfuse_config_cache is not None:
        return _langfuse_config_cache
    loader = get_config_loader()
    if force_reload:
        loader.reload()
    lf_config = loader.get("observability.langfuse", {})
    if lf_config:
        _langfuse_config_cache = {"langfuse": lf_config}
        _langfuse_config_cache_time = time.time()
        return _langfuse_config_cache
    return None


def get_langfuse_config() -> Dict[str, Any]:
    """返回 langfuse 配置段（enabled/public_key/secret_key/host/self_hosted）。"""
    lf_file = load_langfuse_config_file()
    if lf_file and 'langfuse' in lf_file:
        return lf_file['langfuse']
    # fallback：直接从 config 读取
    from .config_loader import get_config
    return {
        'enabled': get_config("observability.langfuse.enabled", False),
        'public_key': get_config("observability.langfuse.public_key", ""),
        'secret_key': get_config("observability.langfuse.secret_key", ""),
        'host': get_config("observability.langfuse.host", ""),
        'self_hosted': get_config("observability.langfuse.self_hosted", True),
    }
