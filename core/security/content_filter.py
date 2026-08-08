"""敏感词过滤 + 输出拦截中间件。

用法：
  from core.security.content_filter import filter_content
  result = filter_content("用户输入或AI输出")
  if result.blocked:
      return "内容包含不当信息，已被拦截"

配置开关：config/agent_config.json -> security.content_filter.enabled
"""
from __future__ import annotations

from loguru import logger


class FilterResult:
    def __init__(self, blocked: bool = False, reason: str = "", matched: list[str] = None):
        self.blocked = blocked
        self.reason = reason
        self.matched = matched or []

    def __bool__(self):
        return self.blocked


_DEFAULT_SENSITIVE_WORDS: list[str] = []


def _load_words() -> list[str]:
    words = list(_DEFAULT_SENSITIVE_WORDS)
    try:
        from infrastructure.database.repositories.security_repository import SensitiveWordRepository
        db_words = SensitiveWordRepository().get_enabled_words()
        words.extend(db_words)
    except Exception as e:
        logger.warning(f"[ContentFilter] load words failed: {e}")
    return words


def filter_content(text: str) -> FilterResult:
    if not text or not text.strip():
        return FilterResult()
    try:
        from utils.config import get_config
        if not get_config("security.content_filter.enabled", False):
            return FilterResult()
    except Exception:
        return FilterResult()

    words = _load_words()
    if not words:
        return FilterResult()

    matched = []
    for word in words:
        if word and word in text:
            matched.append(word)

    if matched:
        logger.warning(f"[ContentFilter] matched: {matched}")
        return FilterResult(blocked=True, reason="content blocked", matched=matched)

    return FilterResult()


def log_filter_event(text: str, matched: list[str], direction: str = "input",
                     user_id: str = "", username: str = "", workspace_id: int = None):
    try:
        from infrastructure.database.repositories.audit_repository import AuditRepository
        from utils.id_generator import generate_uuid
        AuditRepository().create(
            audit_id=f"AUDIT_{generate_uuid()[:16]}",
            user_id=user_id or "",
            username=username or "",
            workspace_id=workspace_id,
            resource_type="security",
            resource_id=",".join(matched[:5]),
            action=f"blocked_{direction}",
            path="/api/chat/stream",
            status_code=200,
            before_data=text[:500] if text else "",
            after_data=f"匹配词: {','.join(matched[:10])}",
        )
    except Exception as e:
        logger.warning(f"[ContentFilter] audit write failed: {e}")
