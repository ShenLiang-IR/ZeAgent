# api/rag/rag_routes.py
# RAG API endpoints: ingest + retrieve
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict
import asyncio
import tempfile
import os
import threading
import time
from loguru import logger

router = APIRouter(prefix="/api/rag", tags=["rag"])


class RetrieveRequest(BaseModel):
    query: str
    kb_id: str = "default"
    top_k: int = 5
    strategy: str = "semantic"
    metadata_filter: Optional[Dict] = None
    ratio: Optional[float] = None


class RetrieveResponse(BaseModel):
    query: str
    strategy: str
    latency_ms: float
    total_chunks: int
    chunks: list


_ingest_tasks: dict = {}

# R4: ingest 任务记录的上限 + TTL（防 _ingest_tasks 无界增长导致内存泄漏）
_INGEST_TASKS_MAX = 500
_INGEST_TASKS_TTL_SECONDS = 3600


def _evict_task_dict(tasks: dict, max_tasks: int, ttl_seconds: int) -> None:
    """通用任务记录淘汰：TTL 过期 + 超上限淘汰，防 dict 无界增长。

    processing 状态任务不被淘汰（前端可能在轮询）；已完成任务按 TTL 清理，
    超上限时按插入顺序淘汰最旧的已完成任务。
    """
    now = time.time()
    # 1) TTL 过期清理（非 processing）
    expired = [
        k for k, v in tasks.items()
        if v.get("status") != "processing"
        and now - v.get("created_at", now) > ttl_seconds
    ]
    for k in expired:
        tasks.pop(k, None)
    # 2) 超上限按插入顺序淘汰最旧的非 processing
    if len(tasks) > max_tasks:
        for k in list(tasks):
            if len(tasks) <= max_tasks:
                break
            v = tasks.get(k)
            if v.get("status") != "processing":
                tasks.pop(k, None)


def _evict_ingest_tasks():
    _evict_task_dict(_ingest_tasks, _INGEST_TASKS_MAX, _INGEST_TASKS_TTL_SECONDS)


# S2: parse 任务记录的淘汰（对齐 ingest 模式）
_PARSE_TASKS_MAX = 500
_PARSE_TASKS_TTL_SECONDS = 3600


def _evict_parse_tasks():
    _evict_task_dict(_parse_tasks, _PARSE_TASKS_MAX, _PARSE_TASKS_TTL_SECONDS)


# R5: RAGSystem 单例锁（双检防 embedding ~15s 初始化并发双初始化）
_rag_system_instance = None
_rag_system_lock = threading.Lock()


def _get_rag_system():
    """RAGSystem 单例（复用，避免每次请求重新 init embedding ~15s）。

    双检锁：锁外快速路径 + 锁内确认再初始化，防并发首请双初始化。
    """
    global _rag_system_instance
    if _rag_system_instance is None:
        with _rag_system_lock:
            if _rag_system_instance is None:
                from rag.rag_system.rag_system import RAGSystem
                _rag_system_instance = RAGSystem()
    return _rag_system_instance


def reset_rag_system():
    """重置 RAGSystem 单例（热重载时调用）。

    清空后下次 _get_rag_system() 会按最新 config 重建实例。
    """
    global _rag_system_instance
    _rag_system_instance = None


@router.post("/ingest")
async def ingest_document(
    file: UploadFile = File(...),
    kb_id: str = Form("default"),
):
    """上传文档 → 后台向量化入库。立即返回 task_id，前端轮询 status。

    异步处理：大文档 embedding 耗时长（bge-m3 每长 chunk 约 1.7s，
    153 chunk 需 260s），同步会超时。后台线程处理，立即返回 task_id。
    """
    import uuid
    import threading
    suffix = os.path.splitext(file.filename or "doc.txt")[1] or ".txt"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    task_id = str(uuid.uuid4())
    # R4: 新增任务前淘汰过期/超限记录（防 _ingest_tasks 无界增长）
    _evict_ingest_tasks()
    _ingest_tasks[task_id] = {
        "status": "processing", "filename": file.filename,
        "kb_id": kb_id, "chunks": 0,
        "created_at": time.time(),
    }
    t = threading.Thread(
        target=_do_ingest, args=(task_id, tmp_path, kb_id, file.filename),
        daemon=True,
    )
    t.start()
    logger.info(f"[RAG API] ingest task={task_id} {file.filename} (kb={kb_id}) started")
    return {"task_id": task_id, "status": "processing",
            "filename": file.filename, "kb_id": kb_id}


def _do_ingest(task_id: str, tmp_path: str, kb_id: str, filename: str):
    """后台线程：加载→分块→嵌入→存储。更新 _ingest_tasks 状态。"""
    try:
        rs = _get_rag_system()
        # 传 filename 作为 doc_name，避免 metadata 存临时路径导致检索结果不可读
        count = rs.ingest(tmp_path, kb_id, doc_name=filename)
        _ingest_tasks[task_id] = {
            "status": "done", "filename": filename,
            "kb_id": kb_id, "chunks": count,
        }
        logger.info(f"[RAG API] ingest task={task_id} {filename} → {count} chunks (kb={kb_id})")
    except Exception as e:
        _ingest_tasks[task_id] = {
            "status": "failed", "filename": filename, "kb_id": kb_id,
            "error": str(type(e).__name__) + ": " + str(e)[:200],
        }
        logger.error("[RAG API] ingest task=" + task_id + " failed: " + str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.get("/ingest/status/{task_id}")
async def ingest_status(task_id: str):
    """查询 ingest 任务状态（processing/done/failed）。"""
    task = _ingest_tasks.get(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    return task


# ===== 文档解析（MinerU）=====
_parse_tasks: dict = {}


@router.post("/parse")
async def parse_document(
    file: UploadFile = File(...),
):
    """上传文档 → 后台 MinerU 解析。立即返回 task_id，前端轮询 status。

    支持 pdf/docx/jpeg/jpg。结果（JSON+MD）保存到 rag.persist_directory。
    """
    import uuid
    import threading
    suffix = os.path.splitext(file.filename or "doc.pdf")[1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    task_id = str(uuid.uuid4())
    # S2: 新增任务前淘汰过期/超限记录（防 _parse_tasks 无界增长）
    _evict_parse_tasks()
    _parse_tasks[task_id] = {"status": "processing", "filename": file.filename, "created_at": time.time()}
    t = threading.Thread(
        target=_do_parse, args=(task_id, tmp_path, file.filename),
        daemon=True,
    )
    t.start()
    logger.info(f"[RAG API] parse task={task_id} {file.filename} started")
    return {"task_id": task_id, "status": "processing", "filename": file.filename}


def _do_parse(task_id: str, tmp_path: str, filename: str):
    """后台线程：MinerU 上传→解析→轮询→下载→保存 JSON/MD。"""
    try:
        from rag.rag_system.doc_parser import DocParser
        from utils.config import get_config
        mineru = get_config("mineru", {})
        persist_dir = get_config("rag.persist_directory", "data/chroma_rag")
        parser = DocParser(
            base_url=mineru.get("base_url", ""),
            api_key=mineru.get("api_key", ""),
            timeout=mineru.get("timeout", 600),
            poll_interval=mineru.get("poll_interval", 5),
        )
        result = parser.parse(tmp_path, persist_dir, filename=filename)
        _parse_tasks[task_id] = {"status": "done", "filename": filename, **result}
        logger.info(f"[RAG API] parse task={task_id} {filename} done")
    except Exception as e:
        _parse_tasks[task_id] = {
            "status": "failed", "filename": filename,
            "error": str(type(e).__name__) + ": " + str(e)[:300],
        }
        logger.error("[RAG API] parse task=" + task_id + " failed: " + str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.get("/parse/status/{task_id}")
async def parse_status(task_id: str):
    """查询 parse 任务状态（processing/done/failed）。"""
    task = _parse_tasks.get(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    return task


@router.post("/retrieve")
async def retrieve_chunks(req: RetrieveRequest):
    """检索知识库。返回 chunks。"""
    try:
        rs = _get_rag_system()
        if req.strategy == "adaptive":
            # Adaptive：Agentic RAG 循环是异步实现，直接 await（不经 to_thread）
            result = await rs.retrieve_adaptive_async(
                query=req.query,
                kb_id=req.kb_id,
                top_k=req.top_k,
            )
        else:
            # R1: retrieve 是同步实现（内部 embedding + new_event_loop），
            # 经 to_thread 放到工作线程执行——不阻塞事件循环，且 new_event_loop
            # 在无运行 loop 的工作线程内安全运行。
            result = await asyncio.to_thread(
                rs.retrieve,
                query=req.query,
                strategy=req.strategy,
                top_k=req.top_k,
                kb_id=req.kb_id,
                metadata_filter=req.metadata_filter,
                ratio=req.ratio,
            )
        chunks = [
            {"content": c.content, "doc_name": c.doc_name, "node_title": c.node_title,
             "page": c.page, "char_start": c.char_start, "char_end": c.char_end,
             "citation": c.citation}
            for c in result.chunks
        ]
        logger.info(f"[RAG API] retrieve kb={req.kb_id} q='{req.query[:30]}' → {len(chunks)} chunks")
        return RetrieveResponse(
            query=result.query,
            strategy=result.strategy,
            latency_ms=result.latency_ms,
            total_chunks=len(chunks),
            chunks=chunks,
        )
    except Exception as e:
        logger.error("[RAG API] retrieve failed: " + str(e))
        raise HTTPException(500, "检索失败: " + str(type(e).__name__) + ": " + str(e)[:200])


@router.get("/config")
async def get_rag_config():
    """返回 RAG 配置状态。"""
    from utils.config import get_config
    rag_cfg = get_config("rag", {})
    return {
        "persist_directory": rag_cfg.get("persist_directory", "data/chroma_rag"),
        "hybrid_enabled": rag_cfg.get("hybrid", {}).get("enabled", False),
        "rerank_enabled": rag_cfg.get("rerank", {}).get("enabled", False),
        "query_rewrite_enabled": rag_cfg.get("query_rewrite", {}).get("enabled", False),
        "parent_child_enabled": rag_cfg.get("chunk", {}).get("parent_child", {}).get("enabled", False),
        "vector_store_backend": rag_cfg.get("vector_store", {}).get("backend", "chromadb"),
    }


# ===== 知识库管理 CRUD =====
class KbCreateRequest(BaseModel):
    kb_id: str
    name: str
    description: str = ""
    persist_directory: str = "data/chroma_rag"
    embedding_provider: str = "local"
    embedding_model: str = ""
    embedding_base_url: str = ""
    chunk_size: int = 500
    chunk_overlap: int = 100


class KbUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    persist_directory: Optional[str] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_base_url: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    status: Optional[str] = None


@router.get("/kb")
async def list_knowledge_bases():
    """列出所有 RAG 知识库。"""
    try:
        from infrastructure.database.repositories.rag_kb_repository import RagKnowledgeBaseRepository
        repo = RagKnowledgeBaseRepository()
        return {"list": repo.list_all()}
    except Exception as e:
        logger.error("[RAG API] kb list failed: " + str(e))
        raise HTTPException(500, "查询失败: " + str(e)[:200])


@router.post("/kb")
async def create_knowledge_base(req: KbCreateRequest):
    """创建 RAG 知识库。"""
    try:
        from infrastructure.database.repositories.rag_kb_repository import RagKnowledgeBaseRepository
        repo = RagKnowledgeBaseRepository()
        if repo.get_by_kb_id(req.kb_id):
            raise HTTPException(400, "知识库ID已存在: " + req.kb_id)
        result = repo.create_kb(
            kb_id=req.kb_id, name=req.name,
            description=req.description, persist_directory=req.persist_directory,
            embedding_provider=req.embedding_provider, embedding_model=req.embedding_model,
            embedding_base_url=req.embedding_base_url,
            chunk_size=req.chunk_size, chunk_overlap=req.chunk_overlap,
        )
        if not result:
            raise HTTPException(500, "创建失败")
        logger.info(f"[RAG API] kb created: {req.kb_id}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[RAG API] kb create failed: " + str(e))
        raise HTTPException(500, "创建失败: " + str(e)[:200])


@router.put("/kb/{kb_id}")
async def update_knowledge_base(kb_id: str, req: KbUpdateRequest):
    """更新 RAG 知识库。"""
    try:
        from infrastructure.database.repositories.rag_kb_repository import RagKnowledgeBaseRepository
        repo = RagKnowledgeBaseRepository()
        data = {k: v for k, v in req.model_dump().items() if v is not None}
        result = repo.update_kb(kb_id, **data)
        if not result:
            raise HTTPException(404, "知识库不存在: " + kb_id)
        logger.info(f"[RAG API] kb updated: {kb_id}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[RAG API] kb update failed: " + str(e))
        raise HTTPException(500, "更新失败: " + str(e)[:200])


@router.delete("/kb/{kb_id}")
async def delete_knowledge_base(kb_id: str):
    """删除 RAG 知识库（软删除）。"""
    try:
        from infrastructure.database.repositories.rag_kb_repository import RagKnowledgeBaseRepository
        repo = RagKnowledgeBaseRepository()
        ok = repo.delete_kb(kb_id)
        if not ok:
            raise HTTPException(404, "知识库不存在: " + kb_id)
        logger.info(f"[RAG API] kb deleted: {kb_id}")
        return {"status": "ok", "kb_id": kb_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[RAG API] kb delete failed: " + str(e))
        raise HTTPException(500, "删除失败: " + str(e)[:200])
