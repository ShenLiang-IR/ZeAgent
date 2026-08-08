from contextlib import contextmanager
from typing import Generator
import threading
from sqlalchemy.orm import Session, sessionmaker
from loguru import logger
from .engines import get_config_engine, get_chat_engine, get_writing_engine
_session_factories: dict[str, sessionmaker[Session]] = {}
_factory_lock = threading.Lock()
def _get_session_factory(db_name: str) -> sessionmaker[Session]:
    if db_name in _session_factories:
        return _session_factories[db_name]
    with _factory_lock:
        if db_name in _session_factories:
            return _session_factories[db_name]
        if db_name == 'config':
            engine = get_config_engine()
        elif db_name == 'chat':
            engine = get_chat_engine()
        elif db_name == 'writing':
            engine = get_writing_engine()
        else:
            raise ValueError(f"不支持的数据库: {db_name}（仅支持 config/chat/writing）")
        factory = sessionmaker(
            bind=engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False
        )
        _session_factories[db_name] = factory
    return factory
@contextmanager
def get_session(db_name: str) -> Generator[Session, None, None]:
    factory = _get_session_factory(db_name)
    session = factory()
    try:
        if session.bind and session.bind.dialect.name == 'postgresql':
            from sqlalchemy import text
            session.execute(text("SET client_encoding = 'utf8'"))
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"数据库会话异常({db_name}): {e}", exc_info=True)
        raise
    finally:
        session.close()
@contextmanager
def get_config_session() -> Generator[Session, None, None]:
    with get_session('config') as session:
        yield session
@contextmanager
def get_chat_session() -> Generator[Session, None, None]:
    with get_session('chat') as session:
        yield session
@contextmanager
def get_writing_session() -> Generator[Session, None, None]:
    with get_session('writing') as session:
        yield session