from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class KbRef(BaseModel):
    """知识库引用片段"""
    label: str       # 展示名，如 "投资限制"
    content: str     # 完整引用内容
    kb_id: str       # 知识库 ID
    doc_name: str    # 来源文档名


class ChatMessage(BaseModel):
    role: str
    content: str
    kb_refs: Optional[List[KbRef]] = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True
    )
    messages: List[ChatMessage]
    session_id: Optional[str] = Field(None, alias="sessionId")
    agent_id: Optional[str] = Field(None, alias="agent")
    response_mode: Optional[str] = Field(None, alias="responseMode")
    deep_thinking: Optional[bool] = Field(False, alias="deepThinking")