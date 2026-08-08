# rag/rag_system/query_rewriter.py
# Query Rewriting：LLM 改写模糊查询，提高检索精度
from loguru import logger
from typing import Optional


class QueryRewriter:
    """LLM-based query rewriting。

    在检索前，用 LLM 将模糊/短查询改写为更精确的检索查询。
    降级安全：LLM 不可用时返回原查询。
    """

    REWRITE_PROMPT = """你是一个查询改写专家。将用户的模糊查询改写为更适合语义检索的精确查询。

规则：
1. 保持原意，不添加无关信息
2. 补充关键术语（如将"营收"改为"营业收入增长率"）
3. 去除口语化表达（如"帮我看看"→ 删除）
4. 输出 1-3 个改写查询，每行一个，不要编号

用户查询：{query}

改写查询："""

    def __init__(self, llm_model=None, enabled: bool = True):
        self._llm = llm_model
        self._enabled = enabled

    async def rewrite(self, query: str) -> list[str]:
        """改写查询。返回 [原始查询, 改写1, 改写2, ...]。

        降级：LLM 不可用或失败 → 返回 [原始查询]
        """
        if not self._enabled or not self._llm:
            return [query]

        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            prompt = self.REWRITE_PROMPT.format(query=query)
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            rewritten = self._parse_response(response)
            logger.info(f"[QueryRewriter] query='{query[:30]}' → {len(rewritten)} variants")
            # 原始查询放第一位（RRF 融合时权重最高）
            return [query] + rewritten
        except Exception as e:
            logger.warning(f"[QueryRewriter] 改写失败: {e}，用原查询")
            return [query]

    def _parse_response(self, response) -> list[str]:
        """解析 LLM 响应为查询列表。"""
        content = ""
        if hasattr(response, "content"):
            content = response.content
        elif isinstance(response, str):
            content = response
        else:
            content = str(response)

        lines = [line.strip() for line in content.strip().split("\n") if line.strip()]
        # 去除编号前缀（如 "1. " "2. "）
        import re
        cleaned = [re.sub(r"^\d+[\.\)]\s*", "", line) for line in lines]
        return [c for c in cleaned if c][:3]  # 最多 3 个改写
