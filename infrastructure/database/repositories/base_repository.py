from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional, List, Dict, Any, Type, Callable
from contextlib import contextmanager
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from ..base import Base
T = TypeVar('T', bound=Base)
D = TypeVar('D')
class BaseRepository(ABC, Generic[T, D]):
    """仓储基类。

    子类可通过类属性 _session_factory / _model_class / _pk_name 声明配置，
    无需覆写 __init__ 和 _get_primary_key_name。
    向后兼容：仍支持 super().__init__(session_factory=..., model_class=...)。
    """
    _session_factory: Callable = None
    _model_class: Type[T] = None
    _pk_name: str = 'id'

    def __init__(self, session_factory: Callable = None, model_class: Type[T] = None):
        """初始化仓储。参数为空时从类属性读取。"""
        self._session_factory = session_factory or type(self)._session_factory
        self._model_class = model_class or type(self)._model_class
    @contextmanager
    def _get_session(self):
        with self._session_factory() as session:
            yield session
    def _ensure_attributes_loaded(self, entity: T, session: Session, attributes: List[str] = None) -> T:
        if entity and attributes:
            for attr in attributes:
                if hasattr(entity, attr):
                    _ = getattr(entity, attr)
        return entity
    def _expunge_entity(self, entity: T, session: Session) -> T:
        if entity:
            session.expunge(entity)
        return entity
    @abstractmethod
    def _entity_to_dict(self, entity: T, session: Session) -> D:
        pass
    def _get_primary_key_name(self) -> str:
        """返回主键字段名。子类可通过 _pk_name 类属性声明。"""
        return type(self)._pk_name
    def get_by_id(self, id_value: Any, return_dict: bool = False, 
                  ensure_attributes: List[str] = None) -> Optional[D | T]:
        try:
            with self._get_session() as session:
                pk_attr = getattr(self._model_class, self._get_primary_key_name())
                stmt = select(self._model_class).where(pk_attr == id_value)
                entity = session.scalar(stmt)
                if entity:
                    if ensure_attributes:
                        entity = self._ensure_attributes_loaded(entity, session, ensure_attributes)
                    if return_dict:
                        return self._entity_to_dict(entity, session)
                    else:
                        entity = self._expunge_entity(entity, session)
                        return entity
                return None
        except SQLAlchemyError as e:
            logger.error(f"{self._model_class.__name__} (id={id_value}): {str(e)}", exc_info=True)
            return None
    def get_all(self, filters: Dict[str, Any] = None, order_by: str = None,
                limit: Optional[int] = None, offset: Optional[int] = None,
                return_dict: bool = False, enabled_only: bool = False) -> List[D | T]:
        try:
            with self._get_session() as session:
                stmt = select(self._model_class)
                if filters:
                    for field, value in filters.items():
                        if hasattr(self._model_class, field):
                            stmt = stmt.where(getattr(self._model_class, field) == value)
                if enabled_only and hasattr(self._model_class, 'enabled'):
                    stmt = stmt.where(self._model_class.enabled == True)
                if order_by and hasattr(self._model_class, order_by):
                    stmt = stmt.order_by(getattr(self._model_class, order_by))
                if offset:
                    stmt = stmt.offset(offset)
                if limit:
                    stmt = stmt.limit(limit)
                entities = session.scalars(stmt).all()
                if return_dict:
                    return [self._entity_to_dict(e, session) for e in entities]
                else:
                    for entity in entities:
                        self._expunge_entity(entity, session)
                    return list(entities)
        except SQLAlchemyError as e:
            logger.error(f"{self._model_class.__name__}: {str(e)}", exc_info=True)
            return []
    def create(self, **kwargs) -> Optional[T]:
        try:
            pk_name = self._get_primary_key_name()
            kwargs.pop(pk_name, None)
            with self._get_session() as session:
                entity = self._model_class(**kwargs)
                session.add(entity)
                session.commit()
                session.refresh(entity)
                entity = self._expunge_entity(entity, session)
                return entity
        except SQLAlchemyError as e:
            logger.error(f"{self._model_class.__name__}: {str(e)}", exc_info=True)
            return None
    def update(self, id_value: Any, **kwargs) -> Optional[T]:
        try:
            with self._get_session() as session:
                pk_attr = getattr(self._model_class, self._get_primary_key_name())
                stmt = select(self._model_class).where(pk_attr == id_value)
                entity = session.scalar(stmt)
                if not entity:
                    return None
                for key, value in kwargs.items():
                    if hasattr(entity, key):
                        setattr(entity, key, value)
                session.commit()
                session.refresh(entity)
                entity = self._expunge_entity(entity, session)
                return entity
        except SQLAlchemyError as e:
            logger.error(f"{self._model_class.__name__} (id={id_value}): {str(e)}", exc_info=True)
            return None
    def delete(self, id_value: Any) -> bool:
        try:
            with self._get_session() as session:
                pk_attr = getattr(self._model_class, self._get_primary_key_name())
                stmt = select(self._model_class).where(pk_attr == id_value)
                entity = session.scalar(stmt)
                if entity:
                    session.delete(entity)
                    session.commit()
                    return True
                return False
        except SQLAlchemyError as e:
            logger.error(f"{self._model_class.__name__} (id={id_value}): {str(e)}", exc_info=True)
            return False
    def upsert(self, id_value: Any, **kwargs) -> Optional[T]:
        try:
            pk_name = self._get_primary_key_name()
            with self._get_session() as session:
                pk_attr = getattr(self._model_class, pk_name)
                stmt = select(self._model_class).where(pk_attr == id_value)
                entity = session.scalar(stmt)
                if entity:
                    for key, value in kwargs.items():
                        if hasattr(entity, key) and key != pk_name:
                            setattr(entity, key, value)
                else:
                    kwargs.pop(pk_name, None)
                    entity = self._model_class(**kwargs)
                    session.add(entity)
                session.commit()
                session.refresh(entity)
                entity = self._expunge_entity(entity, session)
                return entity
        except SQLAlchemyError as e:
            logger.error(f"Upsert {self._model_class.__name__}  (id={id_value}): {str(e)}", exc_info=True)
            return None