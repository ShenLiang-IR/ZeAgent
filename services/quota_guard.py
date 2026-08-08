"""配额自动拦截守卫：在 dispatch/chat 入口检查配额，超限抛 QuotaExceededError 或返回 degrade 信号。

设计参见 docs/specs/2026-07-19-usage-tracking-design.md §4。

核心 API：
- extract_workspace_id(authorization) -> int | None：从 JWT payload 提取 workspace_id
- enforce_quota(authorization, estimated_tokens) -> QuotaResult：检查配额，block 超限抛 QuotaExceededError，degrade 超限返回 degraded 信号
- estimate_prompt_tokens(message) -> int：粗估 prompt token 数
- QuotaResult：配额检查结果（workspace_id + degraded + degrade_model_id）
- QuotaExceededError：block 超限异常，由 server exception_handler 捕获返回 429

行为策略：
- 无 workspace_id（匿名/无 token）：跳过配额检查，不阻塞（向下兼容本地开发）
- block 模式超限：抛 QuotaExceededError（→ HTTP 429）
- degrade 模式超限：返回 QuotaResult(degraded=True, degrade_model_id=...)，调用方切备用模型（不阻塞）
- warn 模式超限：QuotaResult(degraded=False)，仅记日志
- QuotaService 故障：fail-open（不阻塞主流程，记 warning）

degrade 备用模型来源：config quota.fallback_model_id（全局 fallback）。
"""
from dataclasses import dataclass

from loguru import logger


@dataclass
class QuotaResult:
    """配额检查结果。

    Attributes:
        workspace_id: workspace ID（供 usage 记录用）；匿名 None
        degraded: True 表示配额超限且 degrade 模式，调用方应切备用模型
        degrade_model_id: 备用模型 id（degraded=True 时从 config quota.fallback_model_id 读）
    """
    workspace_id: int | None = None
    degraded: bool = False
    degrade_model_id: str | None = None


class QuotaExceededError(Exception):
    """配额超限异常。由 server exception_handler 捕获返回 429。"""

    def __init__(self, message: str, workspace_id: int | None = None):
        super().__init__(message)
        self.workspace_id = workspace_id


def extract_workspace_id(authorization: str | None) -> int | None:
    """从 Authorization header 的 JWT payload 提取 workspace_id。

    失败（无 token / 无效 / 无 workspace_id 字段）返回 None，不抛异常。

    Args:
        authorization: Authorization header 值（"Bearer xxx" 或 None）

    Returns:
        workspace_id（int）；无法提取返回 None
    """
    if not authorization:
        return None
    try:
        from services.auth_service import AuthService
        payload = AuthService().verify_token(authorization)
        if not payload:
            return None
        wid = payload.get("workspace_id")
        return int(wid) if wid is not None else None
    except Exception:
        return None


def enforce_quota(
    authorization: str | None,
    estimated_tokens: int,
    quota_type: str = "monthly_token",
) -> QuotaResult:
    """检查配额并扣减，block 超限抛 QuotaExceededError，degrade 超限返回 degraded 信号。

    无 workspace_id（匿名/无 token）时跳过配额检查，不阻塞主流程（向下兼容）。

    Args:
        authorization: Authorization header（用于提取 workspace_id）
        estimated_tokens: 本次预估新增 token 数
        quota_type: monthly_token / daily_token / monthly_cost

    Returns:
        QuotaResult（workspace_id + degraded + degrade_model_id）；匿名 workspace_id=None

    Raises:
        QuotaExceededError: 配额超限且 over_limit_action=block
    """
    workspace_id = extract_workspace_id(authorization)
    if workspace_id is None:
        return QuotaResult(workspace_id=None)  # 匿名，跳过配额
    try:
        from services.quota_service import QuotaService
        allowed, reason = QuotaService().check_and_deduct(
            workspace_id=workspace_id,
            quota_type=quota_type,
            estimated=estimated_tokens,
        )
        if not allowed:
            raise QuotaExceededError(
                f"workspace {workspace_id} 配额超限（{quota_type}）：{reason}",
                workspace_id=workspace_id,
            )
        # degrade 模式：reason 含 "degrade"，调用方应切备用模型
        degraded = "degrade" in (reason or "").lower()
        degrade_model_id = None
        if degraded:
            from utils.config import get_config
            degrade_model_id = get_config("quota.fallback_model_id", None)
            logger.info(
                f"[QuotaGuard] degrade workspace={workspace_id}, fallback_model={degrade_model_id}"
            )
        return QuotaResult(
            workspace_id=workspace_id,
            degraded=degraded,
            degrade_model_id=degrade_model_id,
        )
    except QuotaExceededError:
        raise
    except Exception as e:
        # QuotaService 故障 fail-open：配额系统故障时不阻塞主流程
        logger.warning(f"[QuotaGuard] check failed (fail-open): {e}")
        return QuotaResult(workspace_id=workspace_id)


def estimate_prompt_tokens(message: str | None) -> int:
    """粗估 prompt token 数。

    中文约 1 token/字，英文约 1 token/4 字符，保守取 len//4 + 100（最小 100）。
    仅用于配额预检，实际 usage 在 _record_usage_hook 用真实 token 数。

    Args:
        message: 用户消息文本

    Returns:
        预估 token 数（最小 100）
    """
    if not message:
        return 100
    return len(message) // 4 + 100


def enforce_chat_quota(authorization: str | None, messages) -> QuotaResult:
    """从 messages 提取最后一条文本，预检 chat 配额。

    chat 路由（chat_stream / chat）入口调用：block 超限抛 QuotaExceededError（→ 429），
    degrade 超限返回 QuotaResult(degraded=True)，匿名跳过。

    Args:
        authorization: Authorization header
        messages: ChatMessage 列表（pydantic），取最后一条 content 粗估

    Returns:
        QuotaResult（workspace_id + degraded + degrade_model_id）
    """
    msg_text = ""
    if messages:
        last = messages[-1]
        msg_text = getattr(last, "content", "") or str(last) if last else ""
    return enforce_quota(authorization, estimate_prompt_tokens(msg_text))


def get_degrade_llm(degrade_model_id: str | None):
    """按 fallback model_id 从 tb_model_config 取配置创建备用 LLM。

    Args:
        degrade_model_id: 备用模型 id（来自 QuotaResult.degrade_model_id）

    Returns:
        备用 LLM 实例；配置不存在返回 None（调用方 fallback 默认 LLM）
    """
    if not degrade_model_id:
        return None
    try:
        from infrastructure.database.repositories.model_config_repository import ModelConfigRepository
        from utils.llm.llm_factory import create_llm_from_db_config

        config = ModelConfigRepository().get_by_id(degrade_model_id)
        if config:
            logger.info(f"[QuotaGuard] degrade to fallback model: {degrade_model_id}")
            return create_llm_from_db_config(config)
        logger.warning(f"[QuotaGuard] fallback model {degrade_model_id} not found in tb_model_config")
        return None
    except Exception as e:
        logger.warning(f"[QuotaGuard] get_degrade_llm failed (fallback default): {e}")
        return None
