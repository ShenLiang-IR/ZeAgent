"""TriggerRegistry：触发器注册中心（单例）。

设计参见 docs/specs/2026-07-19-trigger-registry-design.md §6.5。

要点：
- 单例（get_instance），由 server.py lifespan 驱动 load_from_db / shutdown
- _TRIGGER_CLASSES 字典：trigger_type → 具体类
- register(config_row)：实例化 + start + 存到 _triggers
- unregister(trigger_id)：stop + 从 _triggers 移除
- reload(trigger_id)：unregister + 从 DB 取新配置 + register
- load_from_db()：调 TriggerRepository.list_enabled()，逐个 register
- get_webhook_trigger(trigger_id)：路由层调，取已注册的 WebhookTrigger 实例
- shutdown()：全部 unregister + 关闭共享 scheduler
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from .base import ITrigger
from .cron_trigger import CronTrigger
from .file_watch_trigger import FileWatchTrigger
from .webhook_trigger import WebhookTrigger


class TriggerRegistry:
    """触发器注册中心，单例。"""

    _instance: TriggerRegistry | None = None

    @classmethod
    def get_instance(cls) -> TriggerRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._triggers: dict[str, ITrigger] = {}
        # 类型 → 具体类
        self._TRIGGER_CLASSES: dict[str, type] = {
            "cron": CronTrigger,
            "webhook": WebhookTrigger,
            "file_watch": FileWatchTrigger,
        }

    async def load_from_db(self) -> int:
        """启动时加载所有 enabled trigger。

        L9 多副本协调（两种机制，leader_election 优先）：
        1. 动态（W4）：config agent.execution.trigger_leader_election.enabled=true → DB 租约，
           本副本持约（primary）才加载 webhook/file_watch；过期则其他副本接管。
           需配合 start_heartbeat 周期续约 + 失去 leader 时卸载非 cron。
        2. 静态：环境变量 TRIGGER_WORKER_ROLE（未设/primary 加载全部；secondary 仅 cron）。
        默认两者都未启用 → 加载全部（向下兼容单副本）。
        """
        from infrastructure.database.repositories.trigger_repository import TriggerRepository
        from services.trigger.leader_election import TriggerLeaderElection
        rows = TriggerRepository().list_enabled()
        # 决定是否加载非 cron 触发器
        load_non_cron = True
        if TriggerLeaderElection.enabled():
            acquired = TriggerLeaderElection.acquire_or_renew()
            load_non_cron = acquired
            logger.info(f"[TriggerRegistry] leader_election 启用，本副本 {'持约(primary)' if acquired else '非 leader(secondary)'}")
        else:
            import os
            role = os.getenv("TRIGGER_WORKER_ROLE", "primary")
            if role != "primary":
                load_non_cron = False
                logger.info(f"[TriggerRegistry] TRIGGER_WORKER_ROLE={role!r}（非 primary），仅加载 cron")
        if not load_non_cron:
            rows = [r for r in rows if (r.get("trigger_type") or "") == "cron"]
        loaded = 0
        for row in rows:
            try:
                await self.register(row)
                loaded += 1
            except Exception as e:
                logger.error(
                    f"[TriggerRegistry] register {row.get('trigger_id')} failed: {e}",
                    exc_info=True,
                )
        logger.info(f"[TriggerRegistry] loaded {loaded}/{len(rows)} triggers from DB")
        return loaded

    async def start_heartbeat(self, interval: int = 15) -> None:
        """W4：周期续约 leader 租约 + 失去/获得 leader 时重载非 cron 触发器。

        仅 leader_election 启用时有效；失去 leader → 卸载非 cron；重获 → 重新加载。
        """
        from services.trigger.leader_election import TriggerLeaderElection
        if not TriggerLeaderElection.enabled():
            return
        was_leader = TriggerLeaderElection.is_leader()
        logger.info(f"[TriggerRegistry] heartbeat 启动（interval={interval}s），初始 leader={was_leader}")
        while True:
            try:
                await asyncio.sleep(interval)
                acquired = TriggerLeaderElection.acquire_or_renew()
                if acquired != was_leader:
                    # leader 状态切换：重载非 cron 触发器
                    if acquired:
                        logger.info("[TriggerRegistry] 重获 leader，重新加载非 cron 触发器")
                        await self._reload_non_cron_triggers()
                    else:
                        logger.info("[TriggerRegistry] 失去 leader，卸载非 cron 触发器")
                        await self._unload_non_cron_triggers()
                    was_leader = acquired
            except asyncio.CancelledError:
                logger.info("[TriggerRegistry] heartbeat 取消")
                break
            except Exception as e:
                logger.warning(f"[TriggerRegistry] heartbeat 轮次失败: {e}")

    async def _reload_non_cron_triggers(self) -> None:
        """重新加载所有 enabled 非 cron 触发器（leader 接管时）。"""
        from infrastructure.database.repositories.trigger_repository import TriggerRepository
        rows = TriggerRepository().list_enabled()
        for row in rows:
            ttype = row.get("trigger_type") or ""
            tid = row.get("trigger_id")
            if ttype == "cron" or tid in self._triggers:
                continue
            try:
                await self.register(row)
            except Exception as e:
                logger.warning(f"[TriggerRegistry] reload {tid} failed: {e}")

    async def _unload_non_cron_triggers(self) -> None:
        """卸载所有非 cron 触发器（失去 leader 时，避免重复执行）。"""
        non_cron_ids = [
            tid for tid, t in self._triggers.items()
            if t.__class__.__name__.replace("Trigger", "").lower() != "cron"
        ]
        for tid in non_cron_ids:
            await self.unregister(tid)

    async def register(self, config_row: dict[str, Any]) -> ITrigger | None:
        """根据 config_row 实例化 trigger 并 start()。

        Args:
            config_row: 来自 TriggerRepository 的 dict，含 trigger_id/trigger_type/
                config(JSON string)/target_agent_ids/target_mode/message_template/workspace_id

        Returns:
            注册成功的 ITrigger 实例；失败返回 None
        """
        ttype = config_row.get("trigger_type") or ""
        cls = self._TRIGGER_CLASSES.get(ttype)
        if not cls:
            logger.warning(f"[TriggerRegistry] 未知 trigger_type {ttype!r}，跳过")
            return None

        trigger_id = config_row.get("trigger_id") or ""
        if not trigger_id:
            logger.warning("[TriggerRegistry] config_row 缺 trigger_id，跳过")
            return None

        # 解析 config JSON + target_agent_ids 逗号分隔
        try:
            config = json.loads(config_row.get("config") or "{}")
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"[TriggerRegistry] {trigger_id} config JSON 解析失败: {e}")
            return None

        target_agent_ids_str = config_row.get("target_agent_ids") or ""
        target_agent_ids = [s.strip() for s in target_agent_ids_str.split(",") if s.strip()]

        trigger = cls(
            trigger_id=trigger_id,
            config=config,
            target_agent_ids=target_agent_ids,
            target_mode=config_row.get("target_mode") or "parallel",
            message_template=config_row.get("message_template") or "",
            workspace_id=config_row.get("workspace_id") or 0,
        )
        try:
            await trigger.start()
        except Exception as e:
            logger.error(
                f"[TriggerRegistry] trigger {trigger_id} start failed: {e}",
                exc_info=True,
            )
            return None
        self._triggers[trigger_id] = trigger
        logger.info(f"[TriggerRegistry] registered {trigger_id} ({ttype})")
        return trigger

    async def unregister(self, trigger_id: str) -> None:
        """stop + 从 _triggers 移除。"""
        trigger = self._triggers.pop(trigger_id, None)
        if trigger is None:
            return
        try:
            await trigger.stop()
        except Exception as e:
            logger.warning(f"[TriggerRegistry] unregister {trigger_id} stop failed: {e}")
        logger.info(f"[TriggerRegistry] unregistered {trigger_id}")

    async def reload(self, trigger_id: str) -> ITrigger | None:
        """配置变更后热重载：先 stop 旧实例 → 从 DB 取新配置 → register。

        若 DB 中该 trigger 已 disabled/del，则只 unregister。
        """
        await self.unregister(trigger_id)
        from infrastructure.database.repositories.trigger_repository import TriggerRepository
        row = TriggerRepository().get_by_trigger_id(trigger_id)
        if not row:
            logger.info(f"[TriggerRegistry] reload {trigger_id}: row not found, unregistered only")
            return None
        if row.get("enabled") != "1":
            logger.info(f"[TriggerRegistry] reload {trigger_id}: disabled, unregistered only")
            return None
        return await self.register(row)

    async def get_webhook_trigger(self, trigger_id: str) -> WebhookTrigger | None:
        """供路由层调用：取已注册的 webhook trigger 实例做验签。

        若 trigger_id 不存在或不是 WebhookTrigger，返回 None。
        """
        trigger = self._triggers.get(trigger_id)
        return trigger if isinstance(trigger, WebhookTrigger) else None

    async def get_trigger(self, trigger_id: str) -> ITrigger | None:
        """取已注册的任意 trigger 实例（用于 test endpoint 手动触发）。"""
        return self._triggers.get(trigger_id)

    async def shutdown(self) -> None:
        """全部 unregister + 关闭共享 scheduler。"""
        trigger_ids = list(self._triggers.keys())
        for tid in trigger_ids:
            await self.unregister(tid)
        # 关闭共享 CronTrigger scheduler（如果有）
        try:
            if CronTrigger._scheduler is not None:
                if CronTrigger._scheduler.running:
                    CronTrigger._scheduler.shutdown(wait=False)
                CronTrigger._scheduler = None
        except Exception as e:
            logger.warning(f"[TriggerRegistry] shutdown scheduler failed: {e}")
        logger.info("[TriggerRegistry] shutdown complete")
