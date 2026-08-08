"""记忆管理 admin 路由。

对应 spec：记忆管理 REST API。路由薄，逻辑下沉到可单测的 helper（接收注入的 mm）。
端点：stats / list / get / update / delete / clear-user / recall / consolidate / cron-jobs。
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from loguru import logger
from pydantic import BaseModel

from utils.common.permissions import UserPermissions
from .base import wrap_response
from .common import verify_token
from .permissions import require_read, require_write, require_delete, require_manage
from ._error_handler import handle_admin_errors

router = APIRouter(prefix="/memory", tags=["admin-memory"], dependencies=[Depends(verify_token)])

_MEMORY_CONFIG_KEYS = (
    "memory.enabled", "memory.vector_backend", "memory.cross_session_recall",
    "memory.recency_weight", "memory.conflict_resolution", "memory.consolidation",
    "memory.decay",
)


def _get_mm():
    """获取 MemoryManager 单例（惰性 import，可被测试覆盖）。"""
    from memory import get_memory_manager
    return get_memory_manager()


async def _ensure_loaded(mm) -> None:
    """首次访问时回灌即时/短期记忆到内存（幂等），保证 admin 可见持久化数据。"""
    if hasattr(mm, "initialize") and not getattr(mm, "_tiers_loaded", True):
        try:
            await mm.initialize()
        except Exception as e:
            logger.warning(f"[Memory] initialize 回灌失败: {e}")


def _tier_obj(mm, tier: str):
    return {"immediate": mm.immediate, "short_term": mm.short_term,
            "long_term": mm.long_term}.get(tier, mm.long_term)


def _mtype_val(m) -> str:
    t = getattr(m, "type", None)
    return getattr(t, "value", str(t))


# ─── helper（可单测，接收注入 mm） ───


async def list_memories(
    mm, user_id: Optional[str] = None, session_id: Optional[str] = None,
    tier: str = "long_term", mtype: Optional[str] = None,
    q: Optional[str] = None, limit: int = 50, offset: int = 0,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    tier_obj = _tier_obj(mm, tier)
    mems = await tier_obj.get_all()
    items = []
    ql = q.lower() if q else None
    for m in mems:
        if user_id and m.user_id != user_id:
            continue
        if workspace_id and m.workspace_id != workspace_id:
            continue
        if session_id and (m.session_id or "").replace("-", "") != (session_id or "").replace("-", ""):
            continue
        if mtype and _mtype_val(m) != mtype:
            continue
        if ql and ql not in (m.content or "").lower():
            continue
        items.append(m)
    total = len(items)
    page = items[offset: offset + limit]
    return {"items": [m.to_dict() for m in page], "total": total, "count": len(page)}


async def get_memory(mm, memory_id: str, tier: str = "long_term") -> Optional[Dict[str, Any]]:
    tier_obj = _tier_obj(mm, tier)
    m = await tier_obj.get(memory_id)
    return m.to_dict() if m else None


async def update_memory(
    mm, memory_id: str, content: Optional[str] = None, importance: Optional[float] = None,
    tier: str = "long_term",
) -> bool:
    tier_obj = _tier_obj(mm, tier)
    m = await tier_obj.get(memory_id)
    if m is None:
        return False
    if content is not None:
        m.content = content
    if importance is not None:
        m.importance = max(0.0, min(1.0, importance))
    m.touch()
    await tier_obj.update(m)
    mm.invalidate_search_index()
    return True


async def delete_memory(mm, memory_id: str, tier: str = "long_term") -> bool:
    tier_obj = _tier_obj(mm, tier)
    return await tier_obj.delete(memory_id)


async def clear_user_memories(mm, user_id: str) -> int:
    return await mm.clear_user_memories(user_id)


async def trial_recall(
    mm, query: str, user_id: Optional[str] = None,
    session_id: Optional[str] = None, limit: int = 10,
) -> List[Dict[str, Any]]:
    results = await mm.recall(query=query, limit=limit, user_id=user_id, session_id=session_id)
    return [m.to_dict() for m in results]


async def run_consolidation(mm, trigger=None) -> Dict[str, Any]:
    if trigger is None:
        from services.trigger.memory_consolidation_trigger import MemoryConsolidationTrigger
        trigger = MemoryConsolidationTrigger()
    return await trigger.handle(mm=mm)


async def get_memory_stats(mm) -> Dict[str, Any]:
    return await mm.get_stats()


async def get_conflict_stats(mm, limit: int = 50) -> Dict[str, Any]:
    """聚合 long_term 记忆中 conflict_decision 冲突决策，供运维统计合并质量。

    冲突决策散落在 memory.metadata.conflict_decision（UPDATE/MERGE/NONE），
    本接口聚合 by_action 计数 + 最近合并记录（按 conflict_merged_at 倒序）。
    """
    from collections import Counter
    mems = await mm.long_term.get_all()
    conflicts = [m for m in mems if m.metadata.get("conflict_decision")]
    actions = Counter(m.metadata["conflict_decision"] for m in conflicts)
    recent = sorted(
        conflicts,
        key=lambda m: m.metadata.get("conflict_merged_at") or "",
        reverse=True,
    )[:limit]
    return {
        "total": len(conflicts),
        "by_action": dict(actions),
        "recent": [m.to_dict() for m in recent],
    }


async def list_audit(mm, workspace_id: Optional[str] = None,
                     user_id: Optional[str] = None,
                     limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """列出破坏性合并审计记录（consolidation/conflict_update/conflict_merge）。"""
    items = await mm._sqlite_storage.list_audit(
        workspace_id=workspace_id, user_id=user_id, limit=limit, offset=offset)
    return {"items": items, "count": len(items)}


async def rollback_audit(mm, op_id: str) -> Dict[str, Any]:
    """回滚一次破坏性合并：恢复保留方原内容 + 重建被删方。"""
    return await mm.rollback_audit(op_id)


def get_memory_cron_jobs() -> List[Dict[str, Any]]:
    """3 个记忆定时任务（decay/consolidation/preference_summary）状态。"""
    from utils.config import get_config
    jobs = []
    for name, key, default_cron in (
        ("memory_decay", "memory.decay", "0 3 * * *"),
        ("memory_consolidation", "memory.consolidation", "0 5 * * *"),
        ("memory_preference_summary", "memory.preference_summary", "0 4 * * *"),
    ):
        cfg = get_config(key, {}) or {}
        jobs.append({
            "name": name,
            "enabled": bool(cfg.get("enabled", False)),
            "cron": cfg.get("cron", default_cron),
        })
    return jobs


def get_memory_config_snapshot() -> Dict[str, Any]:
    from utils.config import get_config
    snap = {}
    for k in _MEMORY_CONFIG_KEYS:
        snap[k] = get_config(k, None)
    return snap


# ─── 路由（薄包装） ───


class UpdateMemoryRequest(BaseModel):
    content: Optional[str] = None
    importance: Optional[float] = None
    tier: Optional[str] = "long_term"


class RecallRequest(BaseModel):
    query: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    limit: int = 10


@router.get("/stats")
@handle_admin_errors("[Memory]", detail_with_context=True)
async def stats_endpoint(user_permissions: UserPermissions = Depends(require_read("memory"))):
    mm = _get_mm()
    await _ensure_loaded(mm)
    data = {
        "stats": await get_memory_stats(mm),
        "cron_jobs": get_memory_cron_jobs(),
        "config": get_memory_config_snapshot(),
    }
    return wrap_response(data)


@router.get("/conflicts")
@handle_admin_errors("[Memory]", detail_with_context=True)
async def conflicts_endpoint(
    limit: int = Query(50, ge=1, le=500),
    user_permissions: UserPermissions = Depends(require_read("memory")),
):
    mm = _get_mm()
    await _ensure_loaded(mm)
    return wrap_response(await get_conflict_stats(mm, limit=limit))


@router.get("/audit")
@handle_admin_errors("[Memory]", detail_with_context=True)
async def audit_list_endpoint(
    workspace_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user_permissions: UserPermissions = Depends(require_read("memory")),
):
    mm = _get_mm()
    return wrap_response(await list_audit(mm, workspace_id=workspace_id,
                                          user_id=user_id, limit=limit, offset=offset))


@router.post("/audit/{op_id}/rollback")
@handle_admin_errors("[Memory]", detail_with_context=True)
async def audit_rollback_endpoint(
    op_id: str,
    user_permissions: UserPermissions = Depends(require_write("memory")),
):
    mm = _get_mm()
    r = await rollback_audit(mm, op_id)
    if not r.get("ok"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=r.get("reason", "回滚失败"))
    logger.info(f"[Memory] {user_permissions.user_id} 回滚审计 {op_id}: {r}")
    return wrap_response(r)


@router.get("/cron-jobs")
@handle_admin_errors("[Memory]", detail_with_context=True)
async def cron_jobs_endpoint(
    user_permissions: UserPermissions = Depends(require_read("memory")),
):
    return wrap_response({"jobs": get_memory_cron_jobs()})


@router.get("/recall-stats")
@handle_admin_errors("[Memory]", detail_with_context=True)
async def recall_stats_endpoint(
    user_permissions: UserPermissions = Depends(require_read("memory")),
):
    """recall 效果统计（total/hits/fallback/by_tier），观测召回质量。"""
    mm = _get_mm()
    return wrap_response(mm.get_recall_stats())


@router.get("/list")
@handle_admin_errors("[Memory]", detail_with_context=True)
async def list_endpoint(
    user_id: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    tier: str = Query("long_term"),
    mtype: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user_permissions: UserPermissions = Depends(require_read("memory")),
):
    mm = _get_mm()
    await _ensure_loaded(mm)
    r = await list_memories(mm, user_id=user_id, session_id=session_id, tier=tier,
                            mtype=mtype, q=q, limit=limit, offset=offset,
                            workspace_id=workspace_id)
    return wrap_response(r)


@router.get("/{memory_id}")
@handle_admin_errors("[Memory]", detail_with_context=True)
async def get_endpoint(
    memory_id: str,
    tier: str = Query("long_term"),
    user_permissions: UserPermissions = Depends(require_read("memory")),
):
    mm = _get_mm()
    await _ensure_loaded(mm)
    m = await get_memory(mm, memory_id, tier=tier)
    if m is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"记忆不存在: {memory_id}")
    return wrap_response(m)


@router.put("/{memory_id}")
@handle_admin_errors("[Memory]", detail_with_context=True)
async def update_endpoint(
    memory_id: str,
    body: UpdateMemoryRequest,
    user_permissions: UserPermissions = Depends(require_write("memory")),
):
    mm = _get_mm()
    await _ensure_loaded(mm)
    ok = await update_memory(mm, memory_id, content=body.content,
                             importance=body.importance, tier=body.tier or "long_term")
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"记忆不存在: {memory_id}")
    logger.info(f"[Memory] {user_permissions.user_id} 更新记忆 {memory_id}(tier={body.tier})")
    return wrap_response(message="记忆已更新")


@router.delete("/{memory_id}")
@handle_admin_errors("[Memory]", detail_with_context=True)
async def delete_endpoint(
    memory_id: str,
    tier: str = Query("long_term"),
    user_permissions: UserPermissions = Depends(require_delete("memory")),
):
    mm = _get_mm()
    await _ensure_loaded(mm)
    ok = await delete_memory(mm, memory_id, tier=tier)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"记忆不存在: {memory_id}")
    logger.info(f"[Memory] {user_permissions.user_id} 删除记忆 {memory_id}(tier={tier})")
    return wrap_response(message="记忆已删除")


@router.delete("/user/{user_id}")
@handle_admin_errors("[Memory]", detail_with_context=True)
async def clear_user_endpoint(
    user_id: str,
    user_permissions: UserPermissions = Depends(require_delete("memory")),
):
    mm = _get_mm()
    n = await clear_user_memories(mm, user_id)
    logger.info(f"[Memory] {user_permissions.user_id} 清理用户 {user_id} 记忆 {n} 条")
    return wrap_response({"deleted": n})


@router.post("/recall")
@handle_admin_errors("[Memory]", detail_with_context=True)
async def recall_endpoint(
    body: RecallRequest,
    user_permissions: UserPermissions = Depends(require_read("memory")),
):
    mm = _get_mm()
    r = await trial_recall(mm, query=body.query, user_id=body.user_id,
                           session_id=body.session_id, limit=body.limit)
    return wrap_response({"results": r, "count": len(r)})


@router.post("/consolidate")
@handle_admin_errors("[Memory]", detail_with_context=True)
async def consolidate_endpoint(
    user_permissions: UserPermissions = Depends(require_manage("memory")),
):
    mm = _get_mm()
    r = await run_consolidation(mm)
    logger.info(f"[Memory] {user_permissions.user_id} 手动触发合并: {r}")
    return wrap_response(r)
