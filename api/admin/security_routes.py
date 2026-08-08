"""敏感词管理 API + Agent 审批 API。"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from utils.common.permissions import UserPermissions
from .base import wrap_response
from .common import verify_token
from .permissions import require_read, require_write

router = APIRouter(prefix="/security", tags=["admin"], dependencies=[Depends(verify_token)])


# ─── 敏感词管理 ───

class SensitiveWordCreate(BaseModel):
    word: str
    category: str = "other"
    enabled: int = 1


@router.get("/sensitive-words")
async def list_words(
    user_permissions: UserPermissions = Depends(require_read("security")),
    skip: int = Query(0), limit: int = Query(100),
):
    from infrastructure.database.repositories.security_repository import SensitiveWordRepository
    repo = SensitiveWordRepository()
    items = repo.get_all(limit=limit)
    return wrap_response({"list": items, "total": len(items)})


@router.post("/sensitive-words")
async def add_word(
    req: SensitiveWordCreate,
    user_permissions: UserPermissions = Depends(require_write("security")),
):
    from infrastructure.database.repositories.security_repository import SensitiveWordRepository
    repo = SensitiveWordRepository()
    repo.create(word=req.word, category=req.category, enabled=req.enabled)
    return wrap_response(message="添加成功")


@router.delete("/sensitive-words/{word_id}")
async def delete_word(
    word_id: str,
    user_permissions: UserPermissions = Depends(require_write("security")),
):
    from infrastructure.database.repositories.security_repository import SensitiveWordRepository
    repo = SensitiveWordRepository()
    repo.update(word_id, enabled=0, del_flag="1")
    return wrap_response(message="已删除")


@router.patch("/sensitive-words/{word_id}/toggle")
async def toggle_word(
    word_id: str,
    user_permissions: UserPermissions = Depends(require_write("security")),
):
    from infrastructure.database.repositories.security_repository import SensitiveWordRepository
    repo = SensitiveWordRepository()
    item = repo.get_by_id(word_id, return_dict=True)
    if item:
        repo.update(word_id, enabled=0 if item.get("enabled") == 1 else 1)
    return wrap_response(message="已切换")
