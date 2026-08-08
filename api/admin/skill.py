from ._error_handler import handle_admin_errors
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query, Request, Depends
from pydantic import BaseModel, Field
from loguru import logger
from infrastructure.database.repositories.skill_repository import SkillRepository
from infrastructure.database.repositories.agent_relation_repository import AgentRelationRepository
from infrastructure.database.models.agent import AgentRelation
from domain.skill.registry import get_skill_registry, reset_skill_registry
from domain.skill.entities import SkillCategory
from utils.common.auth_dependencies import get_workspace_id_from_auth_header, get_current_user_permissions
from utils.common.visibility import can_read_object, can_modify_object
from .common import verify_token
router = APIRouter(prefix="/skills", tags=["skills"], dependencies=[Depends(verify_token)])


def _extract_viewer(request: Request):
    """从 token 提取 (user_id, workspace_id, is_admin)。"""
    auth = request.headers.get("Authorization", "")
    is_admin = False
    uid = None
    try:
        perms = get_current_user_permissions(auth)
        is_admin = perms.has_role("admin")
        if str(perms.user_id).isdigit():
            uid = int(perms.user_id)
    except Exception:
        pass
    ws = get_workspace_id_from_auth_header(auth)
    return uid, ws, is_admin
class SkillParameterModel(BaseModel):
    param_name: str = Field(..., description="")
    param_type: str = Field(..., description="string, integer, number, boolean, array, object")
    param_desc: str = Field("", description="")
    required: bool = Field(False, description="")
    default_value: Any = Field(None, description="")
class SkillCreateModel(BaseModel):
    skill_id: str = Field(..., description="ID")
    skill_name: str = Field(..., description="")
    skill_desc: str = Field("", description="")
    category: str = Field("general", description="")
    module_path: str = Field("", description="")
    class_name: str = Field("", description="")
    function_name: str = Field("", description="class_name")
    lazy_load: bool = Field(True, description="")
    preload_priority: int = Field(0, description="")
    enabled: bool = Field(True, description="")
    visibility: str = Field("private", description="可见性 private/workspace/public")
    parameters: List[SkillParameterModel] = Field(default_factory=list, description="")
class SkillUpdateModel(BaseModel):
    skill_name: Optional[str] = None
    skill_desc: Optional[str] = None
    category: Optional[str] = None
    module_path: Optional[str] = None
    class_name: Optional[str] = None
    function_name: Optional[str] = None
    lazy_load: Optional[bool] = None
    preload_priority: Optional[int] = None
    enabled: Optional[bool] = None
    visibility: Optional[str] = Field(None, description="可见性 private/workspace/public")
    parameters: Optional[List[SkillParameterModel]] = None
class SkillBindModel(BaseModel):
    agent_id: int = Field(..., description="Agent pr_key_id")
    skill_id: str = Field(..., description="Skill ID")
class SkillResponseModel(BaseModel):
    skill_id: str
    skill_name: str
    skill_desc: str
    category: str
    enabled: bool
    lazy_load: bool
    preload_priority: int
    module_path: str
    class_name: str
    function_name: str
    parameters: List[Dict[str, Any]]
@router.get("/list", response_model=Dict[str, Any])
@handle_admin_errors("", detail_with_context=True)
async def list_skills(
    request: Request,
    enabled_only: bool = Query(False, description=""),
    category: Optional[str] = Query(None, description=""),
    workspace_id: int | None = Query(None, description="按工作空间筛选（仅 admin 有效，覆盖当前空间；None=全部空间）"),
):
    # admin 用 query 覆盖（None=全部空间，传值=该空间聚合）；非 admin 走三层可见性（防越权）
    is_admin = False
    perms = None
    try:
        perms = get_current_user_permissions(request.headers.get("Authorization", ""))
        is_admin = perms.has_role("admin")
    except Exception:
        pass
    repo = SkillRepository()
    if is_admin:
        skills = repo.get_all(enabled_only=enabled_only, workspace_id=workspace_id, is_admin=True)
    else:
        ws = get_workspace_id_from_auth_header(request.headers.get("Authorization", ""))
        uid = int(perms.user_id) if perms and str(perms.user_id).isdigit() else None
        skills = repo.get_all(
            enabled_only=enabled_only,
            viewer_user_id=uid,
            viewer_workspace_id=ws,
            is_admin=False,
        )
    if category:
        skills = [s for s in skills if s.get("category") == category]
    return {
        "success": True,
        "data": {
            "skills": skills,
            "total": len(skills)
        }
    }
@router.get("/categories", response_model=Dict[str, Any])
async def get_skill_categories():
    from domain.skill.entities import SkillCategory
    categories = [
        {
            "value": cat.value,
            "label": cat.value.title(),
            "description": _get_category_description(cat)
        }
        for cat in SkillCategory
    ]
    return {
        "success": True,
        "data": {
            "categories": categories
        }
    }
def _get_category_description(category: SkillCategory) -> str:
    descriptions = {
        SkillCategory.GENERAL: "通用技能",
        SkillCategory.CODING: "编程开发",
        SkillCategory.SEARCH: "搜索查询",
        SkillCategory.ANALYSIS: "数据分析",
        SkillCategory.WRITING: "内容写作",
        SkillCategory.DATA: "数据处理",
        SkillCategory.AUTOMATION: "自动化任务",
        SkillCategory.COMMUNICATION: "通信交互",
        SkillCategory.UTILITY: "实用工具"
    }
    return descriptions.get(category, "")
@router.get("/local/list", response_model=Dict[str, Any])
async def list_local_skills():
    """列出 skills/ 目录下的本地（磁盘）技能"""
    try:
        from domain.skill.storage import create_skill_storages
        from domain.skill.storage.local import LocalSkillStorage
        storages = create_skill_storages(caller_file=__file__)
        local_skills = []
        for storage in storages:
            if isinstance(storage, LocalSkillStorage):
                skills = storage.load_skills(enabled_only=False)
                for s in skills:
                    local_skills.append({
                        "name": s.name,
                        "description": s.description,
                        "category": s.category.value if s.category else "general",
                        "enabled": s.enabled,
                        "source": "disk",
                        "skill_dir": s.skill_dir or "",
                        "skill_file": s.skill_file or "",
                        "has_content": bool(s.cached_content),
                    })
        return {
            "success": True,
            "data": {
                "skills": local_skills,
                "total": len(local_skills)
            }
        }
    except Exception as e:
        logger.error(f"加载本地技能失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/local/import/{skill_name}", response_model=Dict[str, Any])
async def import_local_skill(skill_name: str):
    """将本地（磁盘）技能导入数据库，使其可通过 CRUD 管理"""
    try:
        import json
        from domain.skill.storage import create_skill_storages
        from domain.skill.storage.local import LocalSkillStorage
        repo = SkillRepository()
        existing = repo.get_by_skill_id(skill_name)
        if existing:
            raise HTTPException(status_code=400, detail=f"skill_id '{skill_name}' 已存在于数据库")
        storages = create_skill_storages(caller_file=__file__)
        target_skill = None
        for storage in storages:
            if isinstance(storage, LocalSkillStorage):
                skills = storage.load_skills(enabled_only=False)
                for s in skills:
                    if s.name == skill_name:
                        target_skill = s
                        break
        if not target_skill:
            raise HTTPException(status_code=404, detail=f"本地技能 '{skill_name}' 不存在")
        config_param = json.dumps({
            "category": target_skill.category.value if target_skill.category else "general",
            "module_path": "",
            "class_name": "",
            "function_name": "",
            "lazy_load": True,
            "preload_priority": 0,
        }, ensure_ascii=False)
        entity = repo.create(
            skill_id=skill_name,
            skill_name=skill_name,
            skill_desc=target_skill.description[:500] if target_skill.description else "",
            config_param=config_param,
            input_json_param="",
            enable_status='1' if target_skill.enabled else '0',
            del_flag='0'
        )
        if not entity:
            raise HTTPException(status_code=500, detail="导入失败")
        try:
            reset_skill_registry()
            await get_skill_registry()
        except Exception as e:
            logger.warning(f"重置 skill registry 失败: {e}")
        logger.info(f"导入本地技能: {skill_name}")
        return {
            "success": True,
            "message": f"技能 '{skill_name}' 已导入数据库",
            "data": {"skill_id": skill_name, "pr_key_id": entity.pr_key_id}
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导入本地技能失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/{skill_id}", response_model=Dict[str, Any])
@handle_admin_errors("获取 Skill 失败", detail_with_context=False)
async def get_skill(skill_id: str, request: Request):
    repo = SkillRepository()
    skill = repo.get_by_skill_id(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"skill_id '{skill_id}' 不存在")
    # 三层可见性读校验
    uid, ws, is_admin = _extract_viewer(request)
    if not can_read_object(
        skill.get("visibility") or "", skill.get("creator_id"), skill.get("workspace_id"),
        uid, ws, is_admin,
    ):
        raise HTTPException(status_code=403, detail="无权访问该 Skill")
    return {
        "success": True,
        "data": skill
    }
@router.post("/create", response_model=Dict[str, Any])
@handle_admin_errors("创建 Skill 失败", detail_with_context=False)
async def create_skill(request: Request, skill: SkillCreateModel):
    import json
    from utils.common.visibility import normalize_visibility, visibility_to_is_public
    repo = SkillRepository()
    existing = repo.get_by_skill_id(skill.skill_id)
    if existing:
        raise HTTPException(status_code=400, detail=f"skill_id '{skill.skill_id}' 已存在")
    workspace_id = get_workspace_id_from_auth_header(request.headers.get("Authorization", ""))
    creator_id = None
    try:
        perms = get_current_user_permissions(request.headers.get("Authorization", ""))
        if str(perms.user_id).isdigit():
            creator_id = int(perms.user_id)
    except Exception:
        pass
    visibility = normalize_visibility(skill.visibility)
    input_json_param = ""
    if skill.parameters:
        params_list = [
            {
                "paramName": p.param_name,
                "paramType": p.param_type,
                "paramDesc": p.param_desc,
                "isRequire": "1" if p.required else "0"
            }
            for p in skill.parameters
        ]
        input_json_param = json.dumps(params_list, ensure_ascii=False)
    config_param = json.dumps({
        "category": skill.category,
        "module_path": skill.module_path,
        "class_name": skill.class_name,
        "function_name": skill.function_name,
        "lazy_load": skill.lazy_load,
        "preload_priority": skill.preload_priority,
    }, ensure_ascii=False)
    entity = repo.create(
        skill_id=skill.skill_id,
        skill_name=skill.skill_name,
        skill_desc=skill.skill_desc,
        config_param=config_param,
        input_json_param=input_json_param,
        enable_status='1' if skill.enabled else '0',
        del_flag='0',
        workspace_id=workspace_id,
        creator_id=creator_id,
        visibility=visibility,
        is_public=visibility_to_is_public(visibility),
    )
    if not entity:
        raise HTTPException(status_code=500, detail="创建失败")
    pr_key_id = entity.pr_key_id
    try:
        reset_skill_registry()
        await get_skill_registry()
    except Exception as e:
        logger.warning(f"重置 skill registry 失败: {e}")
    logger.info(f"创建 Skill: {skill.skill_id} - {skill.skill_name}")
    return {
        "success": True,
        "message": "创建成功",
        "data": {
            "skill_id": skill.skill_id,
            "pr_key_id": pr_key_id
        }
    }
@router.put("/{skill_id}", response_model=Dict[str, Any])
@handle_admin_errors("更新 Skill 失败", detail_with_context=False)
async def update_skill(skill_id: str, skill: SkillUpdateModel, request: Request):
    import json
    repo = SkillRepository()
    existing = repo.get_by_skill_id(skill_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"skill_id '{skill_id}' 不存在")
    # 三层可见性修改校验
    uid, ws, is_admin = _extract_viewer(request)
    if not can_modify_object(
        existing.get("visibility") or "", existing.get("creator_id"), existing.get("workspace_id"),
        uid, ws, is_admin,
    ):
        raise HTTPException(status_code=403, detail="无权修改该 Skill")
    pr_key_id = existing.get('pr_key_id') if isinstance(existing, dict) else existing.pr_key_id
    update_data = {}
    if skill.skill_name is not None:
        update_data['skill_name'] = skill.skill_name
    if skill.skill_desc is not None:
        update_data['skill_desc'] = skill.skill_desc
    if skill.parameters is not None:
        params_list = [
            {
                "paramName": p.param_name,
                "paramType": p.param_type,
                "paramDesc": p.param_desc,
                "isRequire": "1" if p.required else "0"
            }
            for p in skill.parameters
        ]
        update_data['input_json_param'] = json.dumps(params_list, ensure_ascii=False)
    if skill.enabled is not None:
        update_data['enable_status'] = '1' if skill.enabled else '0'
    if skill.visibility is not None:
        # 三层可见性：visibility 为 source of truth，同步 is_public
        from utils.common.visibility import normalize_visibility, visibility_to_is_public
        vis = normalize_visibility(skill.visibility)
        update_data['visibility'] = vis
        update_data['is_public'] = visibility_to_is_public(vis)
    config = {}
    for key in ('category', 'module_path', 'class_name', 'function_name', 'lazy_load', 'preload_priority'):
        val = getattr(skill, key, None)
        if val is not None:
            config[key] = val
    if config:
        existing_config = {}
        if isinstance(existing, dict) and existing.get('config_param'):
            try:
                existing_config = json.loads(existing['config_param'])
            except (json.JSONDecodeError, TypeError):
                existing_config = {}
        existing_config.update(config)
        update_data['config_param'] = json.dumps(existing_config, ensure_ascii=False)
    entity = repo.upsert(pr_key_id, **update_data)
    if not entity:
        raise HTTPException(status_code=500, detail="更新失败")
    try:
        reset_skill_registry()
        await get_skill_registry()
    except Exception as e:
        logger.warning(f"重置 skill registry 失败: {e}")
    logger.info(f"更新 Skill: {skill_id}")
    return {
        "success": True,
        "message": "更新成功"
    }
@router.delete("/unbind", response_model=Dict[str, Any])
@handle_admin_errors("解绑 Skill 失败", detail_with_context=False)
async def unbind_skill_from_agent(agent_id: int, skill_id: str):
    from infrastructure.database.repositories.skill_repository import SkillRepository
    skill_repo = SkillRepository()
    relation_repo = AgentRelationRepository()
    skill = skill_repo.get_by_skill_id(skill_id, return_dict=False)
    if not skill:
        raise HTTPException(status_code=404, detail=f"skill_id '{skill_id}' 不存在")
    success = relation_repo.remove_relation(agent_id, skill.pr_key_id, AgentRelation.RELATION_SKILL)
    if not success:
        raise HTTPException(status_code=500, detail="解绑失败")
    logger.info(f"解绑 Skill: Agent {agent_id} - Skill {skill_id}")
    return {
        "success": True,
        "message": "解绑成功"
    }
@router.delete("/{skill_id}", response_model=Dict[str, Any])
@handle_admin_errors("删除 Skill 失败", detail_with_context=False)
async def delete_skill(skill_id: str, request: Request):
    repo = SkillRepository()
    existing = repo.get_by_skill_id(skill_id, return_dict=False)
    if not existing:
        raise HTTPException(status_code=404, detail=f"skill_id '{skill_id}' 不存在")
    # 三层可见性修改校验（用 dict 形式拿可见性字段）
    existing_dict = repo.get_by_skill_id(skill_id) or {}
    uid, ws, is_admin = _extract_viewer(request)
    if not can_modify_object(
        existing_dict.get("visibility") or "", existing_dict.get("creator_id"),
        existing_dict.get("workspace_id"), uid, ws, is_admin,
    ):
        raise HTTPException(status_code=403, detail="无权删除该 Skill")
    success = repo.delete_skill(existing.pr_key_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")
    try:
        reset_skill_registry()
        await get_skill_registry()
    except Exception as e:
        logger.warning(f"重置 skill registry 失败: {e}")
    logger.info(f"删除 Skill: {skill_id}")
    return {
        "success": True,
        "message": "删除成功"
    }
@router.post("/bind", response_model=Dict[str, Any])
@handle_admin_errors("绑定 Skill 失败", detail_with_context=False)
async def bind_skill_to_agent(binding: SkillBindModel):
    from infrastructure.database.repositories.skill_repository import SkillRepository
    skill_repo = SkillRepository()
    relation_repo = AgentRelationRepository()
    skill = skill_repo.get_by_skill_id(binding.skill_id, return_dict=False)
    if not skill:
        raise HTTPException(status_code=404, detail=f"skill_id '{binding.skill_id}' 不存在")
    success = relation_repo.add_relation(binding.agent_id, skill.pr_key_id, AgentRelation.RELATION_SKILL)
    if not success:
        raise HTTPException(status_code=500, detail="绑定失败")
    logger.info(f"绑定 Skill: Agent {binding.agent_id} - Skill {binding.skill_id}")
    return {
        "success": True,
        "message": "绑定成功"
    }
@router.get("/agent/{agent_id}", response_model=Dict[str, Any])
@handle_admin_errors(" Agent ", detail_with_context=False)
async def get_agent_skills(agent_id: int):
    repo = AgentRelationRepository()
    skill_repo = SkillRepository()
    skill_pr_key_ids = repo.get_skill_ids(agent_id)
    skills_with_metadata = []
    for pr_key_id in skill_pr_key_ids:
        skill_data = skill_repo.get_by_id(pr_key_id)
        if skill_data:
            skills_with_metadata.append({
                'pr_key_id': pr_key_id,
                'skill': skill_data
            })
    return {
        "success": True,
        "data": {
            'agent_id': agent_id,
            'skills': skills_with_metadata,
            'total': len(skills_with_metadata)
        }
    }
@router.post("/reload", response_model=Dict[str, Any])
@handle_admin_errors("重新加载 Skill 失败", detail_with_context=False)
async def reload_skills():
    reset_skill_registry()
    registry = await get_skill_registry()
    return {
        "success": True,
        "message": "",
        "data": {
            "total_skills": registry.skill_count,
            "preload_count": len(registry._preload_list)
        }
    }