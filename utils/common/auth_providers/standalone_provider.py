from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from uuid import uuid4
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from loguru import logger
from .base import AuthResult, AuthValidationError


class StandaloneJWTProvider:
    # 弱密钥特征子串：密钥含这些词即视为弱密钥（拒绝初始化，防默认/弱密钥）
    _WEAK_SECRET_SUBSTRINGS = (
        "change-me-in-production", "dev-secret", "in-production",
        "change", "secret", "jwt_secret", "password",
    )

    @classmethod
    def _is_weak_secret(cls, secret: str) -> bool:
        s = secret.lower()
        return any(sub in s for sub in cls._WEAK_SECRET_SUBSTRINGS)

    def __init__(self, config: Dict[str, Any]):
        secret = config.get("jwt_secret", "")
        if not secret or self._is_weak_secret(secret):
            raise RuntimeError(
                "auth.jwt_secret 未配置或为弱密钥，拒绝初始化 StandaloneJWTProvider；"
                "请设置高强度随机密钥（建议 >=32 字节，不含 change/dev/secret 等弱关键词）后重启"
            )
        self._secret = secret
        self._algorithm = config.get("jwt_algorithm", "HS256")
        self._default_expiry_days = config.get(
            "providers", {}
        ).get(
            "standalone", {}
        ).get(
            "token_expiry_days", 7
        )
        # refresh 宽限期：token 过期后仍可刷新的时间窗口（防无限刷新）
        # 完整吊销需 Redis jti 黑名单，作为后续迭代
        self._refresh_grace_seconds = 7 * 24 * 3600
        logger.info(
            f"[Auth] StandaloneJWTProvider 初始化完成, "
            f"algorithm={self._algorithm}, expiry_days={self._default_expiry_days}"
        )

    @property
    def name(self) -> str:
        return "standalone"

    @property
    def secret(self) -> str:
        return self._secret

    @property
    def algorithm(self) -> str:
        return self._algorithm

    def validate_token(self, token: str) -> AuthResult:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
            )
            user_id = (
                payload.get("user_id")
                or payload.get("sub")
                or payload.get("tellerId")
            )
            if not user_id:
                raise AuthValidationError("Token 缺少 user_id 标识")
            username = (
                payload.get("username")
                or payload.get("userNickname")
                or f"user_{user_id}"
            )
            roles = payload.get("roles", [])
            if not isinstance(roles, list):
                roles = []
            logger.debug(
                f"[Auth] Standalone token 验证成功: user_id={user_id}, roles={roles}"
            )
            # jti 吊销检查（#5 根治）
            jti = payload.get("jti")
            if jti:
                from services.token_revocation_service import TokenRevocationService
                if TokenRevocationService.get_instance().is_revoked(jti):
                    raise AuthValidationError("Token 已被吊销", status_code=401)
            return AuthResult(
                user_id=str(user_id),
                username=str(username),
                roles=roles,
                payload=payload,
            )
        except ExpiredSignatureError:
            raise AuthValidationError("Token 已过期", status_code=401)
        except InvalidTokenError as e:
            raise AuthValidationError(f"Token 无效: {e}", status_code=401)
        except AuthValidationError:
            raise
        except Exception as e:
            raise AuthValidationError(f"Token 验证失败: {e}", status_code=401)

    def create_token(self, data: dict, expires_delta: Optional[float] = None) -> str:
        to_encode = data.copy()
        now = datetime.now(timezone.utc)
        if expires_delta is not None:
            expire = now + timedelta(seconds=expires_delta)
        else:
            expire = now + timedelta(days=self._default_expiry_days)
        to_encode.update({
            "exp": expire,
            "iat": now,
            "jti": str(uuid4()),
        })
        to_encode.setdefault("roles", [])
        to_encode.setdefault("permissions", [])
        encoded = jwt.encode(to_encode, self._secret, algorithm=self._algorithm)
        logger.debug(f"[Auth] Token 已签发, user_id={to_encode.get('user_id') or to_encode.get('sub')}")
        return encoded

    def refresh_token(self, token: str) -> str:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"verify_exp": False},
            )
            # 宽限期检查：token 过期超 refresh_grace_seconds 则拒绝（防无限刷新）
            exp = payload.get("exp")
            if exp is not None:
                now_ts = datetime.now(timezone.utc).timestamp()
                if now_ts - exp > self._refresh_grace_seconds:
                    raise AuthValidationError(
                        "Token 已过期超出刷新宽限期，请重新登录",
                        status_code=401,
                    )
            payload.pop("exp", None)
            payload.pop("iat", None)
            payload.pop("jti", None)
            new_token = self.create_token(payload)
            logger.debug(f"[Auth] Token 已刷新, user_id={payload.get('user_id') or payload.get('sub')}")
            return new_token
        except AuthValidationError:
            raise
        except InvalidTokenError as e:
            raise AuthValidationError(f"Token 无效: {e}", status_code=401)
        except Exception as e:
            raise AuthValidationError(f"Token 刷新失败: {e}", status_code=401)
