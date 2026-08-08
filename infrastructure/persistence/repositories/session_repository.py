from loguru import logger
from typing import Optional, List
from datetime import datetime
from domain.session.entities import Session
from domain.session.repositories import ISessionRepository
class SessionRepository(ISessionRepository):
    def __init__(self, db_connection):
        self.db = db_connection
    def save(self, session: Session) -> Session:
        try:
            from utils.db import get_chat_db
            chat_db = get_chat_db()
            result = chat_db.create_session(
                user_id=session.user_id,
                title=session.title
            )
            if result:
                session.session_id = result.get('pr_key_id', session.session_id)
                if 'created_at' in result:
                    session.created_at = datetime.fromisoformat(result['created_at'].replace('Z', '+00:00'))
                if 'updated_at' in result:
                    session.updated_at = datetime.fromisoformat(result['updated_at'].replace('Z', '+00:00'))
            return session
        except Exception as e:
            logger.error(f"会话仓储操作失败: {e}", exc_info=True)
            raise
    def get_by_id(self, session_id: str, user_id: Optional[str] = None) -> Optional[Session]:
        try:
            from utils.db import get_chat_db
            chat_db = get_chat_db()
            result = chat_db.get_session(user_id=user_id, pr_key_id=session_id)
            if not result:
                return None
            session = Session(
                session_id=result.get('pr_key_id', session_id),
                user_id=result.get('user_id'),
                title=result.get('title'),
                message_count=result.get('message_count', 0),
                status=result.get('status', '1'),
                visible_scope=result.get('visible_scope', '1')
            )
            if 'created_at' in result:
                session.created_at = datetime.fromisoformat(result['created_at'].replace('Z', '+00:00'))
            if 'updated_at' in result:
                session.updated_at = datetime.fromisoformat(result['updated_at'].replace('Z', '+00:00'))
            return session
        except Exception as e:
            logger.error(f"会话仓储操作失败: {e}", exc_info=True)
            raise
    def list_by_user(self, user_id: str, search: Optional[str] = None, limit: Optional[int] = None, offset: Optional[int] = None) -> List[Session]:
        try:
            from utils.db import get_chat_db
            chat_db = get_chat_db()
            results = chat_db.list_sessions(
                user_id=user_id,
                search_query=search,
                limit=limit,
                offset=offset
            )
            sessions = []
            for result in results:
                session = Session(
                    session_id=result.get('pr_key_id', ''),
                    user_id=result.get('user_id'),
                    title=result.get('title'),
                    message_count=result.get('message_count', 0),
                    status=result.get('status', '1'),
                    visible_scope=result.get('visible_scope', '1')
                )
                if 'created_at' in result:
                    session.created_at = datetime.fromisoformat(result['created_at'].replace('Z', '+00:00'))
                if 'updated_at' in result:
                    session.updated_at = datetime.fromisoformat(result['updated_at'].replace('Z', '+00:00'))
                sessions.append(session)
            return sessions
        except Exception as e:
            logger.error(f"会话仓储操作失败: {e}", exc_info=True)
            raise
    def update(self, session: Session) -> Optional[Session]:
        try:
            from utils.db import get_chat_db
            chat_db = get_chat_db()
            result = chat_db.update_session(
                user_id=session.user_id,
                pr_key_id=session.session_id,
                title=session.title
            )
            if not result:
                return None
            if 'updated_at' in result:
                session.updated_at = datetime.fromisoformat(result['updated_at'].replace('Z', '+00:00'))
            return session
        except Exception as e:
            logger.error(f"会话仓储操作失败: {e}", exc_info=True)
            raise
    def delete(self, session_id: str, user_id: Optional[str] = None) -> bool:
        try:
            from utils.db import get_chat_db
            chat_db = get_chat_db()
            success = chat_db.delete_session(user_id=user_id, pr_key_id=session_id)
            return success
        except Exception as e:
            logger.error(f"会话仓储操作失败: {e}", exc_info=True)
            raise