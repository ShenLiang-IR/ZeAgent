"""MemoryPreferenceSummaryTrigger：定时从用户历史会话总结偏好画像存长期记忆。

自动捕获隐式偏好（单轮 _store 漏掉的），如用户反复问辣菜→偏好辣。
与 MemoryDecayTrigger 一样是独立轻量定时任务（不继承 ITrigger），
用 CronTrigger.get_scheduler() 共享的 APScheduler 单例注册。

config: memory.preference_summary = {enabled, cron, lookback_limit, min_conversations}
- enabled: 是否启用（默认 false，保守）
- cron: cron 表达式（默认 "0 4 * * *" 每日 04:00，避开 decay 03:00）
- lookback_limit: 总结时看最近多少条对话（50）
- min_conversations: 至少多少条对话才总结（6，避免单轮就总结）

prompt 模板从提示词管理 DB 读（name=preference_summary_prompt），无则用代码默认兜底。
"""
from __future__ import annotations

from loguru import logger

from utils.config import get_config


class MemoryPreferenceSummaryTrigger:
    """偏好总结定时触发器。"""

    SUMMARY_PROMPT_NAME = "preference_summary_prompt"

    def __init__(self):
        cfg = get_config("memory.preference_summary", {}) or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.cron = cfg.get("cron", "0 4 * * *")
        try:
            self.lookback_limit = int(cfg.get("lookback_limit", 50))
        except (TypeError, ValueError):
            self.lookback_limit = 50
        try:
            self.min_conversations = int(cfg.get("min_conversations", 6))
        except (TypeError, ValueError):
            self.min_conversations = 6

    async def handle(self) -> dict:
        """扫所有用户历史会话，LLM 总结偏好画像存长期记忆。"""
        from utils.db import get_chat_db
        from memory import get_memory_manager
        from utils.llm import get_default_llm
        from langchain_core.messages import HumanMessage
        from infrastructure.database.repositories.prompt_template_repository import PromptTemplateRepository

        chat_db = get_chat_db()
        mm = get_memory_manager()
        llm = get_default_llm()
        summarized = 0
        skipped = 0
        try:
            user_ids = chat_db.get_distinct_user_ids()
        except Exception as e:
            logger.warning(f"[PrefSummary] get_distinct_user_ids failed: {e}")
            return {"summarized": 0, "skipped": 0, "error": str(e)}

        default_prompt = self._default_prompt()
        for uid in user_ids:
            try:
                msgs = chat_db.get_recent_messages_across_sessions(
                    user_id=uid, limit=self.lookback_limit)
                if len(msgs) < self.min_conversations:
                    skipped += 1
                    continue
                # 拼对话历史
                lines = []
                for m in msgs:
                    role = m.get('role', '')
                    content = m.get('content', '')
                    if isinstance(content, dict):
                        content = content.get('text', '') or str(content)
                    tag = '用户' if role in ('1', 'user') else '助手'
                    lines.append(f"{tag}: {str(content)[:200]}")
                conversation_history = "\n".join(lines)

                # 读 DB prompt 模板（提示词管理可编辑），无则默认
                prompt_text = default_prompt.replace('{{conversation_history}}', conversation_history)
                try:
                    tpl = PromptTemplateRepository().get_by_name(self.SUMMARY_PROMPT_NAME)
                    if tpl and tpl.get('content') and tpl.get('enabled') != '0':
                        prompt_text = tpl['content'].replace('{{conversation_history}}', conversation_history)
                except Exception:
                    pass  # DB 读失败用默认

                resp = await llm.ainvoke([HumanMessage(content=prompt_text)])
                result = resp.content if hasattr(resp, 'content') else str(resp)
                result = result.strip()
                import re as _re
                _m = _re.search(r'```(?:json)?\s*(.*?)```', result, _re.DOTALL)
                if _m:
                    result = _m.group(1).strip()
                if not result.startswith('['):
                    _arr = _re.search(r'\[.*\]', result, _re.DOTALL)
                    if _arr:
                        result = _arr.group(0)
                import json as _json
                try:
                    items = _json.loads(result)
                except Exception:
                    items = []
                if not isinstance(items, list) or not items:
                    skipped += 1
                    continue
                # 存前查重：recall 该 user 已有 preference，避免重复存储
                try:
                    existing = await mm.recall(query="偏好", limit=30, user_id=uid, tiers=['long_term'])
                    existing_prefs = [m.content for m in existing
                                      if m.type and getattr(m.type, 'value', str(m.type)) == 'preference']
                except Exception:
                    existing_prefs = []
                deduped = 0
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    content = str(it.get('content', '')).strip()
                    if not content or len(content) < 3:
                        continue
                    # 去重已下沉到 remember 的内置冲突检测（相似候选 LLM 判 ADD/UPDATE/MERGE/NONE），
                    # 不再在此处做朴素包含匹配；LLM 不可用时 remember 自动降级 ADD。
                    try:
                        importance = float(it.get('importance', 0.8))
                    except (TypeError, ValueError):
                        importance = 0.8
                    await mm.remember(
                        content=content,
                        type='preference',
                        importance=importance,
                        user_id=uid,
                        tags=['preference', 'summary', 'auto_summarized']
                    )
                    existing_prefs.append(content)  # 防本轮内重复
                summarized += 1
                if deduped:
                    logger.info(f"[PrefSummary] user {uid} deduped {deduped} duplicate preferences")
            except Exception as e:
                logger.warning(f"[PrefSummary] user {uid} failed: {e}")
        logger.info(f"[PrefSummary] summarized={summarized}, skipped={skipped}, users={len(user_ids)}")
        return {"summarized": summarized, "skipped": skipped, "users": len(user_ids)}

    def _default_prompt(self) -> str:
        """默认偏好总结 prompt（DB 无 preference_summary_prompt 模板时兜底）。"""
        return """从以下用户历史会话总结用户的偏好画像，输出 JSON 数组（无则输出 []）：
{{conversation_history}}

每项格式: {"type":"preference","content":"偏好内容","importance":0.0-1.0}
规则：
- 从用户多次提及/反复选择/明确表达中总结稳定偏好（如"偏好辣食""倾向低风险""常用 python"）
- 隐式偏好（从行为推断）importance 0.8，显式偏好（用户明说）importance 0.9
- 所有偏好 importance>=0.8（存长期记忆，跨会话个性化）
- 只总结有证据的偏好，不要编造
- 每个偏好一条，content 简洁（如"偏好辣食""倾向低风险投资"）
只输出 JSON 数组。"""

    async def start(self) -> None:
        """注册 APScheduler 定时 job（与 CronTrigger 共享 scheduler 单例）。"""
        if not self.enabled:
            logger.debug("[PrefSummary] disabled (memory.preference_summary.enabled=false), skip")
            return
        try:
            from services.trigger.cron_trigger import CronTrigger
            from apscheduler.triggers.cron import CronTrigger as APSCronTrigger
            sched = CronTrigger.get_scheduler()
            trigger = APSCronTrigger.from_crontab(self.cron, timezone="Asia/Shanghai")
            sched.add_job(
                self.handle,
                trigger=trigger,
                id="memory_preference_summary",
                coalesce=True,
                max_instances=1,
                misfire_grace_time=120,
                replace_existing=True,
            )
            logger.info(f"[PrefSummary] registered cron='{self.cron}', lookback={self.lookback_limit}, min_conv={self.min_conversations}")
        except Exception as e:
            logger.warning(f"[PrefSummary] start failed: {e}")
