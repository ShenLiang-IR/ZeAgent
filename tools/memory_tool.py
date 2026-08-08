"""Letta 式自主记忆工具：memory_search / memory_insert / memory_update。

user_id/session_id 由运行时 ContextVar 自动捕获；LLM 只传 query/content/memory_id。
模块顶部只 import 轻量依赖（langchain_core.tools/loguru），memory 包经 _get_mm 惰性导入，
避免 jieba/chromadb 在工具发现阶段被拖入。测试可覆盖 _get_mm 注入隔离实例。
"""
import json
from loguru import logger
from langchain_core.tools import tool


def _get_mm():
    """获取 MemoryManager 单例（惰性 import memory 包，避免工具发现期拖入重依赖）。"""
    from memory import get_memory_manager
    return get_memory_manager()


@tool
async def memory_search(query: str, limit: int = 5) -> str:
    """搜索当前用户的长期记忆，返回相关记忆列表（id/content/type/importance）。"""
    try:
        from utils.common.memory_context import get_memory_context
        ctx = get_memory_context()
        mm = _get_mm()
        results = await mm.recall(
            query=query, limit=limit,
            user_id=ctx.user_id, session_id=ctx.session_id,
            tiers=["long_term"],
        )
        return json.dumps([
            {"id": m.id, "content": m.content,
             "type": getattr(m.type, "value", str(m.type)),
             "importance": m.importance}
            for m in results
        ], ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[memory_search] failed: {e}")
        return json.dumps([])


@tool
async def memory_insert(content: str, type: str = "note", importance: float = 0.8) -> str:
    """写入一条持久记忆（importance 默认 0.8 落 long_term，自动触发冲突检测，必要时合并/更新）。"""
    try:
        from utils.common.memory_context import get_memory_context
        ctx = get_memory_context()
        mm = _get_mm()
        m = await mm.remember(
            content=content, type=type, importance=importance,
            user_id=ctx.user_id, session_id=ctx.session_id,
            source_session_id=ctx.session_id,
        )
        return f"stored memory_id={m.id}"
    except Exception as e:
        logger.warning(f"[memory_insert] failed: {e}")
        return f"error: {e}"


@tool
async def memory_update(memory_id: str, content: str) -> str:
    """更新指定记忆内容（重嵌）；仅可改当前用户自己的记忆。"""
    try:
        from utils.common.memory_context import get_memory_context
        ctx = get_memory_context()
        mm = _get_mm()
        m = await mm.long_term.get(memory_id)
        if m is None:
            return "not found"
        if m.user_id != ctx.user_id:
            return "forbidden"
        m.content = content
        m.touch()
        await mm.long_term.update(m)
        return "updated"
    except Exception as e:
        logger.warning(f"[memory_update] failed: {e}")
        return f"error: {e}"
