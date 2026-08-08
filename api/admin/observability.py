"""可观测性 API：返回 langfuse 配置 + 代理 trace 列表。"""
import httpx
from fastapi import APIRouter, Query, Depends
from utils.config.langfuse_config import get_langfuse_config
from .common import verify_token

router = APIRouter(prefix="/observability", tags=["observability"], dependencies=[Depends(verify_token)])


@router.get("/langfuse")
async def get_langfuse_info():
    """返回 langfuse 配置（enabled/host），供前端使用。"""
    lf = get_langfuse_config()
    return {
        "data": {
            "enabled": lf.get("enabled", False),
            "host": lf.get("host", ""),
            "self_hosted": lf.get("self_hosted", True),
        }
    }


@router.get("/langfuse/traces")
async def get_langfuse_traces(limit: int = Query(10, ge=1, le=50)):
    """代理 langfuse API，返回最近 trace 列表（简化字段）。"""
    lf = get_langfuse_config()
    host = lf.get("host", "")
    public_key = lf.get("public_key", "")
    secret_key = lf.get("secret_key", "")
    if not (host and public_key and secret_key):
        return {"data": {"traces": [], "total": 0, "error": "langfuse config incomplete"}}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{host}/api/public/traces?limit={limit}",
                auth=(public_key, secret_key),
            )
            if resp.status_code == 200:
                traces = resp.json().get("data", [])
                simplified = [
                    {
                        "id": t.get("id", ""),
                        "name": t.get("name", ""),
                        "timestamp": t.get("timestamp", ""),
                        "session_id": t.get("sessionId"),
                        "user_id": t.get("userId"),
                    }
                    for t in traces
                ]
                return {"data": {"traces": simplified, "total": len(simplified)}}
            return {"data": {"traces": [], "total": 0, "error": f"langfuse API {resp.status_code}"}}
    except Exception as e:
        return {"data": {"traces": [], "total": 0, "error": str(e)}}
