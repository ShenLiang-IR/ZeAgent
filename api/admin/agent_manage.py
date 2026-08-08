from typing import Optional
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from loguru import logger

from infrastructure.database.repositories.agent_repository import AgentRepository
from services.agent_crud_service import AgentCrudService
from services.agent_version_service import AgentVersionService
from utils.common.permissions import UserPermissions
from utils.common.visibility import can_read_object, can_modify_object

from ._error_handler import handle_admin_errors
from .permissions import require_delete, require_read, require_write
from .base import wrap_response
from .schemas.agent import (
    AgentListResponse,
    AgentDetailResponse,
    AgentToggleRequest,
    AgentApprovalRequest,
    SubmitReviewRequest,
    AgentCreateRequest,
    AgentUpdateRequest,
    MultiDispatchRequest,
    DispatchRequest,
)

router = APIRouter(prefix="/agents", tags=["agents"])


def _extract_workspace_id(request: Request) -> int | None:
    """从请求 token 提取 workspace_id，失败返回 None。"""
    auth = request.headers.get("Authorization", "")
    if not auth:
        return None
    try:
        from services.auth_service import AuthService
        payload = AuthService().verify_token(auth)
        if payload:
            return payload.get("workspace_id")
    except Exception:
        pass
    return None


def _extract_viewer(request: Request, user_permissions: UserPermissions = None):
    """从 token/permissions 提取 (user_id, workspace_id, is_admin)。

    优先用传入的 user_permissions（避免重复解析 JWT）；未传时自行解析。
    """
    is_admin = False
    uid = None
    if user_permissions:
        is_admin = user_permissions.has_role("admin")
        if str(user_permissions.user_id).isdigit():
            uid = int(user_permissions.user_id)
    ws = _extract_workspace_id(request)
    return uid, ws, is_admin


# ── 编辑变更检测（审批=发布 主线）：编辑已发布/待审批 agent 有改动 → 回草稿 ──
# 传入字段名 → DB 现值字段名 的映射（skills/mcps 在 DB 是 tools/mcp_tools）
_EDIT_FIELD_MAP = {
    "agent_description": "agent_description",
    "model_id": "model_id",
    "system_prompt": "system_prompt",
    "temperature": "temperature",
    "max_tokens": "max_tokens",
    "is_public": "is_public",
    "visibility": "visibility",
    "agent_config": "agent_config",
    "skills": "tools",
    "mcps": "mcp_tools",
}


def _has_content_changed(data: dict, existing: dict) -> bool:
    """对比传入字段与 DB 现值，判断是否有内容变更。

    列表字段（skills/mcps）顺序无关；agent_config 做 JSON 归一化对比。
    """
    import json as _json
    for data_key, db_key in _EDIT_FIELD_MAP.items():
        if data_key not in data:
            continue
        new_val = data[data_key]
        old_val = existing.get(db_key)
        if data_key in ("skills", "mcps"):
            if set(new_val or []) != set(old_val or []):
                return True
        elif data_key == "agent_config":
            new_norm = _json.dumps(new_val, ensure_ascii=False, default=str) if isinstance(new_val, (dict, list)) else new_val
            old_norm = old_val
            if isinstance(old_val, str):
                try:
                    old_norm = _json.dumps(_json.loads(old_val), ensure_ascii=False, default=str)
                except Exception:
                    pass
            if str(new_norm) != str(old_norm):
                return True
        else:
            if new_val != old_val:
                return True
    return False


@router.get("/list", response_model=AgentListResponse)
@handle_admin_errors(" Agent", detail_with_context=True)
async def list_agents(
    request: Request,
    user_permissions: UserPermissions = Depends(require_read("agent")),
    skip: int = Query(0, ge=0, description=""),
    limit: int = Query(10, ge=1, le=100, description=""),
    search: str = Query("", description=""),
    app: str = Query("", description=""),
    enabled: bool | None = Query(None, description=""),
    workspace_id: int | None = Query(None, description="按工作空间筛选（仅 admin 有效，覆盖当前空间；None=全部空间）"),
):
    repo = AgentRepository()
    is_admin = user_permissions.has_role("admin")
    if is_admin:
        # admin：用 query 的 workspace_id 覆盖（None=全部空间，传值=该空间 OR 公开）
        ws_filter = workspace_id
        # DB 级过滤 + 分页（admin 保留空间过滤，不做可见性限制）
        all_agents, total = repo.list_agents(
            workspace_id=ws_filter,
            creator_id=None,
            search=search,
            app=app,
            enabled=enabled,
            offset=skip,
            limit=limit,
        )
    else:
        # 普通用户：三层可见性过滤（public + 同空间 workspace + 自己的 private）
        ws_filter = _extract_workspace_id(request)
        if ws_filter is None:
            return AgentListResponse(agents=[], total=0, count=0)
        cur_uid = int(user_permissions.user_id) if str(user_permissions.user_id).isdigit() else None
        all_agents, total = repo.list_agents(
            viewer_user_id=cur_uid,
            viewer_workspace_id=ws_filter,
            is_admin=False,
            search=search,
            app=app,
            enabled=enabled,
            offset=skip,
            limit=limit,
        )
    return AgentListResponse(
        agents=list(all_agents),  # 确保 JSON 序列化
        total=total,
        count=len(all_agents),
    )


@router.get("/selections")
@handle_admin_errors(" selections", detail_with_context=False)
async def get_selections(
    request: Request,
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """返回前端选择器所需的可选项：内置 tools / skills / mcps。

    非 admin 时按三层可见性过滤——普通用户只看到本空间可见的 skill/mcp。
    """
    is_admin = user_permissions.has_role("admin")
    ws = _extract_workspace_id(request)
    uid = int(user_permissions.user_id) if str(user_permissions.user_id).isdigit() else None
    service = AgentCrudService()
    return service.get_selections(
        viewer_user_id=uid, viewer_workspace_id=ws, is_admin=is_admin,
    )


@router.post("/dispatch-multi")
async def dispatch_multi(
    req: MultiDispatchRequest,
    user_permissions: UserPermissions = Depends(require_read("agent")),
    authorization: str | None = Header(None),
):
    """多 agent 并行调度，SSE 流式返回各 agent 输出。"""
    # 配额预检：超限抛 QuotaExceededError（→ 429）；degrade 返回 degraded 信号（记录，第二期深入切模型）
    from services.quota_guard import enforce_quota, estimate_prompt_tokens
    quota_result = enforce_quota(authorization, estimate_prompt_tokens(req.message))
    if quota_result.degraded:
        logger.info(f"[dispatch-multi] quota degraded, fallback_model={quota_result.degrade_model_id}")
    from fastapi.responses import StreamingResponse

    from api.chat.sse_utils import send_sse_data
    from services.multi_agent_service import MultiAgentService
    service = MultiAgentService()

    async def generate():
        try:
            async for ev in service.dispatch_stream(
                agent_ids=req.agent_ids or [],
                message=req.message,
                mode=req.mode,
                tasks=req.tasks,
                degrade_model_id=quota_result.degrade_model_id,
                team_id=req.team_id,
            ):
                yield send_sse_data(ev)
        except Exception as e:
            logger.error(f"[dispatch-multi] {e}", exc_info=True)
            yield send_sse_data({"type": "error", "data": str(e)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/dispatch-tasks")
async def list_dispatch_tasks(
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """查询历史调度记录（三期持久化，进程重启可查）。"""
    from services.multi_agent_service import MultiAgentService
    service = MultiAgentService()
    return {"records": service.list_dispatch_records(limit=20)}


# ── 静态 GET 路由必须在 /{agent_id} 动态路由之前注册 ──
# 否则 GET /pending-reviews、/my-submissions 会被 /{agent_id} 当作 agent_id 吞掉 → 404
def _join_version_info(agents: list) -> list:
    """给 agent 列表 join 当前版本号 + 说明（rs=2→pending_review, rs=1→published）。"""
    try:
        from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository
        vrepo = AgentVersionRepository()
        for a in agents:
            aid = a.get("pr_key_id")
            if aid is None:
                continue
            v = None
            rs = str(a.get("release_status", ""))
            if rs == "2":
                v = vrepo.get_pending(int(aid))
            elif rs == "1":
                v = vrepo.get_published(int(aid))
            if v:
                a["version_no"] = v.get("version_no")
                a["version_description"] = v.get("version_description")
    except Exception as e:
        logger.warning(f"[Agent] join version info failed: {e}")
    return agents


# （规范：.joyincode/rules/backend.md §路由前缀）
@router.get("/pending-reviews")
async def list_pending_reviews(
    request: Request,
    user_permissions: UserPermissions = Depends(require_read("agent"))
):
    """列出待审批的 Agent（release_status=2），含 pending_review 版本号。"""
    repo = AgentRepository()
    pending = repo.get_all(release_status="2")
    _join_version_info(pending)
    return {"list": pending, "total": len(pending)}


@router.get("/my-submissions")
async def list_my_submissions(
    request: Request,
    status: Optional[str] = Query(None, description="按 release_status 筛选: 0=已拒绝, 1=已通过, 2=待审批"),
    user_permissions: UserPermissions = Depends(require_read("agent"))
):
    """查询当前用户提交的审批记录。支持 ?status=2 筛选待审批项。"""
    user_id = user_permissions.user_id
    try:
        creator_id = int(user_id) if str(user_id).isdigit() else None
    except (ValueError, TypeError):
        creator_id = None
    if creator_id is None:
        return {"list": [], "total": 0}
    repo = AgentRepository()
    # strict_creator=True：只看自己的，不加 OR is_public==1
    # 按 status 筛选：逗号分隔多值（如 ?status=0,1,2）→ 逐个查 DB；单值直接下推 SQL
    status_val = status.replace(" ", "") if status else None
    if status_val and "," not in status_val:
        items = repo.get_all(creator_id=creator_id, strict_creator=True, release_status=status_val)
    else:
        items = repo.get_all(creator_id=creator_id, strict_creator=True)
        if status_val:
            status_set = set(status_val.split(","))
            items = [a for a in items if str(a.get("release_status", "")) in status_set]
    items.sort(key=lambda a: a.get("pr_key_id", ""), reverse=True)
    _join_version_info(items)
    return {"list": items, "total": len(items)}


@router.get("/{agent_id}", response_model=AgentDetailResponse)
async def get_agent(
    agent_id: str,
    request: Request,
    user_permissions: UserPermissions = Depends(require_read("agent"))
):
    try:
        repo = AgentRepository()
        agent = repo.get_by_id(agent_id, return_dict=True)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent: {agent_id}")
        # 三层可见性读校验
        uid, ws, is_admin = _extract_viewer(request, user_permissions)
        if not can_read_object(
            agent.get("visibility") or "", agent.get("creator_id"),
            agent.get("workspace_id"), uid, ws, is_admin,
        ):
            raise HTTPException(status_code=403, detail="无权访问该 Agent")
        return AgentDetailResponse(agent=agent)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f" Agent : {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f" Agent : {str(e)}")


@router.post("/{agent_id}/submit-review")
async def submit_for_review(
    agent_id: str,
    request: Request,
    req: Optional[SubmitReviewRequest] = None,
    user_permissions: UserPermissions = Depends(require_write("agent"))
):
    """提交审批：冻结工作副本为 pending_review 版本。release_status: 草稿(0) → 待审批(2)。"""
    repo = AgentRepository()
    agent = repo.get_by_id(agent_id, return_dict=True)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent: {agent_id}")
    current = agent.get("release_status") or "0"
    if current == "1":
        raise HTTPException(status_code=400, detail="该 Agent 已发布，无需再次审批")
    if current == "2":
        raise HTTPException(status_code=400, detail="该 Agent 已在审批中，请先撤回或等待审批结果")
    # 生成下一版本号 + 拍快照生成 pending_review 版本（version_no 自动，description 可选）
    svc = AgentVersionService()
    version_no = svc.next_version_no(int(agent_id), agent.get("version_no"))
    desc = req.version_description if req else ""
    version = svc.create_pending_submission(int(agent_id), version_no, desc)
    if not version:
        raise HTTPException(status_code=500, detail="创建审批版本失败")
    repo.update(agent_id, release_status="2")
    logger.info(f"[Agent] 提交审批: {agent_id}, version={version_no}")
    # WebSocket 通知 admin
    try:
        import asyncio
        from api.ws_approvals import notify_new_submission
        asyncio.create_task(notify_new_submission(
            agent_id, agent.get("agent_name", agent_id),
            str(user_permissions.username or user_permissions.user_id)
        ))
    except Exception:
        pass
    return wrap_response(data={"version_no": version_no}, message="已提交审批")


@router.post("/{agent_id}/approve")
async def approve_agent(
    agent_id: str,
    req: AgentApprovalRequest,
    request: Request,
    user_permissions: UserPermissions = Depends(require_write("agent"))
):
    """审批 Agent（需 admin）。approve → 发布 pending 版本，reject → 驳回回草稿。"""
    if not user_permissions.has_role("admin"):
        raise HTTPException(status_code=403, detail="仅管理员可审批")
    repo = AgentRepository()
    agent = repo.get_by_id(agent_id, return_dict=True)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent: {agent_id}")
    svc = AgentVersionService()
    if req.action == "approve":
        result = svc.publish_pending(int(agent_id))
        if not result:
            raise HTTPException(status_code=400, detail="无待审批版本或已被作废")
        logger.info(f"[Agent] 审批通过: {agent_id}")
        ws_status = "approved"
        result_msg = wrap_response(message="已审批通过并发布")
    elif req.action == "reject":
        result = svc.reject_pending(int(agent_id), req.reason)
        if not result:
            raise HTTPException(status_code=400, detail="无待审批版本或已被作废")
        logger.info(f"[Agent] 审批拒绝: {agent_id}, reason={req.reason}")
        ws_status = "rejected"
        result_msg = wrap_response(message=f"已拒绝: {req.reason}")
    else:
        raise HTTPException(status_code=400, detail=f"无效操作: {req.action}")
    # 审批结果改变 agent 生效配置 → 清 plan 缓存
    from utils.planning.generator import clear_plan_cache
    clear_plan_cache()
    # WebSocket 通知提交人
    creator_id = agent.get("creator_id")
    if creator_id:
        try:
            import asyncio
            from api.ws_approvals import notify_approval_result
            asyncio.create_task(notify_approval_result(
                str(creator_id), agent_id,
                agent.get("agent_name", agent_id), ws_status,
                reason=req.reason if req.action == "reject" else ""
            ))
        except Exception:
            pass
    return result_msg


@router.patch("/{agent_id}/toggle")
async def toggle_agent(
    agent_id: str,
    req: AgentToggleRequest,
    request: Request,
    user_permissions: UserPermissions = Depends(require_write("agent"))
):
    try:
        repo = AgentRepository()
        agent = repo.get_by_id(agent_id, return_dict=True)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent: {agent_id}")
        # 三层可见性修改校验
        uid, ws, is_admin = _extract_viewer(request, user_permissions)
        if not can_modify_object(
            agent.get("visibility") or "", agent.get("creator_id"),
            agent.get("workspace_id"), uid, ws, is_admin,
        ):
            raise HTTPException(status_code=403, detail="无权修改该 Agent")
        new_status = '1' if req.enabled else '0'
        repo.update(agent_id, status=new_status)
        logger.info(f" Agent : {agent_id}, enabled={req.enabled}")
        return {
            "message": f"Agent {'' if req.enabled else ''}",
            "status": "success",
            "enabled": req.enabled
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f" Agent : {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f" Agent : {str(e)}")


@router.get("/apps/list")
async def list_apps(
    user_permissions: UserPermissions = Depends(require_read("agent"))
):
    apps = [
        {"id": "intelligent_qa", "name": ""},
        {"id": "intelligent_writing", "name": ""},
        {"id": "intelligent_assistant", "name": ""}
    ]
    return {"apps": apps}


@router.post("/create")
async def create_agent(
    req: AgentCreateRequest,
    authorization: Optional[str] = Header(None),
    user_permissions: UserPermissions = Depends(require_write("agent"))
):
    """创建 Agent + 绑定 Skills/MCP。多租户：从 token 提取 creator_id/workspace_id。"""
    creator_id = None
    workspace_id = None
    try:
        from services.auth_service import AuthService
        if authorization:
            payload = AuthService().verify_token(authorization)
            if payload:
                creator_id = payload.get("user_id")
                workspace_id = payload.get("workspace_id")
    except Exception:
        pass
    try:
        service = AgentCrudService()
        agent = service.create(
            agent_name=req.agent_name,
            system_prompt=req.system_prompt,
            agent_description=req.agent_description or "",
            model_id=req.model_id or "",
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            response_timeout=req.response_timeout,
            visible_scope=req.visible_scope,
            release_status=req.release_status,
            version_no=req.version_no,
            skills=req.skills,
            mcps=req.mcps,
            enabled=req.enabled,
            is_public=req.is_public,
            visibility=req.visibility,
            creator_id=creator_id,
            workspace_id=workspace_id,
            is_admin=user_permissions.has_role("admin"),
            agent_config=json.dumps(req.agent_config) if isinstance(req.agent_config, dict) else req.agent_config,
        )
        from utils.planning.generator import clear_plan_cache
        clear_plan_cache()
        return wrap_response(data={"agent": agent})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f" Agent: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{agent_id}")
async def update_agent(
    agent_id: str,
    req: AgentUpdateRequest,
    authorization: Optional[str] = Header(None),
    user_permissions: UserPermissions = Depends(require_write("agent"))
):
    """更新 Agent 基本信息 + 重新绑定 Skills/MCP（传了才改）。"""
    viewer_user_id = None
    viewer_workspace_id = None
    try:
        from services.auth_service import AuthService
        if authorization:
            payload = AuthService().verify_token(authorization)
            if payload:
                viewer_user_id = payload.get("user_id")
                viewer_workspace_id = payload.get("workspace_id")
    except Exception:
        pass
    # 三层可见性修改校验
    is_admin_flag = user_permissions.has_role("admin")
    repo_check = AgentRepository()
    existing = repo_check.get_by_id(agent_id, return_dict=True)
    if existing and not can_modify_object(
        existing.get("visibility") or "", existing.get("creator_id"),
        existing.get("workspace_id"), viewer_user_id, viewer_workspace_id, is_admin_flag,
    ):
        raise HTTPException(status_code=403, detail="无权修改该 Agent")
    try:
        service = AgentCrudService()
        data = req.model_dump(exclude_none=True, by_alias=False)
        # 安全：禁止通过 update 绕过审批流程修改 release_status（前端直接传值）
        data.pop("release_status", None)
        # 审批=发布主线：已发布/待审批 agent 编辑有改动 → 回草稿
        revert_to_draft = False
        if existing:
            cur = existing.get("release_status") or "0"
            if cur in ("1", "2") and _has_content_changed(data, existing):
                data["release_status"] = "0"
                revert_to_draft = True
        data["viewer_user_id"] = viewer_user_id
        data["viewer_workspace_id"] = viewer_workspace_id
        data["is_admin"] = is_admin_flag
        ok = service.update(agent_id, **data)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Agent: {agent_id}")
        # 待审批被编辑 → 作废 pending 版本（防止遗留 stale 审批）
        if revert_to_draft and existing and (existing.get("release_status") or "0") == "2":
            AgentVersionService().invalidate_pending(int(agent_id))
        from utils.planning.generator import clear_plan_cache
        clear_plan_cache()
        return wrap_response(message="Agent 更新成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f" Agent: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    request: Request,
    user_permissions: UserPermissions = Depends(require_delete("agent"))
):
    """软删 Agent + 清理关系。"""
    try:
        repo = AgentRepository()
        agent = repo.get_by_id(agent_id, return_dict=True)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent: {agent_id}")
        # 三层可见性删除校验
        uid, ws, is_admin = _extract_viewer(request, user_permissions)
        if not can_modify_object(
            agent.get("visibility") or "", agent.get("creator_id"),
            agent.get("workspace_id"), uid, ws, is_admin,
        ):
            raise HTTPException(status_code=403, detail="无权删除该 Agent")
        service = AgentCrudService()
        ok = service.delete(agent_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Agent: {agent_id}")
        from utils.planning.generator import clear_plan_cache
        clear_plan_cache()
        return wrap_response(message="Agent 已删除")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f" Agent: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def build_dispatch_detail(agent_id: str, test_message: str | None = None) -> dict:
    """构建 agent 调度详情：加载的工具列表（分类）+ agent 信息 + 可选执行结果。

    返回 { before: {...}, execution?: {...}, final: {...} }
    """
    repo = AgentRepository()
    cfg = repo.get_by_id(agent_id)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Agent 不存在: {agent_id}")
    from core.builder.tool_collector import collect_subagent_tools_async
    tools, _, skill_ids = await collect_subagent_tools_async(
        cfg, cfg.get("pr_key_id"), return_skill_ids=True
    )
    tool_list = []
    for t in tools:
        meta = getattr(t, "metadata", None) or {}
        cat = meta.get("tool_category", "unknown") if isinstance(meta, dict) else "unknown"
        tool_list.append({
            "name": getattr(t, "name", str(t)),
            "category": cat,
            "description": (getattr(t, "description", "") or "")[:120],
        })
    result = {
        "before": {
            "agent_id": cfg.get("pr_key_id"),
            "agent_name": cfg.get("agent_name"),
            "system_prompt": cfg.get("system_prompt", ""),
            "model_id": cfg.get("model_id", ""),
            "temperature": cfg.get("temperature"),
            "max_tokens": cfg.get("max_tokens"),
            "tools": tool_list,
            "skills": cfg.get("tools", []),
            "mcp_tools": cfg.get("mcp_tools", []),
            "external_tools": cfg.get("external_tools", []),
            "skill_ids": skill_ids,
        },
        "final": {
            "summary": f"已加载 {len(tool_list)} 个工具（{len(skill_ids)} 个 skill 绑定），未执行测试消息",
            "tools_count": len(tool_list),
        },
    }
    if test_message:
        try:
            from langchain_core.messages import HumanMessage

            from core.builder import build_graph
            from utils.message.extract import extract_final_output
            graph = await build_graph(subagent_name=cfg.get("agent_name"))
            if graph:
                res = await graph.ainvoke({"messages": [HumanMessage(content=test_message)]})
                output = extract_final_output(res) or ""
                # 提取执行中的工具调用记录（AIMessage.tool_calls + ToolMessage）
                from langchain_core.messages import AIMessage as _AIMsg
                from langchain_core.messages import ToolMessage as _ToolMsg
                steps = []
                _msgs = res.get("messages", []) if isinstance(res, dict) else []
                for _m in _msgs:
                    if isinstance(_m, _AIMsg):
                        for _tc in (getattr(_m, "tool_calls", None) or []):
                            steps.append({
                                "type": "tool_call",
                                "name": _tc.get("name", ""),
                                "detail": str(_tc.get("args", {}))[:300],
                            })
                    elif isinstance(_m, _ToolMsg):
                        steps.append({
                            "type": "tool_result",
                            "name": getattr(_m, "name", ""),
                            "detail": str(getattr(_m, "content", ""))[:300],
                        })
                result["execution"] = {"test_message": test_message, "response": output, "steps": steps}
                result["final"] = {
                    "summary": f"执行完成，加载 {len(tool_list)} 工具，调用 {len(steps)} 次工具，回复 {len(output)} 字符",
                    "tools_count": len(tool_list),
                    "steps_count": len(steps),
                    "response_length": len(output),
                }
            else:
                result["execution"] = {"error": "graph 构建失败"}
                result["final"] = {"summary": "执行失败：graph 构建失败", "tools_count": len(tool_list)}
        except Exception as e:
            result["execution"] = {"error": str(e)}
            result["final"] = {"summary": f"执行失败: {e}", "tools_count": len(tool_list)}
    return result


@router.post("/{agent_id}/dispatch")
async def dispatch_agent(
    agent_id: str,
    req: DispatchRequest | None = None,
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """调度 Agent：返回加载的 tools/skills/mcp 详情，可选传 testMessage 执行一次。"""
    try:
        test_msg = req.test_message if req else None
        return await build_dispatch_detail(agent_id, test_msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"dispatch Agent: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
