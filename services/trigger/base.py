"""触发器抽象接口 + 渲染工具。

设计参见 docs/specs/2026-07-19-trigger-registry-design.md §6.1。

要点：
- render_template：纯函数，str.format 风格安全替换；缺 key 兜底返回原文
- ITrigger：抽象基类，子类实现 start/stop；handle 提供统一归约
  （渲染模板 → 调 MultiAgentService.dispatch_stream → 写 tb_trigger_log）
- 方法内懒加载 import MultiAgentService / TriggerLogRepository，
  避免模块顶部触发 utils 与 repositories 的循环 import
"""
from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from string import Formatter
from typing import Any

from loguru import logger


class _SafeFormatter(Formatter):
    """禁止属性/下标访问的 Formatter（防格式化字符串攻击 FSA）。

    str.format 可经 ``{x.__class__.__init__.__globals__}`` 访问对象属性/全局，
    本 Formatter 在 get_field 阶段拒绝含 . 或 [ 的字段名，使属性访问占位符
    保留原样不解析。其余 str.format 语义（``{{`` 转义、缺 key 降级）不变。
    """

    def get_field(self, field_name, args, kwargs):
        if '.' in field_name or '[' in field_name:
            raise ValueError(f"禁止属性/下标访问: {field_name}")
        return super().get_field(field_name, args, kwargs)


_safe_formatter = _SafeFormatter()


def render_template(template: str, ctx: dict[str, Any]) -> str:
    """安全模板渲染：str.format 语义 + 禁止属性访问（防 FSA）。

    保留 str.format 的 ``{{`` 转义与缺 key 降级行为；含属性访问的占位符
    （``{x.__class__}``）经 _SafeFormatter 拒绝，返回模板原文。
    """
    try:
        return _safe_formatter.format(template, **ctx)
    except (KeyError, IndexError, ValueError):
        return template


class ITrigger(ABC):
    """所有触发器实现此接口。生命周期：register → start → handle×N → stop。"""

    def __init__(
        self,
        trigger_id: str,
        config: dict[str, Any],
        target_agent_ids: list,
        target_mode: str,
        message_template: str,
        workspace_id: int,
    ):
        self.trigger_id = trigger_id
        self.config = config
        self.target_agent_ids = target_agent_ids
        self.target_mode = target_mode
        self.message_template = message_template
        self.workspace_id = workspace_id
        # per-trigger 串行化防雪崩；同一触发器并发触发会排队
        self._semaphore = asyncio.Semaphore(1)

    @abstractmethod
    async def start(self) -> None:
        """启动监听（注册 cron job / 路由 / watcher）。"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止监听 + 释放资源。"""
        ...

    async def handle(self, event: dict[str, Any]) -> str:
        """统一归约：渲染模板 → 调 dispatch_stream → 写 log。

        event 示例：
          CronTrigger:      {"triggered_at": "2026-07-19T09:00:00+08:00"}
          WebhookTrigger:   {"payload": {...}, "headers": {...}, "client_ip": "..."}
          FileWatchTrigger: {"file": "data/knowledge/x.md", "event": "modified"}

        Returns:
            log_id（TRG_LOG_ 前缀），可通过 TriggerLogRepository 查询执行历史
        """
        async with self._semaphore:  # 串行化，防雪崩
            log_id = self._gen_log_id()
            started = datetime.now(UTC)
            dispatch_id: str | None = None
            status = "running"
            error: str | None = None
            try:
                message = render_template(self.message_template, event)
                # 懒加载 import：避免模块顶部触发 utils 与 repositories 的循环
                from services.multi_agent_service import MultiAgentService
                svc = MultiAgentService()
                async for ev in svc.dispatch_stream(
                    agent_ids=self.target_agent_ids,
                    message=message,
                    mode=self.target_mode,
                ):
                    # 捕获 dispatch_id 用于关联 tb_dispatch_record
                    if ev.get("type") == "dispatch_started" and ev.get("dispatch_id"):
                        dispatch_id = ev.get("dispatch_id")
                status = "completed"
            except Exception as e:
                logger.error(
                    f"[Trigger {self.trigger_id}] handle failed: {e}",
                    exc_info=True,
                )
                status = "failed"
                error = str(e)[:500]
            finally:
                duration_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
                self._write_log(log_id, event, dispatch_id, status, error, duration_ms)
            return log_id

    def _gen_log_id(self) -> str:
        """生成 TRG_LOG_ 前缀的 log_id。懒加载 import 避免循环。"""
        from utils.id_generator import generate_uuid
        return f"TRG_LOG_{generate_uuid()[:16]}"

    def _write_log(
        self,
        log_id: str,
        event: dict[str, Any],
        dispatch_id: str | None,
        status: str,
        error: str | None,
        duration_ms: int,
    ) -> None:
        """写 tb_trigger_log（同步 DB 操作）。

        DB 写失败不能影响 trigger 主流程；记 warning 即可。
        """
        try:
            from infrastructure.database.repositories.trigger_repository import (
                TriggerLogRepository,
            )
            trigger_type = self.__class__.__name__.replace("Trigger", "").lower()
            TriggerLogRepository().create(
                log_id=log_id,
                trigger_id=self.trigger_id,
                trigger_type=trigger_type,
                event_data=json.dumps(event, ensure_ascii=False, default=str),
                dispatch_id=dispatch_id,
                status=status,
                error=error,
                duration_ms=duration_ms,
            )
        except Exception as e:
            logger.warning(
                f"[Trigger {self.trigger_id}] write log failed: {e}"
            )
