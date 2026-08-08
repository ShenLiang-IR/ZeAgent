import importlib
from typing import Optional, Dict, Any
from loguru import logger
from .base import AuthProvider
_auth_provider: Optional[AuthProvider] = None
def create_auth_provider(auth_config: Dict[str, Any]) -> AuthProvider:
    provider_name = auth_config.get("provider", "invres").lower()
    if not provider_name:
        provider_name = "invres"
    logger.info(f"[Auth]  Provider: {provider_name}")
    if provider_name == "invres":
        from .invres_provider import InvResJWTProvider
        return InvResJWTProvider(auth_config)
    if provider_name == "standalone":
        from .standalone_provider import StandaloneJWTProvider
        return StandaloneJWTProvider(auth_config)
    if provider_name == "apikey":
        from .apikey_provider import ApiKeyProvider
        return ApiKeyProvider(auth_config)
    if "." in provider_name:
        return _load_custom_provider(provider_name, auth_config)
    raise ValueError(
        f" auth.provider: {provider_name}"
        f": invres, standalone, apikey, "
    )
def get_auth_provider() -> AuthProvider:
    global _auth_provider
    if _auth_provider is None:
        from utils.config.config_loader import get_config
        auth_config = get_config("auth", {})
        _auth_provider = create_auth_provider(auth_config)
    return _auth_provider
def reset_auth_provider() -> None:
    global _auth_provider
    _auth_provider = None
    logger.debug("[Auth] AuthProvider ")
def _load_custom_provider(class_path: str, config: Dict[str, Any]) -> AuthProvider:
    try:
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        provider_class = getattr(module, class_name)
        instance = provider_class(config)
        required_methods = ["validate_token", "create_token", "refresh_token"]
        for method in required_methods:
            if not hasattr(instance, method):
                raise ValueError(
                    f" Provider {class_path} : {method}"
                )
        logger.info(f"[Auth]  Provider : {class_path}")
        return instance
    except (ImportError, AttributeError) as e:
        raise ValueError(f" Provider {class_path}: {e}")