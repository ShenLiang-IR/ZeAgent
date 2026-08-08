from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
import json
class MemoryType(Enum):
    PREFERENCE = "preference"
    FACT = "fact"
    TASK = "task"
    EVENT = "event"
    NOTE = "note"
    CONTEXT = "context"
    SKILL = "skill"
    ERROR = "error"
    RELATION = "relation"
class MemoryPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3
@dataclass
class MemoryBlock:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    type: MemoryType = MemoryType.NOTE
    importance: float = 0.5
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    workspace_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    embedding: Optional[List[float]] = None
    def __post_init__(self):
        self.importance = max(0.0, min(1.0, self.importance))
        if isinstance(self.type, str):
            self.type = MemoryType(self.type)
    def touch(self) -> None:
        self.last_accessed = datetime.now()
        self.access_count += 1
    def decay_importance(self, factor: float = 0.95) -> None:
        self.importance *= factor
        self.importance = max(0.0, min(1.0, self.importance))
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "type": self.type.value if isinstance(self.type, MemoryType) else self.type,
            "importance": self.importance,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "access_count": self.access_count,
            "metadata": self.metadata,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "tags": self.tags,
        }
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryBlock":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            content=data.get("content", ""),
            type=MemoryType(data.get("type", "note")),
            importance=data.get("importance", 0.5),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            last_accessed=datetime.fromisoformat(data["last_accessed"]) if "last_accessed" in data else datetime.now(),
            access_count=data.get("access_count", 0),
            metadata=data.get("metadata", {}),
            session_id=data.get("session_id"),
            user_id=data.get("user_id"),
            workspace_id=data.get("workspace_id"),
            tags=data.get("tags", []),
        )
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
    @classmethod
    def from_json(cls, json_str: str) -> "MemoryBlock":
        return cls.from_dict(json.loads(json_str))
    def get_age_hours(self) -> float:
        delta = datetime.now() - self.created_at
        return delta.total_seconds() / 3600
    def get_recency_score(self, half_life_hours: float = 24.0) -> float:
        import math
        age_hours = self.get_age_hours()
        return math.exp(-math.log(2) * age_hours / half_life_hours)
    def get_combined_score(self, recency_weight: float = 0.3) -> float:
        recency_score = self.get_recency_score()
        access_score = min(1.0, self.access_count / 10.0)
        return (
            self.importance * (1 - recency_weight) +
            recency_score * recency_weight * 0.5 +
            access_score * recency_weight * 0.5
        )
    def get_final_recall_score(self, recency_weight: float = 0.15) -> float:
        """recall 最终排序分：relevance*(1-rw) + recency*rw。

        relevance 取 hybrid_score / similarity / combined_score 兜底；
        recency 用一周(168h)半衰期的时间衰减。
        """
        relevance = self.metadata.get(
            "hybrid_score",
            self.metadata.get("similarity", self.get_combined_score()),
        )
        try:
            rel = float(relevance)
        except (TypeError, ValueError):
            rel = self.get_combined_score()
        recency = self.get_recency_score(half_life_hours=168.0)
        rw = max(0.0, min(1.0, float(recency_weight)))
        return rel * (1.0 - rw) + recency * rw
def create_memory_block(
    content: str,
    type: str = "note",
    importance: float = 0.5,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    source_session_id: Optional[str] = None,
    source_message_id: Optional[str] = None
) -> MemoryBlock:
    memory_type = MemoryType(type) if isinstance(type, str) else type
    meta = dict(metadata or {})
    if source_session_id is not None:
        meta["source_session_id"] = source_session_id
    if source_message_id is not None:
        meta["source_message_id"] = source_message_id
    return MemoryBlock(
        content=content,
        type=memory_type,
        importance=importance,
        session_id=session_id,
        user_id=user_id,
        workspace_id=workspace_id,
        tags=tags or [],
        metadata=meta,
    )