"""Prompt 模板 API：CRUD + render 插值。

设计参见 当前文档分析.md §3.8。

路径前缀 /api/admin/prompts/*：
- POST   /prompts              创建模板
- GET    /prompts              列出模板
- GET    /prompts/{name}       按名称查询
- PUT    /prompts/{pr_key_id}  更新
- POST   /prompts/render       渲染模板（传 name + variables）
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from utils.common.permissions import UserPermissions

from .base import wrap_response
from .permissions import require_read, require_write

router = APIRouter(prefix="/prompts", tags=["prompt-templates"])


class PromptTemplateCreate(BaseModel):
    name: str
    content: str
    variables: list[str] = []
    version: str = "1.0.0"
    description: str = ""
    workspace_id: int | None = None


class PromptTemplateUpdate(BaseModel):
    content: str | None = None
    variables: list[str] | None = None
    version: str | None = None
    description: str | None = None


class RenderRequest(BaseModel):
    name: str
    variables: dict = {}


@router.post("")
async def create_template(
    data: PromptTemplateCreate,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """创建 Prompt 模板。"""
    from services.prompt_template_service import PromptTemplateService

    result = PromptTemplateService().create(
        name=data.name,
        content=data.content,
        variables=data.variables,
        version=data.version,
        description=data.description,
        workspace_id=data.workspace_id,
    )
    if not result:
        raise HTTPException(status_code=500, detail="创建模板失败（名称可能已存在）")
    return wrap_response(result)


@router.get("")
async def list_templates(
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """列出启用的 Prompt 模板。"""
    from services.prompt_template_service import PromptTemplateService

    templates = PromptTemplateService().list_enabled()
    return wrap_response({"templates": templates, "total": len(templates)})


@router.get("/{name}")
async def get_template(
    name: str,
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """按名称查询模板。"""
    from services.prompt_template_service import PromptTemplateService

    template = PromptTemplateService().get_by_name(name)
    if not template:
        raise HTTPException(status_code=404, detail=f"模板 {name} 不存在")
    return wrap_response(template)


@router.put("/{pr_key_id}")
async def update_template(
    pr_key_id: int,
    data: PromptTemplateUpdate,
    user_permissions: UserPermissions = Depends(require_write("agent")),
):
    """更新模板。"""
    import json

    from services.prompt_template_service import PromptTemplateService

    kwargs = data.model_dump(exclude_none=True)
    if "variables" in kwargs:
        kwargs["variables"] = json.dumps(kwargs["variables"], ensure_ascii=False)
    result = PromptTemplateService().update(pr_key_id, **kwargs)
    if not result:
        raise HTTPException(status_code=404, detail=f"模板 {pr_key_id} 不存在")
    return wrap_response(result)


@router.post("/render")
async def render_template(
    req: RenderRequest,
    user_permissions: UserPermissions = Depends(require_read("agent")),
):
    """渲染模板：按 name 查模板 + variables 插值。"""
    from services.prompt_template_service import PromptTemplateService

    result = PromptTemplateService().render_template(req.name, req.variables)
    if result is None:
        raise HTTPException(status_code=404, detail=f"模板 {req.name} 不存在")
    return wrap_response({"rendered": result, "name": req.name})
