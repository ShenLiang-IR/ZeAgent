from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime
@dataclass
class Session:
    session_id: str
    user_id: Optional[str] = None
    title: Optional[str] = None
    message_count: int = 0
    status: str = "1"
    visible_scope: str = "1"
    last_message_at: Optional[datetime] = None
    del_flag: str = "0"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    def update(self, title: Optional[str] = None):
        if title is not None:
            self.title = title
        self.updated_at = datetime.now()