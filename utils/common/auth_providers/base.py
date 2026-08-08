from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Protocol
@dataclass
class AuthResult:
    user_id: str
    username: str
    roles: list[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)
class AuthValidationError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code
class AuthProvider(Protocol):
    @property
    def name(self) -> str:
        ...
    def validate_token(self, token: str) -> AuthResult:
        ...
    def create_token(self, data: dict, expires_delta: Optional[float] = None) -> str:
        ...
    def refresh_token(self, token: str) -> str:
        ...