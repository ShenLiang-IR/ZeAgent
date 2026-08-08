"""MemoryDecayTrigger：定时衰减记忆 importance + 清理低分记忆。

不继承 ITrigger（ITrigger.handle 绑 dispatch_stream 语义）；独立轻量定时任务，
用 CronTrigger.get_scheduler() 共享的 APScheduler AsyncIOScheduler 单例注册。

config: memory.decay = {enabled, cron, factor, cleanup_below}
- enabled: 是否启用
- cron: cron 表达式（默认 "0 3 * * *" 每日 03:00）
- factor: 衰减因子（importance *= factor，0.95）
- cleanup_below: importance 低于此值的长期记忆被清理（0.1）
"""
from __future__ import annotations

from loguru import logger

from utils.config import get_config


class MemoryDecayTrigger:
    """记忆衰减定时触发器。"""

    def __init__(self):
        cfg = get_config("memory.decay", {}) or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.cron = cfg.get("cron", "0 3 * * *")
        try:
            self.factor = float(cfg.get("factor", 0.95))
        except (TypeError, ValueError):
            self.factor = 0.95
        try:
            self.cleanup_below = float(cfg.get("cleanup_below", 0.1))
        except (TypeError, ValueError):
            self.cleanup_below = 0.1

    async def handle(self, mm=None) -> dict:
        """执行一次衰减 + 清理。返回统计。

        - long_term：衰减 importance 并持久化到 SQLite；低于阈值的删除
        - immediate/short_term：内存层衰减（TTL 自然清理，不持久化）
        - short_term 主动 TTL 巡检：清理低活跃 session 过期记忆（内存+SQLite）
        """
        if mm is None:
            from memory import get_memory_manager
            mm = get_memory_manager()
        decayed = 0
        cleaned = 0
        try:
            # long_term：衰减 + 持久化 + 清理
            all_m = await mm.long_term.get_all()
            for m in all_m:
                m.decay_importance(self.factor)
                if m.importance < self.cleanup_below:
                    await mm.forget(m.id)
                    cleaned += 1
                else:
                    # 持久化衰减后的 importance（SQLiteStorage.save = INSERT OR REPLACE）
                    if hasattr(mm.long_term._storage, "save"):
                        await mm.long_term._storage.save(m)
                    decayed += 1
        except Exception as e:
            logger.warning(f"[MemoryDecayTrigger] long_term 衰减失败: {e}")
        try:
            # immediate/short_term：内存层衰减（不持久化，TTL/容量自然清理）
            for tier in (mm.immediate, mm.short_term):
                for m in await tier.get_all():
                    m.decay_importance(self.factor)
        except Exception as e:
            logger.warning(f"[MemoryDecayTrigger] 短期记忆衰减失败: {e}")
        # short_term 主动 TTL 巡检：清理低活跃 session 的过期记忆（内存+SQLite）
        short_term_cleaned = 0
        try:
            short_term_cleaned = await mm.short_term.cleanup_expired()
        except Exception as e:
            logger.warning(f"[MemoryDecayTrigger] short_term 巡检失败: {e}")
        logger.info(
            f"[MemoryDecayTrigger] decay factor={self.factor}, "
            f"decayed={decayed}, cleaned={cleaned}, short_term_cleaned={short_term_cleaned}"
        )
        return {"decayed": decayed, "cleaned": cleaned, "factor": self.factor,
                "short_term_cleaned": short_term_cleaned}

    async def start(self) -> None:
        """注册 APScheduler 定时 job（与 CronTrigger 共享 scheduler 单例）。"""
        if not self.enabled:
            logger.debug("[MemoryDecayTrigger] disabled (memory.decay.enabled=false), skip")
            return
        try:
            from services.trigger.cron_trigger import CronTrigger
            from apscheduler.triggers.cron import CronTrigger as APSCronTrigger
            sched = CronTrigger.get_scheduler()
            trigger = APSCronTrigger.from_crontab(self.cron, timezone="Asia/Shanghai")
            sched.add_job(
                self.handle,
                trigger=trigger,
                id="memory_decay",
                coalesce=True,
                max_instances=1,
                misfire_grace_time=60,
                replace_existing=True,
            )
            logger.info(f"[MemoryDecayTrigger] registered cron='{self.cron}', factor={self.factor}, cleanup_below={self.cleanup_below}")
        except Exception as e:
            logger.warning(f"[MemoryDecayTrigger] start failed: {e}")
