# rag/rag_system/agentic_rag.py
# Agentic RAG — LangGraph 图：检索 → 评估 → 生成/改写重检索
# Phase 3: agent 决定何时检索、检索什么
import asyncio
from loguru import logger
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict


class AgenticRAGState(TypedDict):
    """Agentic RAG 状态。

    注：`_grade` 必须声明为正式字段——LangGraph TypedDict StateGraph 仅把
    声明字段作为可靠 channel，未声明 key 在条件边/循环场景可能读不到，
    导致改写重检索循环失效。
    """
    query: str
    kb_id: str
    top_k: int
    retrieved_chunks: list
    attempt: int
    max_attempts: int
    answer: str
    _grade: str


class AgenticRAG:
    """Agentic RAG 图：检索 → 评估相关性 → 生成 / 改写重检索。

    与传统 2-Step RAG 的区别：agent 评估检索结果是否充分，
    不足时改写查询重新检索（最多 max_attempts 轮）。
    """

    GRADE_PROMPT = """你是一个文档相关性评估器。判断以下检索到的文档块是否与用户查询相关。

用户查询：{query}
检索到的文档（前 500 字）：
{chunks}

如果文档包含回答查询所需的信息，回答 "yes"，否则回答 "no"。
仅输出 yes 或 no："""

    GENERATE_PROMPT = """基于以下检索到的文档，回答用户查询。

用户查询：{query}
检索文档：
{context}

回答（基于文档，不要编造）："""

    REWRITE_PROMPT = """用户查询的检索结果不相关。改写查询以获得更好的检索结果。

原查询：{query}
不相关的检索结果（前 200 字）：{chunks}

改写后的查询（更精确、更具检索性）："""

    def __init__(self, rag_system, llm_model=None, max_attempts: int = 3):
        """
        Args:
            rag_system: RAGSystem 实例（retrieve 方法）
            llm_model: LLM 模型（ainvoke）
            max_attempts: 最大检索轮次（防无限循环）
        """
        self._rag = rag_system
        self._llm = llm_model
        self._max_attempts = max_attempts
        self._graph = self._build_graph()  # QA 图（检索→评估→改写/生成，返回 answer）
        self._retrieval_graph = self._build_retrieval_graph()  # 仅检索图（返回 chunks，不生成）

    def _build_graph(self):
        """构建 LangGraph agentic RAG 图。"""
        graph = StateGraph(AgenticRAGState)
        graph.add_node("retrieve", self._retrieve_node)
        graph.add_node("grade", self._grade_node)
        graph.add_node("generate", self._generate_node)
        graph.add_node("rewrite", self._rewrite_node)

        graph.add_edge(START, "retrieve")
        graph.add_edge("retrieve", "grade")
        graph.add_conditional_edges(
            "grade",
            self._decide_after_grading,
            {"generate": "generate", "rewrite": "rewrite"},
        )
        graph.add_edge("rewrite", "retrieve")
        graph.add_edge("generate", END)
        return graph.compile()

    async def _retrieve_node(self, state: AgenticRAGState) -> dict:
        """检索节点：调 RAGSystem.retrieve。kb_id 从 state 读（并发安全）。"""
        query = state["query"]
        kb_id = state.get("kb_id", "default")
        top_k = state.get("top_k", 5)
        attempt = state.get("attempt", 0)
        logger.info(f"[AgenticRAG] retrieve attempt={attempt} query='{query[:50]}' kb={kb_id} top_k={top_k}")
        try:
            # P4: 同步 retrieve 经 to_thread 放到工作线程执行（不阻塞事件循环）
            result = await asyncio.to_thread(
                self._rag.retrieve,
                query=query, strategy="semantic", top_k=top_k,
                kb_id=kb_id,
            )
            chunks = [
                {"content": c.content, "doc_name": c.doc_name,
                 "node_title": c.node_title,
                 "page": c.page, "char_start": c.char_start, "char_end": c.char_end}
                for c in result.chunks
            ]
        except Exception as e:
            logger.warning(f"[AgenticRAG] retrieve 失败: {e}")
            chunks = []
        return {"retrieved_chunks": chunks, "attempt": attempt + 1}

    async def _grade_node(self, state: AgenticRAGState) -> dict:
        """评估节点：判断检索结果是否相关。"""
        chunks = state.get("retrieved_chunks", [])
        attempt = state.get("attempt", 0)

        # 无 LLM → 简单规则：有 chunks 就认为相关
        if not self._llm:
            return {"_grade": "yes" if chunks else "no"}

        if not chunks or attempt >= self._max_attempts:
            return {"_grade": "yes"}  # 达到上限，直接生成

        try:
            from langchain_core.messages import HumanMessage
            chunks_text = "\n---\n".join(c["content"][:500] for c in chunks[:3])
            prompt = self.GRADE_PROMPT.format(query=state["query"], chunks=chunks_text)
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            grade = response.content.strip().lower() if hasattr(response, "content") else str(response).strip().lower()
            logger.info(f"[AgenticRAG] grade={grade} attempt={attempt}")
            return {"_grade": grade}
        except Exception as e:
            logger.warning(f"[AgenticRAG] grade 失败: {e}，默认相关")
            return {"_grade": "yes"}

    def _decide_after_grading(self, state: AgenticRAGState) -> str:
        """条件边：根据 grade 决定生成还是改写。"""
        grade = state.get("_grade", "yes")
        attempt = state.get("attempt", 0)
        if grade == "no" and attempt < self._max_attempts:
            return "rewrite"
        return "generate"

    async def _generate_node(self, state: AgenticRAGState) -> dict:
        """生成节点：基于检索结果生成回答。"""
        chunks = state.get("retrieved_chunks", [])
        if not self._llm or not chunks:
            # 无 LLM 或无 chunks → 返回拼接的 chunks
            answer = "\n---\n".join(c["content"] for c in chunks[:5])
            return {"answer": answer}

        try:
            from langchain_core.messages import HumanMessage
            context = "\n---\n".join(c["content"][:1000] for c in chunks[:5])
            prompt = self.GENERATE_PROMPT.format(query=state["query"], context=context)
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            answer = response.content if hasattr(response, "content") else str(response)
            logger.info(f"[AgenticRAG] generate answer len={len(answer)}")
            return {"answer": answer}
        except Exception as e:
            logger.warning(f"[AgenticRAG] generate 失败: {e}")
            return {"answer": "\n---\n".join(c["content"] for c in chunks[:5])}

    async def _rewrite_node(self, state: AgenticRAGState) -> dict:
        """改写节点：改写查询后重新检索。"""
        if not self._llm:
            return {"query": state["query"]}  # 无 LLM 不改写

        try:
            from langchain_core.messages import HumanMessage
            chunks = state.get("retrieved_chunks", [])
            chunks_text = "\n---\n".join(c["content"][:200] for c in chunks[:2])
            prompt = self.REWRITE_PROMPT.format(
                query=state["query"], chunks=chunks_text
            )
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            new_query = response.content.strip() if hasattr(response, "content") else str(response).strip()
            logger.info(f"[AgenticRAG] rewrite: '{state['query'][:30]}' → '{new_query[:30]}'")
            return {"query": new_query or state["query"]}
        except Exception as e:
            logger.warning(f"[AgenticRAG] rewrite 失败: {e}")
            return {"query": state["query"]}

    async def run(self, query: str, kb_id: str = "default") -> str:
        """运行 Agentic RAG QA 图。返回回答。kb_id/top_k 走 graph state（并发安全）。"""
        initial_state = {
            "query": query,
            "kb_id": kb_id,
            "top_k": 5,
            "retrieved_chunks": [],
            "attempt": 0,
            "max_attempts": self._max_attempts,
            "answer": "",
        }
        result = await self._graph.ainvoke(initial_state)
        return result.get("answer", "")

    # ===== 仅检索模式（返回 chunks，不生成） =====

    def _build_retrieval_graph(self):
        """构建仅检索图：检索→评估→（改写重检索），终止返回 chunks（不生成）。

        与 QA 图的区别：终态不接 generate 节点，改写循环收敛后直接返回
        改善后的检索结果，供外层 agent 继续生成（避免双重生成）。
        """
        graph = StateGraph(AgenticRAGState)
        graph.add_node("retrieve", self._retrieve_node)
        graph.add_node("grade", self._grade_node)
        graph.add_node("rewrite", self._rewrite_node)

        graph.add_edge(START, "retrieve")
        graph.add_edge("retrieve", "grade")
        graph.add_conditional_edges(
            "grade",
            self._decide_after_grading_retrieval,
            {"done": END, "rewrite": "rewrite"},
        )
        graph.add_edge("rewrite", "retrieve")
        return graph.compile()

    def _decide_after_grading_retrieval(self, state: AgenticRAGState) -> str:
        """条件边（仅检索）：grade 后收尾返回 chunks 或改写重检索。"""
        grade = state.get("_grade", "yes")
        attempt = state.get("attempt", 0)
        if grade == "no" and attempt < self._max_attempts:
            return "rewrite"
        return "done"

    async def retrieve_adaptive(self, query: str, kb_id: str = "default", top_k: int = 5) -> list:
        """仅检索模式：检索→评估→（改写重检索）循环，返回改善后的 chunks。

        复用 _retrieve_node/_grade_node/_rewrite_node（不做最终生成，
        避免与外层 agent 双重生成）。kb_id/top_k 走 graph state（并发安全）。

        Returns:
            [{"content", "doc_name"}, ...] 改善后的检索结果
        """
        initial_state = {
            "query": query,
            "kb_id": kb_id,
            "top_k": top_k,
            "retrieved_chunks": [],
            "attempt": 0,
            "max_attempts": self._max_attempts,
            "answer": "",
        }
        result = await self._retrieval_graph.ainvoke(initial_state)
        return result.get("retrieved_chunks", [])
