from typing import Dict, List, Optional, Any
from infrastructure.database.repositories.chat_repository import ChatRepository
class ChatDatabase:
    def __init__(self):
        self._repo = ChatRepository()
    def create_session(
        self,
        user_id: str,
        title: Optional[str] = None,
        model_config_data: Optional[Dict[str, Any]] = None,
        workspace_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self._repo.create_session(
            user_id=user_id,
            title=title,
            model_config_data=model_config_data,
            workspace_id=workspace_id,
        )
    def get_session(self, user_id: str, pr_key_id: str) -> Optional[Dict[str, Any]]:
        return self._repo.get_session(user_id=user_id, pr_key_id=pr_key_id)
    def count_sessions(
        self,
        user_id: str,
        search_query: Optional[str] = None
    ) -> int:
        return self._repo.count_sessions(
            user_id=user_id,
            search_query=search_query
        )
    def list_sessions(
        self,
        user_id: str,
        search_query: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return self._repo.list_sessions(
            user_id=user_id,
            search_query=search_query,
            limit=limit,
            offset=offset
        )
    def list_sessions_with_count(
        self,
        user_id: str,
        search_query: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> tuple:
        return self._repo.list_sessions_with_count(
            user_id=user_id,
            search_query=search_query,
            limit=limit,
            offset=offset
        )
    def update_session(
        self,
        user_id: str,
        pr_key_id: str,
        title: Optional[str] = None,
        model_config_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        return self._repo.update_session(
            user_id=user_id,
            pr_key_id=pr_key_id,
            title=title,
            model_config_data=model_config_data
        )
    def delete_session(self, user_id: str, pr_key_id: str) -> bool:
        return self._repo.delete_session(user_id=user_id, pr_key_id=pr_key_id)
    def delete_all_sessions(self, user_id: str) -> int:
        return self._repo.delete_all_sessions(user_id=user_id)
    def batch_delete_sessions(self, user_id: str, session_ids: List[str]) -> tuple:
        return self._repo.batch_delete_sessions(user_id=user_id, session_ids=session_ids)
    def get_messages(self, user_id: str, session_id: str) -> List[Dict[str, Any]]:
        return self._repo.get_messages(user_id=user_id, session_id=session_id)
    def get_recent_messages_across_sessions(
        self, user_id: str, limit: int = 10, exclude_session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """跨 session 按 user_id 加载最近 limit 条消息（排除指定 session）。"""
        return self._repo.get_recent_messages_across_sessions(
            user_id=user_id, limit=limit, exclude_session_id=exclude_session_id
        )
    def get_distinct_user_ids(self) -> List[str]:
        """返回所有不同 user_id（供偏好总结 cron 扫描用户用）。"""
        return self._repo.get_distinct_user_ids()
    def save_message(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: Dict[str, Any],
        message_order: int
    ) -> Dict[str, Any]:
        return self._repo.save_message(
            user_id=user_id,
            session_id=session_id,
            role=role,
            content=content,
            message_order=message_order
        )
    def delete_messages_by_session(self, user_id: str, session_id: str) -> int:
        return self._repo.delete_messages_by_session(user_id=user_id, session_id=session_id)
_chat_db: Optional[ChatDatabase] = None
def get_chat_db() -> ChatDatabase:
    global _chat_db
    if _chat_db is None:
        _chat_db = ChatDatabase()
    return _chat_db