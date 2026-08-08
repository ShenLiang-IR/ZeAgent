import json
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy import String, Text, Integer, BigInteger, Index, DateTime as SqlDateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from ..base import Base
class ChatSession(Base):
    __tablename__ = "tb_chat_session"
    pr_key_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="ID")
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="ID")
    workspace_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="所属工作空间")
    title: Mapped[Optional[str]] = mapped_column(String(255), comment="")
    model_config_data: Mapped[Optional[str]] = mapped_column(Text, comment="JSON")
    source_type: Mapped[str] = mapped_column(String(1), default="1", comment="1-2-")
    document_id: Mapped[Optional[str]] = mapped_column(String(64), comment="ID")
    message_count: Mapped[int] = mapped_column(Integer, default=0, comment="")
    status: Mapped[str] = mapped_column(String(1), default="1", comment="1-2-")
    visible_scope: Mapped[str] = mapped_column(String(1), default="1", comment="1-2-")
    last_message_at: Mapped[Optional[datetime]] = mapped_column(SqlDateTime, comment="")
    del_flag: Mapped[str] = mapped_column(String(1), default="0", comment="")
    create_time: Mapped[Optional[datetime]] = mapped_column(SqlDateTime(timezone=True), server_default=func.now(), comment="")
    update_time: Mapped[Optional[datetime]] = mapped_column(SqlDateTime(timezone=True), server_default=func.now(), onupdate=func.now(), comment="")
    __table_args__ = (
        Index('idx_chat_session_user_id', 'user_id'),
        Index('idx_chat_session_user_updated', 'user_id', 'update_time'),
        Index('idx_chat_session_status', 'status'),
        Index('idx_chat_session_source_type', 'source_type'),
        Index('idx_chat_session_document', 'document_id'),
    )
    def get_model_config_dict(self) -> Optional[Dict[str, Any]]:
        if not self.model_config_data:
            return None
        if isinstance(self.model_config_data, str):
            try:
                return json.loads(self.model_config_data)
            except json.JSONDecodeError:
                return None
        return self.model_config_data if isinstance(self.model_config_data, dict) else None
    def set_model_config(self, config: Optional[Dict[str, Any]]):
        if config is None:
            self.model_config_data = None
        else:
            self.model_config_data = json.dumps(config, ensure_ascii=False)
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.pr_key_id,
            'pr_key_id': self.pr_key_id,
            'user_id': self.user_id,
            'title': self.title,
            'source_type': self.source_type,
            'document_id': self.document_id,
            'model_config_data': self.get_model_config_dict(),
            'message_count': self.message_count,
            'status': self.status,
            'visible_scope': self.visible_scope,
            'last_message_at': self.last_message_at.isoformat() if self.last_message_at else None,
            'del_flag': self.del_flag,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None,
        }
class ChatMessage(Base):
    __tablename__ = "tb_chat_message"
    pr_key_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="ID")
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="IDtb_chat_session.pr_key_id")
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="ID")
    role: Mapped[str] = mapped_column(String(1), nullable=False, comment="1-2-3-")
    content_type: Mapped[str] = mapped_column(String(1), default="1", comment="1-2-3-")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="JSON")
    message_order: Mapped[int] = mapped_column(Integer, nullable=False, comment="")
    parent_message_id: Mapped[Optional[str]] = mapped_column(String(64), comment="ID")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, comment="Prompt Token")
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, comment="Completion Token")
    model_id: Mapped[Optional[str]] = mapped_column(String(32), comment="ID")
    model_name: Mapped[Optional[str]] = mapped_column(String(100), comment="")
    execute_duration: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), comment="")
    execute_steps: Mapped[Optional[int]] = mapped_column(Integer, comment="")
    status: Mapped[str] = mapped_column(String(1), default="1", comment="1-2-")
    error_code: Mapped[Optional[str]] = mapped_column(String(32), comment="")
    error_message: Mapped[Optional[str]] = mapped_column(Text, comment="")
    del_flag: Mapped[str] = mapped_column(String(1), default="0", comment="")
    create_time: Mapped[Optional[datetime]] = mapped_column(SqlDateTime(timezone=True), server_default=func.now(), comment="")
    message_type: Mapped[str] = mapped_column(String(20), default="chat", comment="chat-writing_init-writing_result-writing_chat-")
    __table_args__ = (
        Index('idx_chat_message_session_id', 'session_id'),
        Index('idx_chat_message_user_session', 'user_id', 'session_id'),
        Index('idx_chat_message_session_order', 'session_id', 'message_order'),
        Index('idx_chat_message_user_session_order', 'user_id', 'session_id', 'message_order'),
        Index('idx_chat_message_parent', 'parent_message_id'),
        Index('idx_chat_message_type', 'message_type'),
    )
    def get_content_dict(self) -> Dict[str, Any]:
        if isinstance(self.content, str):
            try:
                return json.loads(self.content)
            except json.JSONDecodeError:
                return {'text': self.content}
        return self.content if isinstance(self.content, dict) else {'text': str(self.content)}
    def set_content(self, content: Dict[str, Any]):
        self.content = json.dumps(content, ensure_ascii=False)
    @property
    def token_count(self) -> int:
        return self.prompt_tokens + self.completion_tokens
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.pr_key_id,
            'pr_key_id': self.pr_key_id,
            'session_id': self.session_id,
            'user_id': self.user_id,
            'role': self.role,
            'content_type': self.content_type,
            'content': self.get_content_dict(),
            'message_order': self.message_order,
            'parent_message_id': self.parent_message_id,
            'token_count': self.token_count,
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'model_id': self.model_id,
            'model_name': self.model_name,
            'execute_duration': float(self.execute_duration) if self.execute_duration else None,
            'execute_steps': self.execute_steps,
            'status': self.status,
            'error_code': self.error_code,
            'error_message': self.error_message,
            'del_flag': self.del_flag,
            'message_type': self.message_type,
            'create_time': self.create_time.isoformat() if self.create_time else None,
        }
Session = ChatSession
Message = ChatMessage