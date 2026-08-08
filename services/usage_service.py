"""UsageService：token 用量记录 + 成本计算。

设计参见 docs/specs/2026-07-19-usage-tracking-design.md §4。

第一期硬编码常用模型单价（qwen-turbo / gpt-4 / claude 等），
第二期切 tb_model_pricing 表。
"""

from loguru import logger

# ─── 模型单价矩阵（美元 per 1k tokens，第一期硬编码） ───
# 第二期切 tb_model_pricing 表，与 tb_model_config 联动
MODEL_PRICING = {
    # OpenAI 系列
    "gpt-4":            {"input": 0.03,    "output": 0.06},
    "gpt-4-turbo":      {"input": 0.01,    "output": 0.03},
    "gpt-4o":           {"input": 0.005,   "output": 0.015},
    "gpt-4o-mini":      {"input": 0.00015, "output": 0.0006},
    "gpt-3.5-turbo":    {"input": 0.0005,  "output": 0.0015},
    # Claude 系列
    "claude-3-haiku":   {"input": 0.00025, "output": 0.00125},
    "claude-3-sonnet":  {"input": 0.003,   "output": 0.015},
    "claude-3-opus":    {"input": 0.015,   "output": 0.075},
    # 通义千问（人民币价 → 美元按 7:1 简化）
    "qwen-turbo":       {"input": 0.0003 / 7,  "output": 0.0006 / 7},
    "qwen-plus":        {"input": 0.002 / 7,   "output": 0.006 / 7},
    "qwen-max":         {"input": 0.02 / 7,    "output": 0.06 / 7},
}


class UsageService:
    """token 用量记录 + 成本计算服务。"""

    def record_usage(
        self,
        dispatch_id: str,
        workspace_id: int,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        agent_id: int | None = None,
        user_id: str | None = None,
        duration_ms: int | None = None,
        trigger_id: str | None = None,
    ) -> dict | None:
        """记录一次 LLM 调用的 token 用量 + 计算成本。

        异步场景下调用方可用 asyncio.create_task 包裹避免阻塞。
        """
        try:
            from infrastructure.database.repositories.usage_repository import UsageRepository
            from utils.id_generator import generate_uuid

            cost = self._calc_cost(model_id, prompt_tokens, completion_tokens)
            total = prompt_tokens + completion_tokens

            row = UsageRepository().create(
                usage_id=f"USAGE_{generate_uuid()[:16]}",
                dispatch_id=dispatch_id,
                trigger_id=trigger_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
                model_id=model_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total,
                cost_usd=cost,
                duration_ms=duration_ms,
            )
            logger.info(
                f"[Usage] recorded: dispatch={dispatch_id}, model={model_id}, "
                f"tokens={total}, cost=${cost:.6f}"
            )
            # 业务指标：token 消耗（metrics 失败不影响 usage 记录）
            try:
                from utils.observability.metrics import LLM_TOKENS_TOTAL
                if prompt_tokens:
                    LLM_TOKENS_TOTAL.labels(type="prompt", model=model_id).inc(prompt_tokens)
                if completion_tokens:
                    LLM_TOKENS_TOTAL.labels(type="completion", model=model_id).inc(completion_tokens)
            except Exception:
                pass
            return row
        except Exception as e:
            logger.warning(f"[Usage] record failed (non-fatal): {e}")
            return None

    def _calc_cost(self, model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
        """按模型单价计算美元成本。

        未知模型返回 0（不抛异常）。
        """
        pricing = MODEL_PRICING.get(model_id)
        if not pricing:
            return 0.0
        # 单价是 per 1k tokens
        input_cost = (prompt_tokens / 1000) * pricing["input"]
        output_cost = (completion_tokens / 1000) * pricing["output"]
        return round(input_cost + output_cost, 6)
