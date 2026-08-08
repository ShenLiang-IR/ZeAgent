from abc import ABC, abstractmethod
from typing import List, Optional
from .entities import Message
class IMessageRepository(ABC):
    @abstractmethod
    def get_by_session(self, session_id: str, user_id: Optional[str] = None) -> List[Message]:
        pass
    @abstractmethod
    def delete_by_session(self, session_id: str, user_id: Optional[str] = None) -> int:
        pass