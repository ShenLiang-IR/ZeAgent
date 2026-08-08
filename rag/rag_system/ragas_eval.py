# rag/rag_system/ragas_eval.py
# 完整 RAGAS 评估（可选，需 pip install ragas）
# 评估指标：Faithfulness（忠实度）+ Context Precision（上下文精度）+ Answer Relevancy（回答相关性）
from loguru import logger
from typing import List, Dict, Any, Optional


class RAGASEvaluator:
    """RAGAS 评估器。

    需：pip install ragas
    降级：ragas 未安装时用简化版（Hit Rate + Recall@5）
    """

    def __init__(self, llm_model=None, embedder=None):
        self._llm = llm_model
        self._embedder = embedder
        self._ragas_available = self._check_ragas()

    def _check_ragas(self) -> bool:
        try:
            import ragas
            logger.info(f"[RAGAS] ragas {ragas.__version__} 可用")
            return True
        except ImportError:
            logger.warning("[RAGAS] ragas 未安装，降级为简化评估（Hit Rate）")
            return False

    def evaluate(self, query: str, retrieved_chunks: List[Dict],
                 answer: str = "", ground_truth: str = "") -> Dict[str, Any]:
        """评估单次 RAG 检索质量。

        Args:
            query: 用户查询
            retrieved_chunks: 检索到的 chunks [{content, doc_name, ...}]
            answer: 生成的回答（可选）
            ground_truth: 标准答案（可选，用于对比）

        Returns:
            {faithfulness, context_precision, answer_relevancy, hit_rate}
        """
        if self._ragas_available and self._llm:
            return self._evaluate_ragas(query, retrieved_chunks, answer, ground_truth)
        else:
            return self._evaluate_simple(query, retrieved_chunks, ground_truth)

    def _evaluate_ragas(self, query, chunks, answer, ground_truth) -> Dict:
        """完整 RAGAS 评估。"""
        try:
            from ragas.metrics import faithfulness, context_precision, answer_relevancy
            from ragas import evaluate
            import datasets

            # 构造 RAGAS 数据集
            contexts = [[c["content"] for c in chunks]]
            data = {
                "question": [query],
                "contexts": contexts,
                "answer": [answer or ""],
                "ground_truth": [ground_truth] if ground_truth else [answer or ""],
            }
            ds = datasets.Dataset.from_dict(data)

            # 评估
            result = evaluate(
                dataset=ds,
                metrics=[faithfulness, context_precision, answer_relevancy],
            )
            scores = result.to_pandas().to_dict("records")[0]
            logger.info(f"[RAGAS] faithfulness={scores.get('faithfulness', 0):.2%} "
                        f"context_precision={scores.get('context_precision', 0):.2%} "
                        f"answer_relevancy={scores.get('answer_relevancy', 0):.2%}")
            return {
                "faithfulness": float(scores.get("faithfulness", 0)),
                "context_precision": float(scores.get("context_precision", 0)),
                "answer_relevancy": float(scores.get("answer_relevancy", 0)),
                "mode": "ragas",
            }
        except Exception as e:
            logger.warning(f"[RAGAS] 评估失败: {e}，降级为简化评估")
            return self._evaluate_simple(query, chunks, ground_truth)

    def _evaluate_simple(self, query, chunks, ground_truth) -> Dict:
        """简化评估（无 ragas 依赖）：Hit Rate + Context Coverage。"""
        if not chunks:
            return {"hit_rate": 0.0, "context_coverage": 0.0, "mode": "simple"}

        # Hit Rate：检索结果中是否包含 ground_truth 关键词
        if ground_truth:
            keywords = [w.strip() for w in ground_truth.split() if len(w.strip()) > 1]
            hits = sum(1 for c in chunks if any(kw in c.get("content", "") for kw in keywords))
            hit_rate = hits / max(len(chunks), 1)
        else:
            hit_rate = 1.0 if chunks else 0.0

        # Context Coverage：检索结果总长度（proxy for coverage）
        total_content = sum(len(c.get("content", "")) for c in chunks)
        coverage = min(total_content / 2000, 1.0)  # 2000 chars = 100% coverage

        return {
            "hit_rate": hit_rate,
            "context_coverage": coverage,
            "total_chunks": len(chunks),
            "total_content_chars": total_content,
            "mode": "simple",
        }

    def evaluate_batch(self, queries: List[str], rag_retrieve_fn,
                       ground_truths: List[str] = None) -> Dict[str, Any]:
        """批量评估。

        Args:
            queries: 查询列表
            rag_retrieve_fn: callable(query) → list[chunk dict]
            ground_truths: 标准答案列表（可选）

        Returns:
            {avg_hit_rate, avg_coverage, details: [...]}
        """
        results = []
        for i, query in enumerate(queries):
            gt = ground_truths[i] if ground_truths and i < len(ground_truths) else ""
            chunks = rag_retrieve_fn(query)
            score = self.evaluate(query, chunks, ground_truth=gt)
            results.append({"query": query, **score})

        # 汇总
        avg_hit = sum(r.get("hit_rate", r.get("faithfulness", 0)) for r in results) / max(len(results), 1)
        avg_cov = sum(r.get("context_coverage", r.get("context_precision", 0)) for r in results) / max(len(results), 1)

        logger.info(f"[RAGAS] batch: {len(results)} queries, avg_hit={avg_hit:.2%} avg_cov={avg_cov:.2%}")
        return {
            "total_queries": len(results),
            "avg_hit_rate": avg_hit,
            "avg_context_coverage": avg_cov,
            "details": results,
        }
