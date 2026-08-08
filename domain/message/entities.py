from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
@dataclass
class MessageContent:
    text: str
    reasoning_content: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
@dataclass
class Message:
    session_id: str
    role: MessageRole
    content: MessageContent
    message_order: int
    user_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    def to_langchain_message(self):
        from langchain_core.messages import (
            HumanMessage, AIMessage, SystemMessage, ToolMessage
        )
        if self.role == MessageRole.USER:
            return HumanMessage(content=self.content.text)
        elif self.role == MessageRole.ASSISTANT:
            msg = AIMessage(content=self.content.text)
            if self.content.tool_calls:
                msg.tool_calls = self.content.tool_calls
            return msg
        elif self.role == MessageRole.SYSTEM:
            return SystemMessage(content=self.content.text)
        elif self.role == MessageRole.TOOL:
            return ToolMessage(
                content=self.content.text,
                tool_call_id=self.metadata.get('tool_call_id', '')
            )
        else:
            return HumanMessage(content=self.content.text)