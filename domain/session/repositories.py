from abc import ABC, abstractmethod
from typing import Optional, List
from .entities import Session
class ISessionRepository(ABC):
    @abstractmethod
    def save(self, session: Session) -> Session:
        pass
    @abstractmethod
    def get_by_id(self, session_id: str, user_id: Optional[str] = None) -> Optional[Session]:
        pass
    @abstractmethod
    def list_by_user(self, user_id: str, search: Optional[str] = None, limit: Optional[int] = None, offset: Optional[int] = None) -> List[Session]:
        pass
    @abstractmethod
    def update(self, session: Session) -> Optional[Session]:
        pass
    @abstractmethod
    def delete(self, session_id: str, user_id: Optional[str] = None) -> bool:
        pass