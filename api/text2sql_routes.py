"""text2sql API endpoint：自然语言 → SQL 查询"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from loguru import logger

router = APIRouter(prefix="/api/text2sql", tags=["text2sql"])

# 单例 TextSQL 实例：委托 db_skills.text2sql.factory（工具与路由共用，避免初始化逻辑重复）
def _get_tsql():
    """获取 TextSQL 单例（委托 factory）。"""
    from db_skills.text2sql.factory import get_textsql
    return get_textsql()


class AskRequest(BaseModel):
    question: str
    max_rows: Optional[int] = 20


@router.post("/ask")
async def ask(req: AskRequest):
    """自然语言查询数据库，返回 SQL + 数据。"""
    if not req.question.strip():
        raise HTTPException(400, "问题不能为空")
    try:
        tsql = _get_tsql()
        logger.info(f"[text2sql] ask: {req.question[:50]}")
        result = tsql.ask(req.question, max_rows=req.max_rows)
        return {
            "question": result.question,
            "sql": result.sql,
            "data": result.data,
            "error": result.error,
            "tool_calls": result.tool_calls_made,
            "success": result.success,
        }
    except Exception as e:
        logger.error(f"[text2sql] ask failed: {e}", exc_info=True)
        raise HTTPException(500, f"查询失败: {str(e)[:200]}")


@router.get("/trace-summary")
async def trace_summary():
    """获取 trace 统计。"""
    tsql = _get_tsql()
    if tsql.tracer:
        return tsql.tracer.summary()
    return {"total_queries": 0, "message": "tracing not enabled"}
