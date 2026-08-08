"""配置文件热重载监听器。

监听 config/ 目录下所有运行时配置文件的变更，自动触发 reload_config()，
实现真正的动态加载——直接编辑配置文件后无需重启或调 API 即可生效。

监听的文件（运行时实际被加载的）：
  - agent_config.json      — 主配置（LLM/Agent/Memory/RAG/Embedding/Database/Langfuse 等，原 db_config.json + langfuse.json 已合并）
  - tools/*.json           — 工具描述配置

不监听的文件（种子/模板/文档，运行时不加载）：
  - *.example              — 模板文件
  - subagents/*.json       — 种子/文档文件（运行时从 DB 读取）
  - README.md              — 文档

已删除的独立配置文件（合并到 agent_config.json）：
  - db_config.json         — 已合并到 agent_config.json 的 database 段
  - langfuse.json          — 已合并到 agent_config.json 的 observability.langfuse 段
  - http_config.json       — 种子文件（运行时从 DB 读取），已删除
  - external_tools.json    — 种子文件（运行时从 DB 读取），已删除
  - permissions.json       — 已废弃：权限已迁移到 DB (tb_role_permission 表)

核心设计：
- 基于 watchfiles（已在 FileWatchTrigger 中使用，无需新增依赖）
- 防抖机制：快速连续保存仅触发一次 reload
- 异步非阻塞：watcher 跑在独立 asyncio.Task 中，不阻塞主事件循环
- 优雅启停：FastAPI lifespan startup/shutdown 管理生命周期
- 容错：watchfiles 不可用或目录不存在时仅警告，不阻塞启动
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

try:
    from watchfiles import awatch
    _WATCHFILES_AVAILABLE = True
except ImportError:  # pragma: no cover
    _WATCHFILES_AVAILABLE = False
    awatch = None  # type: ignore


# 防抖窗口（秒）：编辑器保存通常触发多次文件事件，在此窗口内只 reload 一次
_DEBOUNCE_SECONDS: float = 1.0

# 后台 task 引用，用于 shutdown 取消
_watch_task: asyncio.Task | None = None

# 运行时实际加载的配置文件名（顶层）——仅 agent_config.json
_TOP_LEVEL_WATCHED_FILES = frozenset({
    "agent_config.json",
})

# 运行时实际加载的子目录（目录内所有 .json 都监听）
_WATCHED_SUBDIRS = frozenset({
    "tools",
})


def _get_config_dir() -> Path:
    """获取 config/ 目录的绝对路径。"""
    return Path(__file__).parent.parent.parent / "config"


def _is_watched_file(file_path: Path, config_dir: Path) -> bool:
    """判断变更的文件是否需要触发热重载。

    规则：
    - 顶层：仅监听 _TOP_LEVEL_WATCHED_FILES 中的文件
    - tools/ 子目录：监听所有 .json 文件
    - 排除：.example 文件、非 .json 文件
    """
    name = file_path.name

    # 排除 .example 模板文件
    if name.endswith(".example"):
        return False

    # 计算相对于 config/ 的路径
    try:
        rel = file_path.relative_to(config_dir)
    except ValueError:
        return False

    parts = rel.parts

    # 顶层文件
    if len(parts) == 1:
        return name in _TOP_LEVEL_WATCHED_FILES

    # 子目录文件
    if len(parts) == 2 and parts[0] in _WATCHED_SUBDIRS:
        return name.endswith(".json")

    return False


async def start_config_watcher() -> None:
    """启动配置文件监听器。

    在 FastAPI lifespan startup 阶段调用。
    失败不抛异常，仅记录日志（不影响 server 正常启动）。
    """
    global _watch_task

    if not _WATCHFILES_AVAILABLE:
        logger.warning("[ConfigWatcher] watchfiles 不可用，跳过配置文件热重载监听")
        return

    config_dir = _get_config_dir()
    if not config_dir.is_dir():
        logger.warning(f"[ConfigWatcher] {config_dir} 不存在，跳过监听")
        return

    _watch_task = asyncio.create_task(_watch_loop(config_dir))
    logger.info(
        f"[ConfigWatcher] 已启动，监听目录: {config_dir} "
        f"(文件: {', '.join(sorted(_TOP_LEVEL_WATCHED_FILES))}, "
        f"子目录: {', '.join(sorted(_WATCHED_SUBDIRS))})"
    )


async def stop_config_watcher() -> None:
    """停止配置文件监听器。

    在 FastAPI lifespan shutdown 阶段调用。
    """
    global _watch_task

    if _watch_task is not None and not _watch_task.done():
        _watch_task.cancel()
        try:
            await _watch_task
        except asyncio.CancelledError:
            pass
    _watch_task = None
    logger.info("[ConfigWatcher] 已停止")


async def _watch_loop(config_dir: Path) -> None:
    """主监听循环。

    递归监听 config/ 目录，过滤出运行时配置文件变更事件。
    每次检测到变更时取消之前的 pending reload 并重新开始防抖窗口，
    确保仅在文件变更稳定后的 _DEBOUNCE_SECONDS 秒执行一次 reload。
    """
    pending_reload: asyncio.Task | None = None

    async def _debounced_reload(changed_files: list[str]) -> None:
        """防抖等待后调用 reload_config()。"""
        await asyncio.sleep(_DEBOUNCE_SECONDS)
        try:
            from api.admin.common import reload_config
            reload_config()
            files_str = ", ".join(changed_files)
            logger.info(f"[ConfigWatcher] 检测到配置变更 ({files_str})，已自动重载运行时配置")
        except Exception as e:
            logger.error(f"[ConfigWatcher] 配置重载失败: {e}", exc_info=True)

    try:
        async for changes in awatch(str(config_dir), recursive=True):
            # 收集本批次中需要监听的变更文件
            watched_changes: list[str] = []
            for _change_type, file_path in changes:
                p = Path(file_path)
                if _is_watched_file(p, config_dir):
                    watched_changes.append(p.name)

            if not watched_changes:
                continue

            # 取消之前的 pending reload，重新开始防抖
            if pending_reload is not None and not pending_reload.done():
                pending_reload.cancel()
                try:
                    await pending_reload
                except (asyncio.CancelledError, Exception):
                    pass
            pending_reload = asyncio.create_task(_debounced_reload(watched_changes))
    except asyncio.CancelledError:
        if pending_reload is not None and not pending_reload.done():
            pending_reload.cancel()
        raise
    except Exception as e:
        logger.error(f"[ConfigWatcher] 监听循环异常退出: {e}", exc_info=True)
