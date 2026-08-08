# api/model_routes.py
# 模型配置 CRUD（LLM/Embedding/Rerank 统一管理）
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from loguru import logger

router = APIRouter(prefix="/api/models", tags=["models"])


class ModelCreateRequest(BaseModel):
    model_name: str
    provider: str
    model_type: str
    display_name: str = ""
    api_key: str = ""
    api_endpoint_url: str = ""


class ModelUpdateRequest(BaseModel):
    model_name: Optional[str] = None
    provider: Optional[str] = None
    model_type: Optional[str] = None
    display_name: Optional[str] = None
    api_key: Optional[str] = None
    api_endpoint_url: Optional[str] = None
    status: Optional[str] = None


@router.get("")
async def list_models(model_type: str = None):
    """列出模型配置（可按 model_type 过滤：LLM/Embedding/Rerank）。"""
    try:
        from infrastructure.database.repositories.model_config_repository import ModelConfigRepository
        repo = ModelConfigRepository()
        return {"list": repo.list_all(model_type=model_type)}
    except Exception as e:
        logger.error("[Model API] list failed: " + str(e))
        raise HTTPException(500, "查询失败: " + str(e)[:200])


@router.post("")
async def create_model(req: ModelCreateRequest):
    """创建模型配置。"""
    try:
        from infrastructure.database.repositories.model_config_repository import ModelConfigRepository
        repo = ModelConfigRepository()
        result = repo.create_model(
            model_name=req.model_name, provider=req.provider, model_type=req.model_type,
            display_name=req.display_name, api_key=req.api_key, api_endpoint_url=req.api_endpoint_url,
        )
        if not result:
            raise HTTPException(500, "创建失败")
        logger.info(f"[Model API] created: {req.model_name} ({req.provider}/{req.model_type})")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[Model API] create failed: " + str(e))
        raise HTTPException(500, "创建失败: " + str(e)[:200])


@router.put("/{model_id}")
async def update_model(model_id: str, req: ModelUpdateRequest):
    """更新模型配置。"""
    try:
        from infrastructure.database.repositories.model_config_repository import ModelConfigRepository
        repo = ModelConfigRepository()
        data = {k: v for k, v in req.model_dump().items() if v is not None}
        result = repo.update_model(model_id, **data)
        if not result:
            raise HTTPException(404, "模型不存在: " + model_id)
        logger.info(f"[Model API] updated: {model_id}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[Model API] update failed: " + str(e))
        raise HTTPException(500, "更新失败: " + str(e)[:200])


@router.delete("/{model_id}")
async def delete_model(model_id: str):
    """删除模型配置（软删除）。"""
    try:
        from infrastructure.database.repositories.model_config_repository import ModelConfigRepository
        repo = ModelConfigRepository()
        if not repo.delete_model(model_id):
            raise HTTPException(404, "模型不存在: " + model_id)
        logger.info(f"[Model API] deleted: {model_id}")
        return {"status": "ok", "id": model_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[Model API] delete failed: " + str(e))
        raise HTTPException(500, "删除失败: " + str(e)[:200])
