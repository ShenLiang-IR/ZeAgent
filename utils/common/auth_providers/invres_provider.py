import base64
import json
from typing import Dict, Any, Optional
from loguru import logger
from .base import AuthResult, AuthValidationError
class InvResJWTProvider:
    def __init__(self, config: Dict[str, Any]):
        self._system_name = config.get("system_name", "invres")
        logger.info(f"[Auth] InvResJWTProvider , system_name={self._system_name}")
    @property
    def name(self) -> str:
        return "invres"
    def validate_token(self, token: str) -> AuthResult:
        try:
            parts = token.split(".")
            if len(parts) < 2:
                raise AuthValidationError("Token  JWT ")
            payload_segment = parts[1]
            padding = 4 - len(payload_segment) % 4
            if padding != 4:
                payload_segment += "=" * padding
            payload_json = base64.urlsafe_b64decode(
                payload_segment.encode("utf-8")
            ).decode("utf-8")
            payload = json.loads(payload_json)
            user_id = (
                payload.get("tellerId")
                or payload.get("userId")
                or payload.get("user_id")
                or payload.get("sub")
            )
            if not user_id:
                raise AuthValidationError("Token  ID")
            username = (
                payload.get("userNickname")
                or payload.get("userName")
                or payload.get("username")
                or f"user_{user_id}"
            )
            roles = payload.get("roles") or payload.get("authorities", [])
            if not isinstance(roles, list):
                roles = []
            logger.debug(
                f"[Auth] InvRes token : user_id={user_id}, "
                f"username={username}, roles={roles}"
            )
            return AuthResult(
                user_id=str(user_id),
                username=str(username),
                roles=roles,
                payload=payload,
            )
        except AuthValidationError:
            raise
        except Exception as e:
            raise AuthValidationError(f"Token : {e}")
    def create_token(self, data: dict, expires_delta: Optional[float] = None) -> str:
        raise NotImplementedError("InvRes Provider  tokentoken ")
    def refresh_token(self, token: str) -> str:
        raise NotImplementedError("InvRes Provider  token")