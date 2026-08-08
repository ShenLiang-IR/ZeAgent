"""MemoryConsolidationTrigger：定时按 user 维度合并高相似长期记忆。

与 MemoryDecayTrigger/MemoryPreferenceSummaryTrigger 同构：独立轻量定时任务，
用 CronTrigger.get_scheduler() 共享的 APScheduler 单例注册。

config: memory.consolidation = {enabled, cron, similarity_threshold, max_pairs_per_user}
- enabled: 默认 false（破坏性，保守 opt-in）
- cron: 默认 "0 5 * * *" 每日 05:00（避开 decay 03:00 / preference_summary 04:00）
- similarity_threshold: embedding 余弦相似度阈值（0.85）
- max_pairs_per_user: 每 user 每轮最多合并多少对（10，封顶）

合并复用 ConflictResolver.consolidate_pair：产出合并 content 写入保留方、删除被合并方。
"""
from __future__ import annotations
import math
from loguru import logger
from typing import Any, List, Tuple
from utils.config import get_config


class MemoryConsolidationTrigger:
    def __init__(self):
        cfg = get_config("memory.consolidation", {}) or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.cron = cfg.get("cron", "0 5 * * *")
        try:
            self.similarity_threshold = float(cfg.get("similarity_threshold", 0.85))
        except (TypeError, ValueError):
            self.similarity_threshold = 0.85
        try:
            self.max_pairs_per_user = int(cfg.get("max_pairs_per_user", 10))
        except (TypeError, ValueError):
            self.max_pairs_per_user = 10

    def _make_resolver(self):
        from memory.conflict_resolver import ConflictResolver
        return ConflictResolver()

    async def handle(self, mm=None) -> dict:
        """扫所有 user 的长期记忆，合并高相似对。"""
        from memory import get_memory_manager
        mm = mm or get_memory_manager()
        resolver = self._make_resolver()
        total_merged = 0
        total_pairs = 0
        try:
            all_m = await mm.long_term.get_all()
        except Exception as e:
            logger.warning(f"[Consolidation] get_all 失败: {e}")
            return {"users": 0, "pairs": 0, "merged": 0, "error": str(e)}
        by_user: dict = {}
        for m in all_m:
            by_user.setdefault(m.user_id or "default", []).append(m)
        for uid, mems in by_user.items():
            pairs = self._top_similar_pairs(mems, self.max_pairs_per_user)
            for a, b in pairs:
                total_pairs += 1
                try:
                    a_before = a.content
                    b_snapshot = b.to_dict()
                    merged = await resolver.consolidate_pair(a, b)
                    if not merged:
                        continue
                    a.content = merged
                    a.importance = min(1.0, max(a.importance, b.importance) + 0.05)
                    a.touch()
                    await mm.long_term.update(a)
                    # 审计：合并前记录 a 原内容 + b 完整快照，供回滚
                    await mm._record_audit(
                        op_type="consolidation",
                        workspace_id=a.workspace_id, user_id=a.user_id,
                        kept_id=a.id, kept_content_before=a_before,
                        deleted_snapshot=b_snapshot, merged_content=merged,
                        reason="consolidate_pair")
                    await mm.forget(b.id)
                    total_merged += 1
                except Exception as e:
                    logger.warning(f"[Consolidation] 合并对失败 a={a.id} b={b.id}: {e}")
        mm.invalidate_search_index()
        logger.info(f"[Consolidation] users={len(by_user)}, pairs={total_pairs}, merged={total_merged}")
        return {"users": len(by_user), "pairs": total_pairs, "merged": total_merged}

    def _top_similar_pairs(self, mems: List, cap: int) -> List[Tuple]:
        scored: List[Tuple[float, Any, Any]] = []
        for i in range(len(mems)):
            ei = mems[i].embedding
            if not ei:
                continue
            for j in range(i + 1, len(mems)):
                ej = mems[j].embedding
                if not ej:
                    continue
                sim = self._cosine(ei, ej)
                if sim >= self.similarity_threshold:
                    scored.append((sim, mems[i], mems[j]))
        scored.sort(key=lambda x: x[0], reverse=True)
        used: set = set()
        out: List[Tuple] = []
        for sim, a, b in scored:
            if a.id in used or b.id in used:
                continue
            out.append((a, b))
            used.add(a.id)
            used.add(b.id)
            if len(out) >= cap:
                break
        return out

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("[Consolidation] disabled (memory.consolidation.enabled=false), skip")
            return
        try:
            from services.trigger.cron_trigger import CronTrigger
            from apscheduler.triggers.cron import CronTrigger as APSCronTrigger
            sched = CronTrigger.get_scheduler()
            trigger = APSCronTrigger.from_crontab(self.cron, timezone="Asia/Shanghai")
            sched.add_job(
                self.handle,
                trigger=trigger,
                id="memory_consolidation",
                coalesce=True,
                max_instances=1,
                misfire_grace_time=120,
                replace_existing=True,
            )
            logger.info(f"[Consolidation] registered cron='{self.cron}', "
                        f"thr={self.similarity_threshold}, max_pairs={self.max_pairs_per_user}")
        except Exception as e:
            logger.warning(f"[Consolidation] start failed: {e}")
