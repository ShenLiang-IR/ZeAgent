from typing import Dict, List, Optional, Any
from loguru import logger
from sqlalchemy import and_, select, update, func
# 注意：不从顶部 import utils.id_generator，避免 utils ↔ repositories.chat_repository 循环
# 在使用处方法内懒加载 import（line 27 + line 330）
from ..sessions import get_chat_session
from ..models.chat import Session as SessionModel, Message as MessageModel
class ChatRepository:
    @staticmethod
    def _normalize_pr_key_id(pr_key_id: str) -> str:
        if pr_key_id and '-' in pr_key_id:
            return pr_key_id.replace('-', '')
        return pr_key_id
    def create_session(
        self,
        user_id: str,
        title: Optional[str] = None,
        model_config_data: Optional[Dict[str, Any]] = None,
        source_type: str = "1",
        document_id: Optional[str] = None,
        workspace_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            with get_chat_session() as db_session:
                from utils.id_generator import generate_chat_session_pr_key_id
                pr_key_id = generate_chat_session_pr_key_id()
                session_obj = SessionModel(
                    pr_key_id=pr_key_id,
                    user_id=user_id,
                    title=title,
                    source_type=source_type,
                    document_id=document_id,
                    workspace_id=workspace_id,
                )
                if model_config_data is not None:
                    session_obj.set_model_config(model_config_data)
                db_session.add(session_obj)
                db_session.commit()
                db_session.refresh(session_obj)
                return self._session_to_dict(session_obj)
        except Exception as e:
            logger.error(f"聊天仓储操作失败: {e}", exc_info=True)
            return {}
    def get_session(self, user_id: str, pr_key_id: str, include_deleted: bool = False) -> Optional[Dict[str, Any]]:
        try:
            normalized_pr_key_id = self._normalize_pr_key_id(pr_key_id)
            with get_chat_session() as db_session:
                stmt = select(SessionModel).where(
                    and_(
                        SessionModel.user_id == user_id,
                        SessionModel.pr_key_id == normalized_pr_key_id
                    )
                )
                if not include_deleted:
                    stmt = stmt.where(SessionModel.del_flag == "0")
                session_obj = db_session.scalar(stmt)
                if session_obj:
                    return self._session_to_dict(session_obj)
                return None
        except Exception as e:
            logger.error(f"聊天仓储操作失败: {e}", exc_info=True)
            return None
    def count_sessions(
        self,
        user_id: str,
        search_query: Optional[str] = None,
        include_deleted: bool = False
    ) -> int:
        try:
            with get_chat_session() as db_session:
                stmt = select(func.count()).select_from(SessionModel).where(
                    SessionModel.user_id == user_id
                )
                if not include_deleted:
                    stmt = stmt.where(SessionModel.del_flag == "0")
                if search_query:
                    stmt = stmt.where(
                        SessionModel.title.ilike(f"%{search_query}%")
                    )
                result = db_session.execute(stmt)
                return result.scalar() or 0
        except Exception as e:
            logger.error(f"聊天仓储操作失败: {e}", exc_info=True)
            return 0
    def list_sessions_with_count(
        self,
        user_id: str,
        search_query: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        include_deleted: bool = False
    ) -> tuple:
        try:
            with get_chat_session() as db_session:
                base_where = [SessionModel.user_id == user_id]
                if not include_deleted:
                    base_where.append(SessionModel.del_flag == "0")
                if search_query:
                    base_where.append(SessionModel.title.ilike(f"%{search_query}%"))
                count_stmt = select(func.count()).select_from(SessionModel).where(*base_where)
                total = db_session.execute(count_stmt).scalar() or 0
                list_stmt = select(SessionModel).where(*base_where).order_by(SessionModel.update_time.desc())
                if limit:
                    list_stmt = list_stmt.limit(limit)
                if offset:
                    list_stmt = list_stmt.offset(offset)
                result = db_session.execute(list_stmt)
                sessions = [self._session_to_dict(s) for s in result.scalars().all()]
                return sessions, total
        except Exception as e:
            logger.error(f"聊天仓储操作失败: {e}", exc_info=True)
            return [], 0
    def list_sessions(
        self,
        user_id: str,
        search_query: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        include_deleted: bool = False
    ) -> List[Dict[str, Any]]:
        try:
            with get_chat_session() as db_session:
                stmt = select(SessionModel).where(
                    SessionModel.user_id == user_id
                )
                if not include_deleted:
                    stmt = stmt.where(SessionModel.del_flag == "0")
                if search_query:
                    stmt = stmt.where(
                        SessionModel.title.ilike(f"%{search_query}%")
                    )
                stmt = stmt.order_by(SessionModel.update_time.desc())
                if limit:
                    stmt = stmt.limit(limit)
                if offset:
                    stmt = stmt.offset(offset)
                result = db_session.execute(stmt)
                sessions = result.scalars().all()
                return [self._session_to_dict(s) for s in sessions]
        except Exception as e:
            logger.error(f"聊天仓储操作失败: {e}", exc_info=True)
            return []
    def update_session(
        self,
        user_id: str,
        pr_key_id: str,
        title: Optional[str] = None,
        model_config_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        normalized_pr_key_id = self._normalize_pr_key_id(pr_key_id)
        if title is None and model_config_data is None:
            return self.get_session(user_id, normalized_pr_key_id)
        try:
            with get_chat_session() as db_session:
                stmt = select(SessionModel).where(
                    and_(
                        SessionModel.user_id == user_id,
                        SessionModel.pr_key_id == normalized_pr_key_id,
                        SessionModel.del_flag == "0"
                    )
                )
                session_obj = db_session.scalar(stmt)
                if not session_obj:
                    return None
                if title is not None:
                    session_obj.title = title
                if model_config_data is not None:
                    session_obj.set_model_config(model_config_data)
                db_session.commit()
                db_session.refresh(session_obj)
                return self._session_to_dict(session_obj)
        except Exception as e:
            logger.error(f"聊天仓储操作失败: {e}", exc_info=True)
            return None
    def delete_session(self, user_id: str, pr_key_id: str, hard_delete: bool = False) -> bool:
        normalized_pr_key_id = self._normalize_pr_key_id(pr_key_id)
        try:
            with get_chat_session() as db_session:
                if hard_delete:
                    db_session.execute(
                        MessageModel.__table__.delete().where(
                            and_(
                                MessageModel.session_id == normalized_pr_key_id,
                                MessageModel.user_id == user_id
                            )
                        )
                    )
                    result = db_session.execute(
                        SessionModel.__table__.delete().where(
                            and_(
                                SessionModel.user_id == user_id,
                                SessionModel.pr_key_id == normalized_pr_key_id
                            )
                        )
                    )
                else:
                    db_session.execute(
                        update(MessageModel)
                        .where(
                            and_(
                                MessageModel.session_id == normalized_pr_key_id,
                                MessageModel.user_id == user_id,
                                MessageModel.del_flag == "0"
                            )
                        )
                        .values(del_flag="1")
                    )
                    result = db_session.execute(
                        update(SessionModel)
                        .where(
                            and_(
                                SessionModel.user_id == user_id,
                                SessionModel.pr_key_id == normalized_pr_key_id,
                                SessionModel.del_flag == "0"
                            )
                        )
                        .values(del_flag="1")
                    )
                db_session.commit()
                return result.rowcount > 0
        except Exception as e:
            logger.error(f"聊天仓储操作失败: {e}", exc_info=True)
            return False
    def batch_delete_sessions(self, user_id: str, session_ids: List[str]) -> tuple:
        if not session_ids:
            return 0, 0
        normalized_ids = list(set(self._normalize_pr_key_id(sid) for sid in session_ids))
        try:
            with get_chat_session() as db_session:
                stmt = select(SessionModel).where(
                    and_(
                        SessionModel.user_id == user_id,
                        SessionModel.pr_key_id.in_(normalized_ids),
                        SessionModel.del_flag == "0"
                    )
                )
                result = db_session.execute(stmt)
                sessions = result.scalars().all()
                if not sessions:
                    return 0, len(normalized_ids)
                deleted_ids = [s.pr_key_id for s in sessions]
                deleted_count = len(deleted_ids)
                skipped_count = len(normalized_ids) - deleted_count
                db_session.execute(
                    update(SessionModel)
                    .where(SessionModel.pr_key_id.in_(deleted_ids))
                    .values(del_flag="1")
                )
                db_session.execute(
                    update(MessageModel)
                    .where(
                        and_(
                            MessageModel.session_id.in_(deleted_ids),
                            MessageModel.user_id == user_id,
                            MessageModel.del_flag == "0"
                        )
                    )
                    .values(del_flag="1")
                )
                db_session.commit()
                return deleted_count, skipped_count
        except Exception as e:
            logger.error(f"聊天仓储操作失败: {e}", exc_info=True)
            raise
    def delete_all_sessions(self, user_id: str) -> int:
        try:
            with get_chat_session() as db_session:
                db_session.execute(
                    update(MessageModel)
                    .where(
                        and_(
                            MessageModel.user_id == user_id,
                            MessageModel.del_flag == "0"
                        )
                    )
                    .values(del_flag="1")
                )
                result = db_session.execute(
                    update(SessionModel)
                    .where(
                        and_(
                            SessionModel.user_id == user_id,
                            SessionModel.del_flag == "0"
                        )
                    )
                    .values(del_flag="1")
                )
                db_session.commit()
                return result.rowcount
        except Exception as e:
            logger.error(f"聊天仓储操作失败: {e}", exc_info=True)
            return 0
    def get_messages(self, user_id: str, session_id: str, include_deleted: bool = False) -> List[Dict[str, Any]]:
        try:
            with get_chat_session() as db_session:
                stmt = select(MessageModel).where(
                    and_(
                        MessageModel.user_id == user_id,
                        MessageModel.session_id == session_id
                    )
                )
                if not include_deleted:
                    stmt = stmt.where(MessageModel.del_flag == "0")
                stmt = stmt.order_by(MessageModel.message_order.asc())
                result = db_session.execute(stmt)
                messages = result.scalars().all()
                return [self._message_to_dict(msg) for msg in messages]
        except Exception as e:
            logger.error(f"聊天仓储操作失败: {e}", exc_info=True)
            return []
    def get_recent_messages_across_sessions(
        self,
        user_id: str,
        limit: int = 10,
        exclude_session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """按 user_id 跨 session 加载最近 limit 条消息（排除指定 session）。

        用于 cross_session_history：新会话开头补充之前会话的对话原文作上下文。
        按 create_time 倒序取 limit 条后反转，返回时间正序（最早在前）。
        """
        try:
            with get_chat_session() as db_session:
                stmt = select(MessageModel).where(
                    MessageModel.user_id == user_id,
                    MessageModel.del_flag == "0"
                )
                if exclude_session_id:
                    stmt = stmt.where(MessageModel.session_id != exclude_session_id)
                stmt = stmt.order_by(MessageModel.create_time.desc()).limit(limit)
                result = db_session.execute(stmt)
                messages = result.scalars().all()
                # desc 查出后反转，让时间正序（最早在前）
                return [self._message_to_dict(m) for m in reversed(messages)]
        except Exception as e:
            logger.error(f"get_recent_messages_across_sessions: {str(e)}", exc_info=True)
            return []
    def get_distinct_user_ids(self) -> List[str]:
        """返回 tb_chat_message 中所有不同 user_id（供偏好总结 cron 扫描用户用）。"""
        try:
            with get_chat_session() as db_session:
                stmt = select(MessageModel.user_id).where(
                    MessageModel.del_flag == "0"
                ).distinct()
                result = db_session.execute(stmt)
                return [r[0] for r in result.fetchall() if r[0]]
        except Exception as e:
            logger.error(f"get_distinct_user_ids: {str(e)}", exc_info=True)
            return []
    def save_message(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: Dict[str, Any],
        message_order: int,
        model_id: Optional[str] = None,
        model_name: Optional[str] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        execute_duration: Optional[float] = None,
        execute_steps: Optional[int] = None,
        status: str = "1",
        message_type: str = "chat"
    ) -> Dict[str, Any]:
        try:
            with get_chat_session() as db_session:
                from utils.id_generator import generate_chat_message_pr_key_id
                message = MessageModel(
                    pr_key_id=generate_chat_message_pr_key_id(),
                    user_id=user_id,
                    session_id=session_id,
                    role=role,
                    message_order=message_order,
                    model_id=model_id,
                    model_name=model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    execute_duration=execute_duration,
                    execute_steps=execute_steps,
                    status=status,
                    message_type=message_type
                )
                message.set_content(content)
                db_session.add(message)
                db_session.commit()
                db_session.refresh(message)
                return self._message_to_dict(message)
        except Exception as e:
            logger.error(f"聊天仓储操作失败: {e}", exc_info=True)
            return {}
    def delete_messages_by_session(self, user_id: str, session_id: str) -> int:
        try:
            with get_chat_session() as db_session:
                result = db_session.execute(
                    update(MessageModel)
                    .where(
                        and_(
                            MessageModel.user_id == user_id,
                            MessageModel.session_id == session_id,
                            MessageModel.del_flag == "0"
                        )
                    )
                    .values(del_flag="1")
                )
                db_session.commit()
                return result.rowcount
        except Exception as e:
            logger.error(f"聊天仓储操作失败: {e}", exc_info=True)
            return 0
    def delete_all_messages_by_user(self, user_id: str) -> int:
        try:
            with get_chat_session() as db_session:
                result = db_session.execute(
                    update(MessageModel)
                    .where(
                        and_(
                            MessageModel.user_id == user_id,
                            MessageModel.del_flag == "0"
                        )
                    )
                    .values(del_flag="1")
                )
                db_session.commit()
                return result.rowcount
        except Exception as e:
            logger.error(f"聊天仓储操作失败: {e}", exc_info=True)
            return 0
    def _session_to_dict(self, session_obj: SessionModel) -> Dict[str, Any]:
        create_time_str = session_obj.create_time.isoformat() if session_obj.create_time else None
        update_time_str = session_obj.update_time.isoformat() if session_obj.update_time else None
        return {
            'id': session_obj.pr_key_id,
            'pr_key_id': session_obj.pr_key_id,
            'session_id': session_obj.pr_key_id,
            'user_id': session_obj.user_id,
            'title': session_obj.title,
            'source_type': session_obj.source_type,
            'document_id': session_obj.document_id,
            'model_config_data': session_obj.get_model_config_dict(),
            'message_count': session_obj.message_count,
            'status': 'ongoing' if session_obj.status == '1' else 'completed',
            'visible_scope': session_obj.visible_scope,
            'last_message_at': session_obj.last_message_at.isoformat() if session_obj.last_message_at else None,
            'del_flag': session_obj.del_flag,
            'created_at': create_time_str,
            'updated_at': update_time_str,
            'create_time': create_time_str,
            'update_time': update_time_str,
        }
    def _message_to_dict(self, message: MessageModel) -> Dict[str, Any]:
        role_map = {'1': 'user', '2': 'assistant', '3': 'system'}
        role = role_map.get(message.role, message.role)
        content_dict = message.get_content_dict()
        if isinstance(content_dict, dict) and len(content_dict) == 1 and 'text' in content_dict:
            content = content_dict['text']
        else:
            content = content_dict
        create_time_str = message.create_time.isoformat() if message.create_time else None
        return {
            'id': message.pr_key_id,
            'pr_key_id': message.pr_key_id,
            'user_id': message.user_id,
            'session_id': message.session_id,
            'role': role,
            'content': content,
            'message_order': message.message_order,
            'message_type': message.message_type,
            'created_at': create_time_str,
            'content_type': message.content_type,
            'parent_message_id': message.parent_message_id,
            'prompt_tokens': message.prompt_tokens,
            'completion_tokens': message.completion_tokens,
            'model_id': message.model_id,
            'model_name': message.model_name,
            'execute_duration': float(message.execute_duration) if message.execute_duration else None,
            'execute_steps': message.execute_steps,
            'status': message.status,
            'error_code': message.error_code,
            'error_message': message.error_message,
            'del_flag': message.del_flag,
            'create_time': create_time_str,
        }