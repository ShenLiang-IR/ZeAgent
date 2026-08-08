"""统一插件管理器 — Plugin Manager。

作为插件市场的统一入口，封装 PluginMarketplaceService + SkillHostManager + McpProcessPool，
提供：
- install / uninstall / enable / disable（委托 PluginMarketplaceService）
- list_installed（附带运行时状态：进程数 / venv 是否存在 / 工具是否加载）
- stats（全局统计：各类插件数量、运行时资源占用）
- reload_all（热重载所有已安装插件，集成 reload_config）

设计原则：
- PluginManager 是无状态门面（不缓存），所有状态由底层组件管理
- 委托模式：install/uninstall 委托 PluginMarketplaceService，运行时状态查询委托各 Host
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from loguru import logger

from services.plugin_marketplace_service import (
    PluginMarketplaceService,
    PLUGIN_TYPE_MCP,
    PLUGIN_TYPE_SKILL_PYTHON,
    PLUGIN_TYPE_SKILL_NODEJS,
    PLUGIN_TYPE_SKILL_GO,
    PLUGIN_TYPE_TOOL,
)


class PluginManager:
    """统一插件管理器（门面模式）。"""

    _instance: Optional["PluginManager"] = None

    def __init__(self):
        self._market = PluginMarketplaceService()

    @classmethod
    def get_instance(cls) -> "PluginManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    # ─────────────────── 市场操作（委托 PluginMarketplaceService） ───────────────────

    def list_marketplace(self, **kwargs) -> Dict[str, Any]:
        return self._market.list_marketplace(**kwargs)

    def get_plugin_detail(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        return self._market.get_plugin_detail(plugin_id)

    def publish_plugin(self, **kwargs) -> Dict[str, Any]:
        return self._market.publish_plugin(**kwargs)

    async def install_plugin(self, plugin_id: str, workspace_id: Optional[int] = None,
                        user_id: Optional[int] = None, config: Optional[Dict] = None) -> Dict[str, Any]:
        return await self._market.install_plugin(plugin_id, workspace_id, user_id, config)

    async def uninstall_plugin(self, install_id: str, **kwargs) -> bool:
        return await self._market.uninstall_plugin(install_id, **kwargs)

    def list_installed(self, workspace_id: Optional[int] = None,
                       user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """列出已安装插件，附带运行时状态。"""
        installs = self._market.list_installed(workspace_id, user_id)
        for inst in installs:
            inst["runtime_status"] = self._get_runtime_status(inst)
        return installs

    def set_enabled(self, install_id: str, enabled: bool) -> bool:
        return self._market.set_enabled(install_id, enabled)

    # ─────────────────── 运行时状态查询 ───────────────────

    def _get_runtime_status(self, install: Dict[str, Any]) -> Dict[str, Any]:
        """查询安装实例的运行时状态。"""
        plugin = install.get("plugin", {}) or {}
        plugin_type = plugin.get("plugin_type", PLUGIN_TYPE_MCP)
        resource_id = install.get("linked_resource_id", "") or install.get("linked_mcp_id", "")

        status = {"type": plugin_type, "resource_id": resource_id, "healthy": True}

        if plugin_type == PLUGIN_TYPE_MCP:
            # MCP：检查进程池中是否有活跃连接
            try:
                from tools.data_providers.mcp_client.process_pool import McpProcessPool
                pool = McpProcessPool.get_instance()
                status["pool_size"] = pool._total_size()
            except Exception:
                status["pool_size"] = 0

        elif plugin_type in (PLUGIN_TYPE_SKILL_PYTHON, PLUGIN_TYPE_SKILL_NODEJS, PLUGIN_TYPE_SKILL_GO):
            # Skill：检查 venv/node_env/go_binary 是否存在
            try:
                from core.skill.host_manager import SkillHostManager
                host = SkillHostManager.get_instance()
                if plugin_type == PLUGIN_TYPE_SKILL_PYTHON:
                    status["venv_exists"] = host.has_venv(resource_id)
                    status["healthy"] = status["venv_exists"]
                elif plugin_type == PLUGIN_TYPE_SKILL_NODEJS:
                    status["node_env_exists"] = host.has_node_env(resource_id)
                    status["healthy"] = status["node_env_exists"]
                elif plugin_type == PLUGIN_TYPE_SKILL_GO:
                    status["go_binary_exists"] = host.has_go_binary(resource_id)
                    status["healthy"] = status["go_binary_exists"]
            except Exception:
                pass

        elif plugin_type == PLUGIN_TYPE_TOOL:
            # Tool：检查 JSON 配置文件是否存在
            try:
                from pathlib import Path
                agent_dir = Path(__file__).resolve().parent.parent
                tool_path = agent_dir / "config" / "tools" / f"{resource_id}.json"
                status["config_exists"] = tool_path.exists()
                status["healthy"] = status["config_exists"]
            except Exception:
                pass

        return status

    # ─────────────────── 全局统计 ───────────────────

    def stats(self, workspace_id: Optional[int] = None,
              user_id: Optional[int] = None) -> Dict[str, Any]:
        """全局插件统计。"""
        installs = self._market.list_installed(workspace_id, user_id)

        by_type: Dict[str, int] = {}
        by_status = {"enabled": 0, "disabled": 0}
        healthy_count = 0

        for inst in installs:
            plugin = inst.get("plugin", {}) or {}
            ptype = plugin.get("plugin_type", "unknown")
            by_type[ptype] = by_type.get(ptype, 0) + 1

            if inst.get("enabled") == "1":
                by_status["enabled"] += 1
            else:
                by_status["disabled"] += 1

            rt = self._get_runtime_status(inst)
            if rt.get("healthy"):
                healthy_count += 1

        # 运行时资源统计
        rt_stats = {}
        try:
            from tools.data_providers.mcp_client.process_pool import McpProcessPool
            pool = McpProcessPool.get_instance()
            rt_stats["mcp_pool_size"] = pool._total_size()
        except Exception:
            rt_stats["mcp_pool_size"] = 0

        try:
            from core.skill.host_manager import SkillHostManager
            host = SkillHostManager.get_instance()
            rt_stats["python_venvs"] = len(host.list_venvs())
            rt_stats["node_envs"] = len(host.list_node_envs())
            rt_stats["go_binaries"] = len(host.list_go_binaries())
        except Exception:
            rt_stats["python_venvs"] = 0
            rt_stats["node_envs"] = 0
            rt_stats["go_binaries"] = 0

        return {
            "total_installed": len(installs),
            "by_type": by_type,
            "by_status": by_status,
            "healthy": healthy_count,
            "unhealthy": len(installs) - healthy_count,
            "runtime": rt_stats,
        }

    # ─────────────────── 热重载 ───────────────────

    async def reload_all(self) -> Dict[str, Any]:
        """热重载所有已安装插件的运行时状态。

        委托 reload_config()（已覆盖 22 项缓存刷新），
        + MCP 进程池 shutdown + 重建（使新 MCP 配置生效）。
        """
        results = {"config_reload": False, "mcp_pool_reset": False, "errors": []}

        # 1. reload_config（覆盖 ConfigLoader + ToolRegistry + SkillRegistry + 所有缓存）
        try:
            from api.admin.common import reload_config  # 延迟导入：编排函数，非架构依赖
            reload_config()
            results["config_reload"] = True
        except Exception as e:
            results["errors"].append(f"reload_config: {e}")

        # 2. MCP 进程池重置（使新 MCP 配置的连接生效）
        try:
            from tools.data_providers.mcp_client.process_pool import McpProcessPool, reset_process_pool
            pool = McpProcessPool.get_instance()
            await pool.shutdown()
            reset_process_pool()
            results["mcp_pool_reset"] = True
        except Exception as e:
            results["errors"].append(f"mcp_pool_reset: {e}")

        logger.info(f"[PluginManager] reload_all: {results}")
        return results
