from loguru import logger
from typing import List, Optional
from domain.message.entities import Message, MessageContent, MessageRole
from domain.message.repositories import IMessageRepository
class MessageRepository(IMessageRepository):
    def __init__(self, db_connection):
        self.db = db_connection
    def get_by_session(self, session_id: str, user_id: Optional[str] = None) -> List[Message]:
        try:
            from utils.db import get_chat_db
            chat_db = get_chat_db()
            user_id = str(user_id) if user_id else 'guest'
            message_dicts = chat_db.get_messages(user_id, session_id)
            messages = []
            for msg_dict in message_dicts:
                role_str = msg_dict.get('role', 'user').lower()
                if role_str == 'user':
                    role = MessageRole.USER
                elif role_str == 'assistant':
                    role = MessageRole.ASSISTANT
                elif role_str == 'system':
                    role = MessageRole.SYSTEM
                else:
                    continue
                content_text = ""
                reasoning_content = None
                content_data = msg_dict.get('content')
                if isinstance(content_data, dict):
                    content_text = content_data.get('text', content_data.get('content', ''))
                    reasoning_content = content_data.get('reasoning_content')
                else:
                    content_text = str(content_data) if content_data else ""
                message = Message(
                    session_id=session_id,
                    role=role,
                    content=MessageContent(
                        text=content_text,
                        reasoning_content=reasoning_content
                    ),
                    message_order=msg_dict.get('message_order', 0),
                    user_id=user_id
                )
                messages.append(message)
            logger.debug(f" {len(messages)}  (session_id: {session_id})")
            return messages
        except Exception as e:
            logger.error(f"消息仓储操作失败: {e}", exc_info=True)
            return []
    def delete_by_session(self, session_id: str, user_id: Optional[str] = None) -> int:
        try:
            from utils.db import get_chat_db
            chat_db = get_chat_db()
            user_id = str(user_id) if user_id else 'guest'
            count = chat_db.delete_messages_by_session(user_id, session_id)
            if count > 0:
                logger.info(f"删除消息成功: session_id={session_id} (共 {count} 条)")
            else:
                logger.warning(f"未删除任何消息: session_id={session_id}")
            return count
        except Exception as e:
            logger.error(f"消息仓储操作失败: {e}", exc_info=True)
            return 0