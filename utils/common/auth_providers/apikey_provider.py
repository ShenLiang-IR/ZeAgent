from typing import Dict, Any, Optional
from loguru import logger
from .base import AuthResult, AuthValidationError
class ApiKeyProvider:
    def __init__(self, config: Dict[str, Any]):
        apikey_config = config.get("providers", {}).get("apikey", {})
        self._keys: Dict[str, Dict[str, Any]] = apikey_config.get("keys", {})
        if not self._keys:
            logger.warning("[Auth] ApiKeyProvider  API Key")
        logger.info(f"[Auth] ApiKeyProvider ,  {len(self._keys)}  API Key")
    @property
    def name(self) -> str:
        return "apikey"
    def validate_token(self, token: str) -> AuthResult:
        if token not in self._keys:
            raise AuthValidationError(" API Key", status_code=401)
        user_info = self._keys[token]
        user_id = str(user_info.get("user_id", ""))
        if not user_id:
            raise AuthValidationError("API Key  user_id")
        username = user_info.get("username", f"api_user_{user_id}")
        roles = user_info.get("roles", [])
        logger.debug(f"[Auth] API Key : user_id={user_id}")
        return AuthResult(
            user_id=user_id,
            username=str(username),
            roles=roles,
            payload=user_info.copy(),
        )
    def create_token(self, data: dict, expires_delta: Optional[float] = None) -> str:
        raise NotImplementedError("ApiKey Provider  token API Key")
    def refresh_token(self, token: str) -> str:
        raise NotImplementedError("ApiKey Provider  tokenAPI Key ")