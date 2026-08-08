from loguru import logger
import asyncio
import json
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from infrastructure.database.repositories.knowledge_repository import (
    KnowledgeBaseRepository,
    KnowledgeBaseDocumentRepository
)
from tools.knowledge_base_tool import BaseKnowledgeTool
class UnstructuredKnowledgeInput(BaseModel):
    knowledge_name: str = Field(
        ...,
        description="知识库名称；传 'auto' 由语义路由自动选库"
    )
    query: str = Field(
        ...,
        description=""
    )
    strategy: str = Field(
        default="semantic",
        description="检索策略: semantic(语义) / metadata(元数据) / global(全局) / "
                    "adaptive(自适应Agentic RAG: 检索→评估→改写重检索, 命中更准但更慢)"
    )
    top_k: int = Field(
        default=5,
        description="5"
    )
def _run_coroutine_sync(coro):
    """在同步上下文里运行一个协程（sync→async 桥接）。

    - 当前无运行中事件循环 → 直接 asyncio.run
    - 已在运行中事件循环（如 agent async 上下文误走同步 invoke）→
      另起线程跑独立 loop，避免 "cannot be called from a running event loop"
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


class UnstructuredKnowledgeTool(BaseKnowledgeTool):
    _rag_system = None
    _rag_config_path = None
    _kb_router = None
    def __init__(self, rag_config_path: str = None):
        super().__init__()
        self._rag_config_path = rag_config_path
        self._kb_repo = KnowledgeBaseRepository()
        self._doc_repo = KnowledgeBaseDocumentRepository()
        self._load_knowledge_bases()
        self.tool_description = self._build_tool_description()
    @property
    def rag_system(self):
        if self._rag_system is None:
            from rag.rag_system.rag_system import RAGSystem
            self._rag_system = RAGSystem(config_path=self._rag_config_path)
        return self._rag_system
    def _get_kb_router(self):
        """KB 语义路由器（懒初始化，复用 rag_system 的 embedder）。"""
        if self._kb_router is None:
            from rag.rag_system.kb_router import KBRouter
            self._kb_router = KBRouter(self.rag_system.embedder)
            self._kb_router.load(list(self._knowledge_cache.values()))
        return self._kb_router
    def _resolve_kb(self, knowledge_name: str, query: str):
        """解析目标知识库：显式库名精确命中优先；'auto'/空/未命中 → 语义路由选库。

        路由仅接受相似度>0 的结果（防退化 embedder 乱路由）；路由异常时
        回退未解析（由调用方走原有报错路径）。

        Returns:
            (kb_info, routed_name)：routed_name 为路由选中的库名（显式命中为 None）
        """
        kb_info = self._knowledge_cache.get(knowledge_name)
        if kb_info:
            return kb_info, None
        if not self._knowledge_cache:
            return None, None
        try:
            ranked = self._get_kb_router().route(query, top_k=1)
        except Exception as e:
            logger.warning(f"[UnstructuredKnowledgeTool] 语义路由失败，回退名称匹配: {e}")
            return None, None
        if not ranked or ranked[0][1] <= 0:
            return None, None
        routed_name, sim = ranked[0]
        logger.info(
            f"[UnstructuredKnowledgeTool] 语义路由: '{knowledge_name}' → "
            f"'{routed_name}' (相似度={sim:.3f})"
        )
        return self._knowledge_cache.get(routed_name), routed_name
    def _load_knowledge_bases(self):
        try:
            unstructured_kbs = self._kb_repo.get_unstructured(enabled_only=True)
            logger.info(f"[UnstructuredKnowledgeTool]  {len(unstructured_kbs)} ")
            for kb in unstructured_kbs:
                kb_name = kb['knowledge_name']
                self._knowledge_cache[kb_name] = kb
                docs = self._doc_repo.get_by_kb(kb['knowledge_base_id'], status='completed')
                kb['_documents'] = docs
                logger.info(
                    f"[UnstructuredKnowledgeTool] 知识库 '{kb_name}' "
                    f"解析到 {len(docs)} 个文档"
                )
        except Exception as e:
            logger.error(f"[UnstructuredKnowledgeTool] : {str(e)}", exc_info=True)
    def _build_tool_description(self) -> str:
        lines = [
            "",
            "",
            "",
        ]
        for kb_name, kb_info in self._knowledge_cache.items():
            kb_desc = kb_info.get('description', '')
            lines.append("")
            lines.append(f">> {kb_name}")
            if kb_desc:
                lines.append(f"   : {kb_desc}")
            docs = kb_info.get('_documents', [])
            if docs:
                lines.append("   :")
                for doc in docs[:10]:
                    lines.append(f"     - {doc['document_name']}")
                if len(docs) > 10:
                    lines.append(f"     ...  {len(docs)} ")
            else:
                lines.append("   ()")
        lines.extend([
            "",
            "",
            "- semantic: LLM ",
            "- metadata: ",
            "- global: ",
            "- adaptive: Agentic RAG 自适应检索（检索→评估→不准则改写重检索，命中率更高但更慢）",
            "",
            "",
            "- knowledge_name: 具体知识库名称；传 'auto' 由语义路由自动选库",
            "- query:  ()",
            "- strategy: semantic（追求命中率可选 adaptive）",
            "- top_k: 5"
        ])
        example = self._build_example()
        lines.extend(["", "", example])
        return "\n".join(lines)
    def _build_example(self) -> str:
        for kb_name in self._knowledge_cache.keys():
            return (
                f"query_unstructured_knowledge(\n"
                f"    knowledge_name='{kb_name}',\n"
                f"    query='<>',\n"
                f"    strategy='semantic',\n"
                f"    top_k=5\n"
                f")"
            )
        return (
            "query_unstructured_knowledge(\n"
            "    knowledge_name='<>',\n"
            "    query='<>',\n"
            "    strategy='semantic',\n"
            "    top_k=5\n"
            ")"
        )
    def invoke(
        self,
        knowledge_name: str,
        query: str,
        strategy: str = "semantic",
        top_k: int = 5
    ) -> str:
        logger.info(
            f"[UnstructuredKnowledgeTool] : ={knowledge_name}, "
            f"={query[:50]}..., ={strategy}"
        )
        kb_info, routed_kb = self._resolve_kb(knowledge_name, query)
        if not kb_info:
            available = list(self._knowledge_cache.keys())
            return self._error_response(
                f" '{knowledge_name}' ",
                f": {', '.join(available) if available else ''}"
            )
        kb_id = kb_info['knowledge_base_id']
        try:
            if strategy == "adaptive":
                # adaptive 是异步 Agentic RAG 循环，sync→async 桥接
                result = _run_coroutine_sync(
                    self.rag_system.retrieve_adaptive_async(query=query, kb_id=kb_id, top_k=top_k)
                )
            else:
                result = self.rag_system.retrieve(
                    query=query,
                    strategy=strategy,
                    top_k=top_k,
                    kb_id=kb_id
                )
            return self._format_result(result, routed_kb=routed_kb)
        except Exception as e:
            logger.error(f"[UnstructuredKnowledgeTool] : {str(e)}", exc_info=True)
            return self._error_response(f": {str(e)}")
    async def ainvoke(
        self,
        knowledge_name: str,
        query: str,
        strategy: str = "semantic",
        top_k: int = 5
    ) -> str:
        """异步版（LangChain coroutine / agent ainvoke 主路径）。

        adaptive → await retrieve_adaptive_async（Agentic RAG 仅检索循环，返 chunks 不生成）
        非 adaptive → to_thread 跑同步 retrieve（不阻塞事件循环）
        """
        logger.info(
            f"[UnstructuredKnowledgeTool] async : ={knowledge_name}, "
            f"={query[:50]}..., ={strategy}"
        )
        kb_info, routed_kb = self._resolve_kb(knowledge_name, query)
        if not kb_info:
            available = list(self._knowledge_cache.keys())
            return self._error_response(
                f" '{knowledge_name}' ",
                f": {', '.join(available) if available else ''}"
            )
        kb_id = kb_info['knowledge_base_id']
        try:
            if strategy == "adaptive":
                result = await self.rag_system.retrieve_adaptive_async(query=query, kb_id=kb_id, top_k=top_k)
            else:
                result = await asyncio.to_thread(
                    self.rag_system.retrieve,
                    query=query, strategy=strategy, top_k=top_k, kb_id=kb_id,
                )
            return self._format_result(result, routed_kb=routed_kb)
        except Exception as e:
            logger.error(f"[UnstructuredKnowledgeTool] : {str(e)}", exc_info=True)
            return self._error_response(f": {str(e)}")
    def _format_result(self, result, routed_kb: str = None) -> str:
        output = {
            "success": True,
            "query": result.query,
            "strategy": result.strategy,
            "latency_ms": result.latency_ms,
            "total_chunks": len(result.chunks),
            "chunks": [
                {
                    "doc_name": chunk.doc_name,
                    "node_title": chunk.node_title,
                    "content": chunk.content[:500] + "..." if len(chunk.content) > 500 else chunk.content,
                    "source": f"{chunk.doc_name} - {chunk.node_title}",
                    "page": chunk.page,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "citation": chunk.citation
                }
                for chunk in result.chunks
            ]
        }
        if routed_kb:
            output["routed_kb"] = routed_kb
        return json.dumps(output, ensure_ascii=False, indent=2)
    def to_langchain_tool(self) -> StructuredTool:
        logger.info("[LLM-] query_unstructured_knowledge - : 4")
        logger.info("[LLM-] query_unstructured_knowledge - : knowledge_name =  ()")
        logger.info("[LLM-] query_unstructured_knowledge - : query =  ()")
        logger.info("[LLM-] query_unstructured_knowledge - : strategy =  ()")
        logger.info("[LLM-] query_unstructured_knowledge - : top_k =  ()")
        logger.debug(f"[LLM-] query_unstructured_knowledge - :\n{self.tool_description}")
        return StructuredTool.from_function(
            func=self.invoke,
            coroutine=self.ainvoke,
            name="query_unstructured_knowledge",
            description=self.tool_description,
            args_schema=UnstructuredKnowledgeInput
        )