import os
import re
from typing import Any
_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")
def resolve_env(value: Any) -> Any:
    if isinstance(value, str):
        full_match = _ENV_PATTERN.fullmatch(value)
        if full_match:
            env_var, default = full_match.groups()
            return os.environ.get(env_var, default or "")
        def replace(match: re.Match[str]) -> str:
            env_var, default = match.groups()
            return os.environ.get(env_var, default or "")
        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {key: resolve_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_env(item) for item in value]
    return value