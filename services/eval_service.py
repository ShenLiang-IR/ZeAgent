"""端到端评测服务：LLM-as-Judge 评分 Agent 回复。

设计参见 当前文档分析.md §3.7：Agent 端到端评测体系（MVP）。

核心 API：
- judge_response(question, response, expected, criteria) → {score, feedback, judge_model}
- save_result(...) → 存 tb_eval_result

Judge LLM 选择：eval.judge_model_id 配置有则用指定模型，无则用项目默认 LLM（get_default_llm）。
降级：LLM 不可用时返回 score=0 + feedback="judge LLM 不可用"（不抛异常）。
"""
import re

from loguru import logger

JUDGE_PROMPT_TEMPLATE = """你是严格的评测专家。请对以下 Agent 回复评分（0-100 分整数）。

【问题】
{question}

【期望输出】
{expected}

【评分标准】
{criteria}

【Agent 回复】
{response}

请严格按以下格式输出（两行，不要加其他内容）：
SCORE: <0-100 整数>
FEEDBACK: <评语，1-3 句，说明得分/扣分原因>
"""

DEFAULT_CRITERIA = "准确性 + 完整性 + 简洁性，各占 1/3 权重"


class EvalService:
    """端到端评测服务：LLM-as-Judge。"""

    _table_ensured = False

    def _ensure_table(self):
        """确保 eval 表存在（幂等 lazy init，首次用时建表）。

        参考 MultiAgentService._ensure_table 模式：Base.metadata.create_all + checkfirst。
        """
        if EvalService._table_ensured:
            return
        try:
            from infrastructure.database.base import Base
            from infrastructure.database.engines import get_config_engine
            from infrastructure.database.models.eval import EvalDataset, EvalResult, Feedback

            Base.metadata.create_all(
                get_config_engine(),
                tables=[EvalDataset.__table__, EvalResult.__table__, Feedback.__table__],
                checkfirst=True,
            )
            EvalService._table_ensured = True
        except Exception as e:
            logger.warning(f"[Eval] _ensure_table failed (non-fatal): {e}")

    async def judge_response(
        self,
        question: str,
        response: str,
        expected_output: str = "",
        scoring_criteria: str = "",
    ) -> dict:
        """LLM-as-Judge 评分单条 Agent 回复。

        Args:
            question: 用户问题
            response: Agent 回复（被评测的）
            expected_output: 期望输出（标准答案，可选）
            scoring_criteria: 评分标准（可选，默认准确性/完整性/简洁性）

        Returns:
            {score: int 0-100, feedback: str, judge_model: str | None}
            LLM 不可用时 score=0 + feedback 说明原因（不抛异常）
        """
        judge_model_name = None
        try:
            llm = self._resolve_judge_llm()
            if llm is None:
                return {"score": 0, "feedback": "judge LLM 不可用", "judge_model": None}
            judge_model_name = self._get_judge_model_name(llm)
        except Exception as e:
            logger.warning(f"[Eval] judge LLM 不可用: {e}")
            return {"score": 0, "feedback": f"judge LLM 不可用: {e}", "judge_model": None}

        prompt = JUDGE_PROMPT_TEMPLATE.format(
            question=question or "(无)",
            expected=expected_output or "(无)",
            criteria=scoring_criteria or DEFAULT_CRITERIA,
            response=response or "(无)",
        )
        try:
            from langchain_core.messages import HumanMessage
            result = await llm.ainvoke([HumanMessage(content=prompt)])
            content = result.content if hasattr(result, "content") else str(result)
            parsed = self._parse_judge_response(content)
            parsed["judge_model"] = judge_model_name
            return parsed
        except Exception as e:
            logger.error(f"[Eval] judge ainvoke failed: {e}", exc_info=True)
            return {"score": 0, "feedback": f"judge 调用失败: {e}", "judge_model": judge_model_name}

    def _parse_judge_response(self, content: str) -> dict:
        """解析 LLM 回复，提取 SCORE + FEEDBACK。

        格式期望：
            SCORE: 85
            FEEDBACK: 回答准确但不够简洁

        解析失败时 score=0 + feedback 标注解析失败（含原始内容前 200 字）。
        """
        score = 0
        feedback = content
        score_match = re.search(r"SCORE\s*[:：]\s*(\d+)", content, re.IGNORECASE)
        score_found = score_match is not None
        if score_found:
            score = max(0, min(100, int(score_match.group(1))))  # 钳制 0-100
        # FEEDBACK：匹配 FEEDBACK: 后到结尾（DOTALL 跨行）
        fb_match = re.search(r"FEEDBACK\s*[:：]\s*(.+)", content, re.IGNORECASE | re.DOTALL)
        if fb_match:
            feedback = fb_match.group(1).strip()
        if not score_found:
            feedback = f"解析失败（无 SCORE 行）：{content[:200]}"
        return {"score": score, "feedback": feedback, "judge_model": None}

    def _resolve_judge_llm(self):
        """解析 judge LLM：eval.judge_model_id 有则用指定模型，无则 get_default_llm。"""
        from utils.config import get_config
        from utils.llm.llm_factory import get_default_llm, resolve_llm_by_model_id

        default_llm = get_default_llm()
        judge_model_id = get_config("eval.judge_model_id", None)
        if judge_model_id:
            # resolve_llm_by_model_id 从 subagent_config 取 model_id，构造 dict 传入
            return resolve_llm_by_model_id({"model_id": judge_model_id}, default_llm)
        return default_llm

    def _get_judge_model_name(self, llm) -> str | None:
        """从 LLM 实例提取模型名（记录到 tb_eval_result.judge_model）。"""
        try:
            return getattr(llm, "model_name", None) or getattr(llm, "model", None)
        except Exception:
            return None

    async def save_result(
        self,
        dispatch_id: str | None,
        dataset_id: str | None,
        question: str,
        response: str,
        expected_output: str | None,
        score: int,
        judge_feedback: str,
        judge_model: str | None,
        workspace_id: int | None = None,
    ) -> dict | None:
        """存评测结果到 tb_eval_result。失败返回 None（不抛异常）。"""
        self._ensure_table()
        try:
            from infrastructure.database.repositories.eval_repository import EvalResultRepository
            from utils.id_generator import generate_uuid

            repo = EvalResultRepository()
            entity = repo.create(
                result_id=f"EVAL_{generate_uuid()[:16]}",
                dispatch_id=dispatch_id,
                dataset_id=dataset_id,
                question=question,
                response=response,
                expected_output=expected_output,
                score=score,
                judge_feedback=judge_feedback,
                judge_model=judge_model,
                workspace_id=workspace_id,
            )
            if entity:
                return repo._entity_to_dict(entity, None)
            return None
        except Exception as e:
            logger.error(f"[Eval] save_result failed: {e}", exc_info=True)
            return None
