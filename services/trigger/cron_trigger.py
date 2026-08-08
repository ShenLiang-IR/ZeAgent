"""CronTrigger：定时触发器。

设计参见 docs/specs/2026-07-19-trigger-registry-design.md §6.2。

要点：
- 用 APScheduler AsyncIOScheduler（与 FastAPI event loop 共享）
- 进程级单例 scheduler，所有 CronTrigger 实例共享
- 标准 cron 表达式（分 时 日 月 周）+ 时区
- misfire_grace_time=60：错过 60 秒内仍补跑
- coalesce=True + max_instances=1：防叠加
"""
from __future__ import annotations

import datetime as dt

from loguru import logger

try:
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger as APSCronTrigger
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    _APSCHEDULER_AVAILABLE = False
    AsyncIOScheduler = None  # type: ignore
    APSCronTrigger = None  # type: ignore
    SQLAlchemyJobStore = None  # type: ignore
    logger.warning("[CronTrigger] apscheduler 未安装，CronTrigger 不可用")

from .base import ITrigger


class CronTrigger(ITrigger):
    """定时触发器：按 cron 表达式触发，调 dispatch_stream。

    用 SQLAlchemyJobStore 持久化 job 到 MySQL，进程重启后未执行的 job
    自动恢复（按 misfire_grace_time 补跑或跳过）。多 worker 部署时
    基于 DB 行锁，同一 job 只被一个 worker 执行。
    """

    # 进程级单例：所有 CronTrigger 实例共享同一 scheduler
    _scheduler: AsyncIOScheduler | None = None

    @classmethod
    def get_scheduler(cls) -> AsyncIOScheduler:
        """获取共享 AsyncIOScheduler 单例。惰性启动。

        jobstore 用 SQLAlchemyJobStore（持久化到 MySQL），
        保证进程重启 / 多 worker 部署时 job 不丢失、不重复执行。
        """
        if not _APSCHEDULER_AVAILABLE:
            raise RuntimeError("apscheduler 未安装；请 pip install apscheduler>=3.11")
        if cls._scheduler is None or not cls._scheduler.running:
            from infrastructure.database.engines import get_config_engine
            engine = get_config_engine()
            cls._scheduler = AsyncIOScheduler(
                jobstores={
                    "default": SQLAlchemyJobStore(engine=engine),
                },
                job_defaults={
                    "coalesce": True,         # 多次错过合并为 1 次
                    "max_instances": 1,        # 同一 job 不并发执行
                    "misfire_grace_time": 60,  # 错过 60 秒内仍补跑
                },
            )
            cls._scheduler.start()
        return cls._scheduler

    async def start(self) -> None:
        """注册 cron job。"""
        cron_expr = self.config["cron"]
        timezone = self.config.get("timezone", "Asia/Shanghai")
        sched = self.get_scheduler()
        # 用 APSCronTrigger 避免与本类同名冲突
        trigger = APSCronTrigger.from_crontab(cron_expr, timezone=timezone)
        sched.add_job(
            self._on_tick,
            trigger=trigger,
            id=self.trigger_id,
            coalesce=True,        # 多次错过合并为 1 次
            max_instances=1,      # 同一 job 不并发执行
            misfire_grace_time=60,  # 错过 60 秒内仍补跑
            replace_existing=True,  # reload 时覆盖旧 job
        )
        logger.info(f"[CronTrigger] started {self.trigger_id}: '{cron_expr}' {timezone}")

    async def stop(self) -> None:
        """移除 cron job。"""
        try:
            sched = self.get_scheduler()
            sched.remove_job(self.trigger_id)
            logger.info(f"[CronTrigger] stopped {self.trigger_id}")
        except Exception as e:
            logger.warning(f"[CronTrigger] stop {self.trigger_id} failed: {e}")

    async def _on_tick(self) -> None:
        """scheduler 触发时调用，构造 event 交给 handle。"""
        event = {"triggered_at": dt.datetime.now().isoformat()}
        try:
            await self.handle(event)
        except Exception as e:
            # handle 内部已 try/except，但兜底防止 scheduler 抛错
            logger.error(f"[CronTrigger] _on_tick {self.trigger_id} failed: {e}", exc_info=True)

