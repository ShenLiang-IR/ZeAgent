from typing import Optional, List, Dict, Any, Union
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, field_validator, model_validator
from loguru import logger
from utils.common.auth_dependencies import get_current_user_id
from utils.db import get_chat_db
from infrastructure.database.repositories.smart_writing_repository import WritingDocumentRepository
router = APIRouter()
class CreateSessionRequest(BaseModel):
    title: Optional[str] = None
    model_config_data: Optional[Dict[str, Any]] = None
class UpdateSessionRequest(BaseModel):
    title: Optional[str] = None
    model_config_data: Optional[Dict[str, Any]] = None
class BatchDeleteRequest(BaseModel):
    session_ids: List[str]
    @field_validator('session_ids')
    @classmethod
    def validate_session_ids(cls, v):
        if not v:
            raise ValueError('session_ids ')
        if len(v) > 100:
            raise ValueError(' 100 ')
        return v
class SessionResponse(BaseModel):
    id: str
    pr_key_id: str
    session_id: Optional[str] = None
    user_id: str
    title: Optional[str] = None
    model_config_data: Optional[Dict[str, Any]] = None
    message_count: int = 0
    status: str = "active"
    visible_scope: str = "private"
    last_message_at: Optional[str] = None
    del_flag: str = "0"
    created_at: str
    updated_at: str
    @model_validator(mode='after')
    def set_session_id(self):
        self.session_id = self.pr_key_id
        return self
class MessageResponse(BaseModel):
    id: str
    pr_key_id: str
    user_id: str
    session_id: str
    role: str
    content: Union[str, Dict[str, Any]]
    message_order: int
    message_type: Optional[str] = "chat"
    created_at: str
def _get_step_progress_from_document(document_id: str) -> Optional[Dict[str, Any]]:
    try:
        writing_repo = WritingDocumentRepository()
        document = writing_repo.get_by_id(document_id)
        if not document:
            return None
        doc_content = document.get("doc_content")
        if not doc_content:
            return None
        import json
        if isinstance(doc_content, str):
            doc_json = json.loads(doc_content)
        else:
            doc_json = doc_content
        attrs = doc_json.get("attrs", {})
        step_progress = attrs.get("stepProgress")
        return step_progress
    except Exception as e:
        logger.error(f"获取写作步骤进度失败: {e}")
        return None
def _enrich_writing_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched_messages = []
    for msg in messages:
        msg_type = msg.get("message_type", "chat")
        if msg_type == "writing_result":
            content = msg.get("content")
            if isinstance(content, dict):
                document_id = content.get("document_id")
            elif isinstance(content, str):
                import json
                try:
                    content_dict = json.loads(content)
                    document_id = content_dict.get("document_id")
                except Exception:
                    document_id = None
            else:
                document_id = None
            if document_id:
                step_progress = _get_step_progress_from_document(document_id)
                if step_progress:
                    if isinstance(content, str):
                        import json
                        try:
                            content = json.loads(content)
                        except Exception:
                            content = {"text": content}
                    if isinstance(content, dict):
                        content["step_progress"] = step_progress
                        msg["content"] = content
        enriched_messages.append(msg)
    return enriched_messages
@router.post("/sessions")
async def create_session(
    request: CreateSessionRequest,
    user_id: str = Depends(get_current_user_id),
    authorization: Optional[str] = Header(None),
):
    try:
        chat_db = get_chat_db()
        # 从 token 提取 workspace_id
        workspace_id = None
        if authorization:
            try:
                from services.auth_service import AuthService
                payload = AuthService().verify_token(authorization)
                if payload:
                    workspace_id = payload.get('workspace_id')
            except Exception as e:
                logger.debug(f"[session] workspace_id 提取失败: {e}")

        session = chat_db.create_session(
            user_id=user_id,
            title=request.title,
            model_config_data=request.model_config_data,
            workspace_id=workspace_id,
        )
        return session
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"会话服务失败: {str(e)}")
@router.get("/sessions")
async def list_sessions(
    search: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    user_id: str = Depends(get_current_user_id)
):
    try:
        chat_db = get_chat_db()
        sessions, total = chat_db.list_sessions_with_count(
            user_id=user_id,
            search_query=search,
            limit=limit,
            offset=offset
        )
        return {"sessions": sessions, "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"会话服务失败: {str(e)}")
@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id)
):
    try:
        chat_db = get_chat_db()
        session = chat_db.get_session(user_id=user_id, pr_key_id=session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        return session
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"会话服务失败: {str(e)}")
@router.put("/sessions/{session_id}")
async def update_session(
    session_id: str,
    request: UpdateSessionRequest,
    user_id: str = Depends(get_current_user_id)
):
    try:
        chat_db = get_chat_db()
        session = chat_db.update_session(
            user_id=user_id,
            pr_key_id=session_id,
            title=request.title,
            model_config_data=request.model_config_data
        )
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        return session
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"会话服务失败: {str(e)}")
@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id)
):
    try:
        chat_db = get_chat_db()
        success = chat_db.delete_session(user_id=user_id, pr_key_id=session_id)
        if not success:
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"message": "删除成功", "status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"会话服务失败: {str(e)}")
@router.post("/sessions/batch-delete")
async def batch_delete_sessions(
    request: BatchDeleteRequest,
    user_id: str = Depends(get_current_user_id)
):
    try:
        chat_db = get_chat_db()
        deleted, skipped = chat_db.batch_delete_sessions(
            user_id=user_id,
            session_ids=request.session_ids
        )
        return {
            "deleted": deleted,
            "skipped": skipped,
            "message": f"成功删除 {deleted} 个" + (f"，跳过 {skipped} 个" if skipped > 0 else "")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"会话服务失败: {str(e)}")
@router.delete("/sessions")
async def delete_all_sessions(
    user_id: str = Depends(get_current_user_id)
):
    try:
        chat_db = get_chat_db()
        deleted_count = chat_db.delete_all_sessions(user_id=user_id)
        return {
            "message": f"成功删除 {deleted_count} 个会话",
            "status": "success",
            "deleted_count": deleted_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"会话服务失败: {str(e)}")
@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    user_id: str = Depends(get_current_user_id)
):
    try:
        chat_db = get_chat_db()
        session = chat_db.get_session(user_id=user_id, pr_key_id=session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        messages = chat_db.get_messages(user_id=user_id, session_id=session_id)
        source_type = session.get("source_type", "1")
        if source_type == "2" and messages:
            messages = _enrich_writing_messages(messages)
        return {"messages": messages or [], "total": len(messages) if messages else 0}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"会话服务失败: {str(e)}")