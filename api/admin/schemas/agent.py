"""Agent 管理相关 Pydantic schema 集中定义（从 agent_manage.py 抽出）。

向后兼容：`from api.admin.agent_manage import X` 仍可用（agent_manage.py re-export）。
"""
from typing import Any
from pydantic import BaseModel, Field


class AgentListResponse(BaseModel):
    agents: list[dict[str, Any]]
    total: int
    count: int


class AgentDetailResponse(BaseModel):
    agent: dict[str, Any]


class AgentToggleRequest(BaseModel):
    enabled: bool


class AgentApprovalRequest(BaseModel):
    """Agent 审批请求体。"""
    action: str = Field(..., description="approve / reject")
    reason: str = Field("", description="审批意见")


class SubmitReviewRequest(BaseModel):
    """提交审批请求体（version_no 后端自动生成，version_description 可选）。"""
    version_description: str = Field("", description="版本说明")

    class Config:
        populate_by_name = True


class AgentCreateRequest(BaseModel):
    """创建 Agent 的请求体（字段名用驼峰，匹配前端约定）。"""
    agent_name: str = Field(..., alias="agentName")
    system_prompt: str = Field(..., alias="systemPrompt")
    agent_description: str = Field("", alias="agentDescription")
    model_id: str = Field("", alias="modelId")
    temperature: float = 0.7
    max_tokens: int = Field(2000, alias="maxTokens")
    response_timeout: int = Field(60, alias="responseTimeout")
    visible_scope: str = Field("1", alias="visibleScope")
    release_status: str = Field("0", alias="releaseStatus", description="0=草稿 2=待审批 1=已发布")
    version_no: str = Field("1.0.0", alias="versionNo")
    skills: list[str] = []
    mcps: list[str] = []
    enabled: bool = True
    is_public: int = Field(0, alias="isPublic", description="0=空间内可见 1=跨空间公开（旧字段，由 visibility 同步）")
    visibility: str | None = Field("private", description="可见性 private/workspace/public（新建默认 private）")
    agent_config: Any = Field(None, alias="agentConfig", description="Agent 级执行配置")

    class Config:
        populate_by_name = True


class AgentUpdateRequest(BaseModel):
    """更新 Agent 的请求体（全部可选，仅传需要改的字段）。"""
    agent_description: str | None = Field(None, alias="agentDescription")
    model_id: str | None = Field(None, alias="modelId")
    system_prompt: str | None = Field(None, alias="systemPrompt")
    temperature: float | None = None
    max_tokens: int | None = Field(None, alias="maxTokens")
    skills: list[str] | None = None
    mcps: list[str] | None = None
    is_public: int | None = Field(None, alias="isPublic", description="0=空间内可见 1=跨空间公开（旧字段）")
    visibility: str | None = Field(None, description="可见性 private/workspace/public")
    agent_config: Any = Field(None, alias="agentConfig", description="Agent 级执行配置")

    class Config:
        populate_by_name = True


class MultiDispatchRequest(BaseModel):
    """多 agent 调度请求体。"""
    agent_ids: list[str] | None = Field(None, alias="agentIds", max_length=10)
    team_id: str | None = Field(None, alias="teamId", description="团队ID（与 agent_ids 二选一，展开为团队成员）")
    message: str
    mode: str = "parallel"
    tasks: list[dict[str, Any]] | None = None


class DispatchRequest(BaseModel):
    """调度请求体：可选传 test_message 执行一次测试对话。"""
    test_message: str | None = Field(None, alias="testMessage")

    class Config:
        populate_by_name = True
