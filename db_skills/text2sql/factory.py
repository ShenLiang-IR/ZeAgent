"""TextSQL 单例工厂 — 工具与路由共用，避免初始化逻辑重复。

用项目 agent_config.json 的 database.config 库 + 项目 LLM 配置。
"""
from __future__ import annotations
import os
from urllib.parse import quote_plus
from loguru import logger

_tsql_instance = None


def get_textsql():
    """获取 TextSQL 单例（用项目 MySQL config_db + 项目 LLM 配置）。"""
    global _tsql_instance
    if _tsql_instance is not None:
        return _tsql_instance
    from db_skills.text2sql.core import TextSQL
    from utils.config.db_config import get_database_config
    cfg_db = get_database_config('config')
    db_host = cfg_db.get("host", "127.0.0.1")
    db_port = cfg_db.get("port", 3306)
    db_name = cfg_db.get("database", "agent_config")
    db_user = cfg_db.get("user", "root")
    db_pass = cfg_db.get("password", "")
    conn_str = f"mysql+pymysql://{quote_plus(db_user)}:{quote_plus(db_pass)}@{db_host}:{db_port}/{db_name}?charset=utf8mb4"
    examples_path = "db_skills/text2sql/scenarios.md" if os.path.exists("db_skills/text2sql/scenarios.md") else None
    _tsql_instance = TextSQL(
        conn_str,
        model=None,  # None = 用项目 config 的 LLM
        examples=examples_path,
        trace_file="data/text2sql_traces.jsonl",
    )
    logger.info(f"[text2sql] 初始化完成: {db_name} @ {db_host}:{db_port}")
    return _tsql_instance


def reset_textsql():
    """重置 TextSQL 单例（热重载时调用）。

    清空后下次 get_textsql() 会按最新 agent_config.json 的 database 段重建实例。
    """
    global _tsql_instance
    _tsql_instance = None
