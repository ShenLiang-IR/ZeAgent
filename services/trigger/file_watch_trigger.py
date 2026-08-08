r"""FileWatchTrigger：文件/数据变更触发器。

设计参见 docs/specs/2026-07-19-trigger-registry-design.md §6.4。

要点：
- 用 watchfiles.awatch() 异步生成器监听目录变更
- 防抖：debounce 窗口内同文件多次变更只触发 1 次
- glob 过滤：只处理匹配 glob 模式的文件
- 跨平台：用 pathlib.Path 处理路径；watchfiles 在 Windows 上对 UNC
  \\server\share 路径行为受限，部署用本地盘
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

try:
    from watchfiles import awatch
    from watchfiles.main import Change
    _WATCHFILES_AVAILABLE = True
except ImportError:
    _WATCHFILES_AVAILABLE = False
    awatch = None  # type: ignore
    Change = None  # type: ignore
    logger.warning("[FileWatchTrigger] watchfiles 未安装，FileWatchTrigger 不可用")

from .base import ITrigger


class FileWatchTrigger(ITrigger):
    """文件变更触发器：监听目录，文件 created/modified/deleted 触发。"""

    _task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动后台 watch task。"""
        if not _WATCHFILES_AVAILABLE:
            raise RuntimeError("watchfiles 未安装；请 pip install watchfiles>=1.1")

        watch_path = Path(self.config["watch_path"])
        if not watch_path.exists():
            raise FileNotFoundError(f"watch_path 不存在: {watch_path}")

        event_types = set(self.config.get("event_types", ["added", "modified", "deleted"]))
        debounce_ms = self.config.get("debounce_ms", 5000)
        glob_pattern = self.config.get("glob", "*")

        self._task = asyncio.create_task(
            self._watch_loop(watch_path, event_types, debounce_ms, glob_pattern)
        )
        logger.info(
            f"[FileWatchTrigger] started {self.trigger_id}: "
            f"watch={watch_path}, events={event_types}, debounce={debounce_ms}ms, glob={glob_pattern}"
        )

    async def stop(self) -> None:
        """取消 watch task。"""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info(f"[FileWatchTrigger] stopped {self.trigger_id}")

    async def _watch_loop(
        self,
        watch_path: Path,
        event_types: set,
        debounce_ms: int,
        glob_pattern: str,
    ) -> None:
        """主循环：监听变更 → 防抖 → 调 handle。"""
        pending: dict[str, str] = {}  # file_path -> last_event

        # watch_filter 决定哪些文件事件被 watchfiles 上报
        def _filter(change_type, path):
            try:
                return Path(path).match(glob_pattern)
            except Exception:
                return False

        try:
            async for changes in awatch(str(watch_path), watch_filter=_filter):
                for change_type, file_path in changes:
                    ev_name = change_type.name.lower()  # added/modified/deleted
                    if ev_name not in event_types:
                        continue
                    pending[file_path] = ev_name
                # 处理 pending：debounce 窗口内同文件多次变更只保留最后一次
                await asyncio.sleep(debounce_ms / 1000)
                for file_path, ev_name in list(pending.items()):
                    try:
                        await self.handle({"file": file_path, "event": ev_name})
                    except Exception as e:
                        logger.error(
                            f"[FileWatchTrigger] handle {file_path} failed: {e}",
                            exc_info=True,
                        )
                    pending.pop(file_path, None)
        except asyncio.CancelledError:
            # 优雅停止
            raise
        except Exception as e:
            logger.error(f"[FileWatchTrigger] watch loop {self.trigger_id} crashed: {e}", exc_info=True)
