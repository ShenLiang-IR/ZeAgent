from typing import Dict, Any, Optional
from urllib.parse import quote_plus
from sqlalchemy import create_engine, Engine
from sqlalchemy.pool import QueuePool
from loguru import logger
_engines: Dict[str, Engine] = {}
def build_database_url(db_config: Dict[str, Any]) -> str:
    db_type = (db_config.get('type') or db_config.get('dbtype', 'postgresql')).lower()
    user = db_config.get('user') or db_config.get('username', '')
    password = db_config.get('password') or db_config.get('pwd', '')
    encoded_user = quote_plus(user)
    encoded_password = quote_plus(password)
    if db_type in ('postgresql', 'postgres'):
        host = db_config['host']
        port = db_config.get('port', 5432)
        database = db_config['database']
        url = f"postgresql://{encoded_user}:{encoded_password}@{host}:{port}/{database}"
        return url
    elif db_type in ('doris', 'mysql'):
        host = db_config['host']
        port = db_config.get('port', 3306)
        database = db_config['database']
        url = f"mysql+pymysql://{encoded_user}:{encoded_password}@{host}:{port}/{database}?charset=utf8mb4"
        return url
    else:
        raise ValueError(f"不支持的数据库类型: {db_type}")
def _get_connect_args(db_config: Dict[str, Any]) -> Dict[str, Any]:
    connect_args = {}
    db_type = db_config.get('type', db_config.get('dbtype', '')).lower()
    if db_type in ('postgresql', 'postgres'):
        if 'schema' in db_config and db_config['schema']:
            schema = db_config['schema']
            connect_args['options'] = f'-csearch_path={schema},public'
        connect_args['client_encoding'] = 'utf8'
    elif db_type in ('doris', 'mysql'):
        connect_args['ssl_disabled'] = True
    return connect_args
def get_engine(db_name: str, db_config: Optional[Dict[str, Any]] = None) -> Engine:
    if db_name in _engines:
        return _engines[db_name]
    if db_config is None:
        from utils.config.db_config import get_database_config
        db_config = get_database_config(db_name)
    database_url = build_database_url(db_config)
    connect_args = _get_connect_args(db_config)
    pool_size = db_config.get('mincached', db_config.get('minconn', 5))
    max_overflow = db_config.get('maxconnections', db_config.get('maxconn', 20)) - pool_size
    engine = create_engine(
        database_url,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
        connect_args=connect_args
    )
    _engines[db_name] = engine
    logger.info(f"数据库引擎已创建: {db_name} (pool_size={pool_size}, max_overflow={max_overflow})")
    return engine
def get_config_engine(db_config: Optional[Dict[str, Any]] = None) -> Engine:
    return get_engine('config', db_config)
def get_chat_engine(db_config: Optional[Dict[str, Any]] = None) -> Engine:
    return get_engine('chat', db_config)
def get_writing_engine(db_config: Optional[Dict[str, Any]] = None) -> Engine:
    return get_engine('writing', db_config)
def close_all_engines():
    global _engines
    for db_name, engine in _engines.items():
        engine.dispose()
        logger.info(f"数据库引擎已关闭: {db_name}")
    _engines.clear()