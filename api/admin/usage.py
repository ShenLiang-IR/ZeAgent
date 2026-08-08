"""成本统计 + 配额管理路由。

设计参见 docs/specs/2026-07-19-usage-tracking-design.md §5。
"""

from fastapi import APIRouter, Depends, Query
from loguru import logger
from pydantic import BaseModel

from utils.common.permissions import UserPermissions

from .base import wrap_response
from .common import verify_token
from .permissions import require_read, require_write

router = APIRouter(prefix="/usage", tags=["admin"], dependencies=[Depends(verify_token)])
quota_router = APIRouter(prefix="/quota", tags=["admin"], dependencies=[Depends(verify_token)])


def _get_usage_repo():
    from infrastructure.database.repositories.usage_repository import UsageRepository
    return UsageRepository()


def _get_quota_repo():
    from infrastructure.database.repositories.usage_repository import QuotaRepository
    return QuotaRepository()


# ─── 用量查询 ───

@router.get("/workspace/{workspace_id}")
async def get_workspace_usage(
    workspace_id: int,
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    group_by: str = Query("day"),
    user_permissions: UserPermissions = Depends(require_read("usage")),
):
    """查询 workspace 用量聚合（tb_usage_record + chat messages 合并）。"""
    repo = _get_usage_repo()
    rows = repo.get_workspace_usage(workspace_id, start_date, end_date, group_by)

    # 如果 tb_usage_record 无数据，从 chat messages 聚合
    if not rows:
        rows = _get_chat_usage_stats(workspace_id)

    return wrap_response({"usage": rows, "total": len(rows)})


def _get_chat_usage_stats(workspace_id: int) -> list[dict]:
    """从 chat DB 聚合聊天 token 用量（含 workspace_id=NULL 的兼容查询）。"""
    try:
        from infrastructure.database.sessions import get_chat_session
        from sqlalchemy import text
        with get_chat_session() as session:
            rows = session.execute(text(
                "SELECT DATE(m.create_time) as date, "
                "SUM(m.prompt_tokens) as prompt_tokens, "
                "SUM(m.completion_tokens) as completion_tokens, "
                "SUM(m.prompt_tokens + m.completion_tokens) as total_tokens, "
                "COUNT(*) as msg_count "
                "FROM tb_chat_message m "
                "JOIN tb_chat_session s ON m.session_id = s.pr_key_id "
                "LEFT JOIN tb_user u ON s.user_id = u.id "
                "WHERE (s.workspace_id = :wid OR (s.workspace_id IS NULL AND u.workspace_id = :wid2)) "
                "AND m.del_flag = '0' "
                "GROUP BY DATE(m.create_time) "
                "ORDER BY date DESC LIMIT 30"
            ), {"wid": workspace_id, "wid2": workspace_id}).fetchall()
        return [
            {"date": str(r[0]) if r[0] else "", "prompt_tokens": r[1] or 0,
             "completion_tokens": r[2] or 0, "total_tokens": r[3] or 0,
             "cost_usd": 0.0, "dispatch_count": r[4] or 0}
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"chat usage stats: {e}")
        return []


@router.get("/agent/{agent_id}")
async def get_agent_usage(
    agent_id: int,
    limit: int = Query(50, ge=1, le=500),
    user_permissions: UserPermissions = Depends(require_read("usage")),
):
    """查询 agent 用量明细。"""
    # 简化：用 BaseRepository.get_all + filter
    from infrastructure.database.repositories.usage_repository import UsageRepository
    repo = UsageRepository()
    rows = repo.get_all(filters={"agent_id": agent_id}, limit=limit)
    return wrap_response({"usage": rows, "total": len(rows)})


@router.get("/dispatch/{dispatch_id}")
async def get_dispatch_usage(
    dispatch_id: str,
    user_permissions: UserPermissions = Depends(require_read("usage")),
):
    """查询单次 dispatch 用量明细。"""
    from infrastructure.database.repositories.usage_repository import UsageRepository
    repo = UsageRepository()
    rows = repo.get_all(filters={"dispatch_id": dispatch_id})
    return wrap_response({"usage": rows, "total": len(rows)})


@router.get("/pricing")
async def get_model_pricing(
    user_permissions: UserPermissions = Depends(require_read("usage")),
):
    """模型单价表（第一期硬编码，第二期查 tb_model_pricing）。"""
    from services.usage_service import MODEL_PRICING
    return wrap_response({"pricing": MODEL_PRICING})


# ─── 配额管理 ───

class QuotaCreate(BaseModel):
    workspace_id: int
    quota_type: str  # monthly_token / daily_token / monthly_cost
    limit_value: int
    period: str | None = None  # 不传则用当前 period
    over_limit_action: str = "warn"  # warn / block / degrade


@quota_router.get("/{workspace_id}")
async def get_quota_status(
    workspace_id: int,
    user_permissions: UserPermissions = Depends(require_read("usage")),
):
    """查询 workspace 配额使用情况，无记录时自动创建默认配额。"""
    from services.quota_service import QuotaService
    svc = QuotaService()
    quotas = svc.get_quota_status(workspace_id)

    # 无配额记录 → 自动创建默认配额
    if not quotas:
        defaults = [
            {"quota_type": "monthly_token", "limit_value": 1000000, "over_limit_action": "warn"},
            {"quota_type": "daily_token", "limit_value": 100000, "over_limit_action": "warn"},
            {"quota_type": "monthly_cost", "limit_value": 50, "over_limit_action": "warn"},
        ]
        for d in defaults:
            svc.create_default_quota(workspace_id, **d)
        quotas = svc.get_quota_status(workspace_id)

    return wrap_response({"quotas": quotas, "total": len(quotas)})


@quota_router.post("")
async def create_or_update_quota(
    data: QuotaCreate,
    user_permissions: UserPermissions = Depends(require_write("usage")),
):
    """创建/更新配额。"""
    from infrastructure.database.repositories.usage_repository import QuotaRepository
    from services.quota_service import QuotaService
    period = data.period or QuotaService()._current_period(data.quota_type)
    repo = QuotaRepository()
    # upsert：找现有记录，有则更新 limit_value + action，无则创建
    existing = repo.list_by_workspace(data.workspace_id)
    matched = [q for q in existing if q.get("quota_type") == data.quota_type and q.get("period") == period]
    if matched:
        pk = matched[0].get("pr_key_id")
        repo.update(pk, limit_value=data.limit_value, over_limit_action=data.over_limit_action)
        logger.info(f"[Quota] updated workspace={data.workspace_id} {data.quota_type}")
    else:
        repo.create(
            workspace_id=data.workspace_id,
            quota_type=data.quota_type,
            limit_value=data.limit_value,
            period=period,
            used_value=0,
            over_limit_action=data.over_limit_action,
            status="active",
        )
        logger.info(f"[Quota] created workspace={data.workspace_id} {data.quota_type}")
    return wrap_response({"workspace_id": data.workspace_id, "quota_type": data.quota_type}, message="配额保存成功")
