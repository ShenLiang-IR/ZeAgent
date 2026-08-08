"""数据库配置加载器（从 agent_config.json 的 database 段读取）。

原 db_config.json 已合并到 agent_config.json 的 database 段。
本模块保持原有函数签名不变，内部改为从 get_config_loader 读取。
"""
import time
from typing import Dict, Any, Optional
from .config_loader import get_config_loader

_db_config_cache: Optional[Dict[str, Any]] = None
_db_config_cache_time: Optional[float] = None


def load_db_config_file(force_reload: bool = False) -> Optional[Dict[str, Any]]:
    """加载 database 配置段（从 agent_config.json 读取，带缓存）。

    原从 db_config.json 读取，现从 agent_config.json 的 database 段读取。
    返回格式与原 db_config.json 一致：{config: {...}, chat: {...}, ...}
    """
    global _db_config_cache, _db_config_cache_time
    if not force_reload and _db_config_cache is not None:
        return _db_config_cache
    loader = get_config_loader()
    # 强制重载 agent_config.json（force_reload 时）
    if force_reload:
        loader.reload()
    db_config = loader.get("database", {})
    # 移除 _comment 等非数据库段
    clean = {k: v for k, v in db_config.items() if not k.startswith("_")}
    _db_config_cache = clean
    _db_config_cache_time = time.time()
    return clean if clean else None


def get_database_config(db_name: str = 'config') -> Dict[str, Any]:
    """获取指定数据库的连接配置。

    Args:
        db_name: config / chat / checkpoint / writing / business

    Returns:
        数据库连接 dict（含 type/host/port/database/user/password 等）
    """
    db_config = load_db_config_file()
    if db_config and db_name in db_config:
        return db_config[db_name].copy()
    raise ValueError(
        f"数据库配置 '{db_name}' 不存在\n"
        f"请在 agent_config.json 的 database.{db_name} 段配置"
    )


def get_storage_config() -> Dict[str, Any]:
    """获取 storage 配置（从 agent_config.json 的 storage 段）"""
    return get_config_loader().get("storage", {})
