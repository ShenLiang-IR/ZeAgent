"""Agent 团队协作 API：团队 CRUD + Agent 邮箱。

设计参见 docs/specs/2026-07-19-team-collaboration-design.md（G2-G4 解冻）。

路径前缀 /api/admin/teams/* + /api/admin/mailbox/*：
- POST   /teams                      创建团队
- GET    /teams                      列出团队
- GET    /teams/{team_id}            查询团队
- POST   /teams/{team_id}/members    添加成员
- GET    /teams/{team_id}/members    取成员 agent_ids（dispatch by team 用）
- POST   /mailbox/send               Agent 发消息
- GET    /mailbox/poll                Agent 拉消息
- POST   /mailbox/ack/{message_id}   确认消息
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from pydantic import BaseModel

from utils.common.permissions import UserPermissions
from utils.common.auth_dependencies import get_workspace_id_from_auth_header

from .base import wrap_response
from .permissions import require_read, require_write

router = APIRouter(prefix="/teams", tags=["agent-teams"])


class TeamCreateRequest(BaseModel):
    name: str
    members: list[dict] = []  # [{agent_id, role}]
    workspace_id: int | None = None
    description: str = ""
    visibility: str | None = "private"  # 可见性 private/workspace/public（新建默认 private）


class AddMemberRequest(BaseModel):
    agent_id: str
    role: str = "member"


class SendMessageRequest(BaseModel):
    from_agent: str
    to_agent: str
    content: str
    team_id: str | None = None
    msg_type: str = "text"
    workspace_id: int | None = None


@router.post("")
async def create_team(
    req: TeamCreateRequest,
    authorization: str | None = Header(None),
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """创建 Agent 团队（记录创建者 + 可见性）。"""
    from services.agent_team_service import AgentTeamService
    creator_id = int(user_permissions.user_id) if str(user_permissions.user_id).isdigit() else None
    workspace_id = req.workspace_id if req.workspace_id is not None else get_workspace_id_from_auth_header(authorization)
    result = AgentTeamService().create_team(
        name=req.name, members=req.members,
        workspace_id=workspace_id, description=req.description,
        visibility=req.visibility, creator_id=creator_id,
    )
    if not result:
        raise HTTPException(status_code=500, detail="创建团队失败")
    return wrap_response(result)


@router.get("")
async def list_teams(
    workspace_id: int | None = Query(None),
    authorization: str | None = Header(None),
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """列出团队（admin 全可见；否则按三层可见性过滤）。"""
    from services.agent_team_service import AgentTeamService
    from utils.common.visibility import can_read_object
    teams = AgentTeamService().list_teams(workspace_id)
    if not user_permissions.has_role("admin"):
        cur_uid = int(user_permissions.user_id) if str(user_permissions.user_id).isdigit() else None
        cur_ws = workspace_id if workspace_id is not None else get_workspace_id_from_auth_header(authorization)
        teams = [
            t for t in teams
            if can_read_object(
                t.get("visibility") or "workspace",
                t.get("creator_id"), t.get("workspace_id"),
                cur_uid, cur_ws, is_admin=False,
            )
        ]
    return wrap_response({"teams": teams, "total": len(teams)})


@router.get("/{team_id}")
async def get_team(
    team_id: str,
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """查询团队。"""
    from services.agent_team_service import AgentTeamService
    team = AgentTeamService().get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"团队 {team_id} 不存在")
    return wrap_response(team)


@router.post("/{team_id}/members")
async def add_member(
    team_id: str,
    req: AddMemberRequest,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """向团队添加成员。"""
    from services.agent_team_service import AgentTeamService
    result = AgentTeamService().add_member(team_id, req.agent_id, req.role)
    if not result:
        raise HTTPException(status_code=404, detail=f"团队 {team_id} 不存在")
    return wrap_response(result)


@router.get("/{team_id}/members")
async def get_members(
    team_id: str,
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """取团队成员 agent_id 列表（dispatch by team 用）。"""
    from services.agent_team_service import AgentTeamService
    agent_ids = AgentTeamService().get_member_agent_ids(team_id)
    return wrap_response({"agent_ids": agent_ids, "total": len(agent_ids)})


# ===== Agent 邮箱 =====
mailbox_router = APIRouter(prefix="/mailbox", tags=["agent-mailbox"])


@mailbox_router.post("/send")
async def send_message(
    req: SendMessageRequest,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """Agent 向另一个 Agent 发消息。"""
    from services.agent_team_service import AgentTeamService
    result = AgentTeamService().send_message(
        from_agent=req.from_agent, to_agent=req.to_agent, content=req.content,
        team_id=req.team_id, msg_type=req.msg_type, workspace_id=req.workspace_id,
    )
    if not result:
        raise HTTPException(status_code=500, detail="发送失败")
    return wrap_response(result)


@mailbox_router.get("/poll")
async def poll_messages(
    agent_name: str = Query(..., description="拉取该 agent 的待处理消息"),
    limit: int = Query(50, ge=1, le=200),
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """Agent 拉取自己的待处理消息。"""
    from services.agent_team_service import AgentTeamService
    messages = AgentTeamService().poll_messages(agent_name, limit)
    return wrap_response({"messages": messages, "total": len(messages)})


@mailbox_router.post("/ack/{message_id}")
async def ack_message(
    message_id: str,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """确认消息（pending→acked）。"""
    from services.agent_team_service import AgentTeamService
    if not AgentTeamService().ack_message(message_id):
        raise HTTPException(status_code=404, detail=f"消息 {message_id} 不存在")
    return wrap_response({"success": True, "message": f"消息 {message_id} 已确认"})
