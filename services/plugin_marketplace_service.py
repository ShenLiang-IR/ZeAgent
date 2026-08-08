"""插件市场服务层。

P0 统一插件市场：在现有 MCP 管理之上加"发现/分发/安装"层，支持三种插件类型：
- mcp_server：安装时生成 tb_mcp 记录，复用 MCP 运行时加载
- skill_python：安装时写入 tb_skill 记录 + pip install 到独立 venv
- tool：安装时写入 config/tools/{name}.json，复用 ToolRegistry 加载

安装关系存 tb_plugin_install，linked_resource_id 统一记录运行时资源 ID。
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

from infrastructure.database.repositories.plugin_repository import (
    PluginRepository,
    PluginInstallRepository,
)
from infrastructure.database.repositories.mcp_repository import McpRepository
from services.mcp_service import McpService
from utils.id_generator import generate_plugin_id, generate_plugin_install_id


# 支持的插件类型
PLUGIN_TYPE_MCP = "mcp_server"
PLUGIN_TYPE_SKILL_PYTHON = "skill_python"
PLUGIN_TYPE_SKILL_NODEJS = "skill_nodejs"
PLUGIN_TYPE_SKILL_GO = "skill_go"
PLUGIN_TYPE_TOOL = "tool"


class PluginMarketplaceService:
    def __init__(self):
        self.plugin_repo = PluginRepository()
        self.install_repo = PluginInstallRepository()
        self.mcp_repo = McpRepository()
        self.mcp_service = McpService()

    # ─────────────────── 插件发布（admin） ───────────────────

    def publish_plugin(
        self,
        name: str,
        display_name: str,
        plugin_type: str = PLUGIN_TYPE_MCP,
        description: str = "",
        icon: str = "",
        category: str = "",
        tags: Optional[List[str]] = None,
        author: str = "",
        version: str = "1.0.0",
        mcp_config: Optional[Dict[str, Any]] = None,
        manifest: Optional[Dict[str, Any]] = None,
        status: str = "1",
        workspace_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """发布一个插件到市场（name 唯一）。"""
        if not name:
            raise ValueError("插件 name 不能为空")
        if self.plugin_repo.get_by_name(name):
            raise ValueError(f"插件 name 已存在: {name}")
        plugin_id = generate_plugin_id(name)
        entity = self.plugin_repo.save_plugin(
            plugin_id=plugin_id,
            name=name,
            display_name=display_name or name,
            description=description,
            icon=icon,
            category=category,
            tags=tags or [],
            author=author,
            version=version,
            plugin_type=plugin_type,
            mcp_config=mcp_config or {},
            manifest=manifest or {},
            status=status,
            del_flag="0",
            download_count=0,
            workspace_id=workspace_id,
        )
        if not entity:
            raise RuntimeError("发布插件失败")
        result = self.plugin_repo.get_by_plugin_id(plugin_id)
        logger.info(f"[PluginMarketplace] publish: {name} -> plugin_id={plugin_id} type={plugin_type}")
        return result

    # ─────────────────── 市场浏览 ───────────────────

    def list_marketplace(
        self,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        workspace_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        plugins = self.plugin_repo.list_marketplace(
            category=category, keyword=keyword, status="1",
            workspace_id=workspace_id, limit=limit, offset=offset,
        )
        categories = self.plugin_repo.list_categories()
        return {"list": plugins, "total": len(plugins), "categories": categories}

    def get_plugin_detail(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        return self.plugin_repo.get_by_plugin_id(plugin_id)

    # ─────────────────── 安装 / 卸载 ───────────────────

    async def install_plugin(
        self,
        plugin_id: str,
        workspace_id: Optional[int] = None,
        user_id: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """安装插件。按 plugin_type 路由到对应的 provisioner。"""
        plugin = self.plugin_repo.get_by_plugin_id(plugin_id)
        if not plugin:
            raise ValueError(f"插件不存在: {plugin_id}")
        if plugin.get("status") != "1":
            raise ValueError(f"插件未上架: {plugin_id}")
        # 幂等：同 workspace+user 已安装则直接返回
        existing = self.install_repo.find_install(plugin_id, workspace_id, user_id)
        if existing:
            logger.info(f"[PluginMarketplace] 已安装，跳过: plugin_id={plugin_id}")
            return existing

        install_id = generate_plugin_install_id()
        plugin_type = plugin.get("plugin_type", PLUGIN_TYPE_MCP)

        # 按 type 路由到对应 provisioner
        linked_resource_id = await self._provision_plugin(
            install_id, plugin, plugin_type, workspace_id, user_id, config
        )

        entity = self.install_repo.save_install(
            install_id=install_id,
            plugin_id=plugin_id,
            version=plugin.get("version", "1.0.0"),
            workspace_id=workspace_id,
            user_id=user_id,
            config=config or {},
            linked_mcp_id=linked_resource_id if plugin_type == PLUGIN_TYPE_MCP else "",
            linked_resource_id=linked_resource_id,
            enabled="1",
            del_flag="0",
        )
        if not entity:
            raise RuntimeError("安装插件失败")
        self.plugin_repo.increment_download(plugin_id)
        result = self.install_repo.find_install(plugin_id, workspace_id, user_id)
        logger.info(
            f"[PluginMarketplace] install: plugin_id={plugin_id} install_id={install_id} "
            f"type={plugin_type} resource={linked_resource_id}"
        )
        return result

    async def _provision_plugin(
        self,
        install_id: str,
        plugin: Dict[str, Any],
        plugin_type: str,
        workspace_id: Optional[int],
        user_id: Optional[int],
        config: Optional[Dict[str, Any]],
    ) -> str:
        """按 plugin_type 路由到对应的 provisioner，返回运行时资源 ID。"""
        if plugin_type == PLUGIN_TYPE_MCP:
            return self._provision_mcp(install_id, plugin, workspace_id)
        elif plugin_type in (PLUGIN_TYPE_SKILL_PYTHON, PLUGIN_TYPE_SKILL_NODEJS, PLUGIN_TYPE_SKILL_GO):
            return await self._provision_skill(install_id, plugin, plugin_type, workspace_id, user_id)
        elif plugin_type == PLUGIN_TYPE_TOOL:
            return self._provision_tool(install_id, plugin, workspace_id, user_id)
        else:
            raise ValueError(f"不支持的插件类型: {plugin_type}")

    def _provision_mcp(self, install_id: str, plugin: Dict[str, Any], workspace_id: Optional[int]) -> str:
        """为 mcp_server 插件生成 tb_mcp 配置，返回 mcp_id。

        mcp_name 取 install_id 前 16 位（tb_mcp.mcp_id 为 String(32)，
        mcp_id=MCP_{mcp_name}，需控制总长 < 32）。
        """
        mcp_config = plugin.get("mcp_config", {}) or {}
        mcp_name = f"plugin_{install_id[:16]}"
        created = self.mcp_service.register(
            mcp_name=mcp_name,
            description=f"[plugin] {plugin.get('display_name', plugin.get('name', ''))}",
            category=plugin.get("category", ""),
            connection_type=mcp_config.get("connection_type", "stdio"),
            connection_url=mcp_config.get("connection_url", ""),
            exec_cmd=mcp_config.get("exec_cmd", ""),
            auth_info=mcp_config.get("auth_info", ""),
            timeout=mcp_config.get("timeout", 30000),
            params=mcp_config.get("params"),
            enabled=True,
            workspace_id=workspace_id,
        )
        return created.get("mcp_id", "")

    async def _provision_skill(
        self,
        install_id: str,
        plugin: Dict[str, Any],
        plugin_type: str,
        workspace_id: Optional[int],
        user_id: Optional[int],
    ) -> str:
        """为 skill 类型插件生成 tb_skill 记录 + 创建隔离运行时环境，返回 skill_id。

        - skill_python: 写 tb_skill + 创建 venv（pip install 依赖）
        - skill_nodejs: 写 tb_skill + 创建 node env（npm install 依赖）
        - skill_go: 写 tb_skill + 编译 go binary
        manifest 中需包含 skill 配置（module_path/class_name/function_name/parameters/dependencies 等）。
        """
        from infrastructure.database.repositories.skill_repository import SkillRepository
        from utils.common.visibility import normalize_visibility, visibility_to_is_public

        manifest = plugin.get("manifest", {}) or {}
        name = plugin.get("name", f"skill_{install_id[:8]}")
        display_name = plugin.get("display_name", name)

        # 从 manifest 提取 skill 配置
        config_param = manifest.get("config_param", {})
        if not config_param:
            config_param = {
                "category": manifest.get("category", plugin.get("category", "general")),
                "module_path": manifest.get("module_path", ""),
                "class_name": manifest.get("class_name", ""),
                "function_name": manifest.get("function_name", ""),
                "lazy_load": manifest.get("lazy_load", True),
                "preload_priority": manifest.get("preload_priority", 0),
            }

        # 根据 plugin_type 设置 runtime 字段（SkillLoader 据此路由）
        runtime_map = {
            "skill_python": "python_venv",
            "skill_nodejs": "nodejs",
            "skill_go": "go",
        }
        config_param["runtime"] = runtime_map.get(plugin_type, "")

        input_json_param = ""
        parameters = manifest.get("parameters", [])
        if parameters:
            params_list = [
                {
                    "paramName": p.get("param_name", p.get("paramName", "")),
                    "paramType": p.get("param_type", p.get("paramType", "string")),
                    "paramDesc": p.get("param_desc", p.get("paramDesc", "")),
                    "isRequire": "1" if p.get("required", p.get("isRequire") == "1") else "0",
                }
                for p in parameters
            ]
            input_json_param = json.dumps(params_list, ensure_ascii=False)

        repo = SkillRepository()
        skill_id = f"plugin_{name}"

        # 幂等：同 skill_id 已存在则跳过创建
        existing = repo.get_by_skill_id(skill_id)
        if existing:
            logger.info(f"[PluginMarketplace] skill 已存在，跳过创建: {skill_id}")
            return skill_id

        visibility = normalize_visibility("workspace")
        entity = repo.create(
            skill_id=skill_id,
            skill_name=display_name,
            skill_desc=plugin.get("description", "")[:500],
            config_param=json.dumps(config_param, ensure_ascii=False),
            input_json_param=input_json_param,
            enable_status="1",
            del_flag="0",
            workspace_id=workspace_id,
            creator_id=user_id,
            visibility=visibility,
            is_public=visibility_to_is_public(visibility),
        )
        if not entity:
            raise RuntimeError(f"创建 skill 记录失败: {skill_id}")

        # 创建隔离运行时环境（venv / node env / go binary）
        await self._provision_skill_runtime(skill_id, plugin_type, manifest)

        # 重置 SkillRegistry 使新 skill 可被发现
        try:
            from domain.skill.registry import reset_skill_registry
            reset_skill_registry()
        except Exception as e:
            logger.warning(f"[PluginMarketplace] reset skill registry failed: {e}")

        logger.info(f"[PluginMarketplace] provisioned skill: {skill_id} ({plugin_type})")
        return skill_id

    async def _provision_skill_runtime(self, skill_id: str, plugin_type: str, manifest: Dict[str, Any]) -> None:
        """为 skill 创建隔离运行时环境（venv / node env / go binary）。

        同步等待创建完成（不阻塞太久，venv 创建通常 3-5 秒）。
        失败不阻塞安装（运行时才报错），仅记录 warning。
        """
        try:
            from core.skill.host_manager import SkillHostManager
            host = SkillHostManager.get_instance()

            if plugin_type == "skill_python":
                requirements = manifest.get("dependencies", [])
                if isinstance(requirements, dict):
                    requirements = [f"{k}=={v}" if v else k for k, v in requirements.items()]
                await host.create_venv(skill_id, requirements=requirements)
            elif plugin_type == "skill_nodejs":
                dependencies = manifest.get("dependencies", {})
                entry_script = manifest.get("entry_script")
                await host.create_node_env(skill_id, dependencies=dependencies, entry_script=entry_script)
            elif plugin_type == "skill_go":
                source_path = manifest.get("source_path", "")
                if source_path:
                    await host.create_go_binary(skill_id, source_path)
        except Exception as e:
            logger.warning(f"[PluginMarketplace] skill runtime 创建失败 ({skill_id}, {plugin_type}): {e}")

    def _provision_tool(
        self,
        install_id: str,
        plugin: Dict[str, Any],
        workspace_id: Optional[int],
        user_id: Optional[int],
    ) -> str:
        """为 tool 类型插件写入 config/tools/{name}.json，返回 tool_name。

        manifest 中需包含 tool 配置（description/parameter_descriptions/examples 等）。
        复用 ToolRegistry 加载，安装后 reload_config() 即可生效。
        """
        manifest = plugin.get("manifest", {}) or {}
        name = plugin.get("name", f"tool_{install_id[:8]}")

        # 写入 config/tools/{name}.json
        agent_dir = Path(__file__).resolve().parent.parent
        tools_dir = agent_dir / "config" / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        tool_config_path = tools_dir / f"{name}.json"

        tool_config = {
            "display_name": plugin.get("display_name", name),
            "description": plugin.get("description", ""),
            "parameter_descriptions": manifest.get("parameter_descriptions", {}),
            "return_description": manifest.get("return_description", ""),
            "examples": manifest.get("examples", []),
        }
        with open(tool_config_path, "w", encoding="utf-8") as f:
            json.dump(tool_config, f, ensure_ascii=False, indent=4)

        # 触发 ToolRegistry reload
        try:
            from api.admin.common import reload_config  # 延迟导入：编排函数，非架构依赖
            reload_config()
        except Exception as e:
            logger.warning(f"[PluginMarketplace] reload_config after tool install failed: {e}")

        logger.info(f"[PluginMarketplace] provisioned tool: {name}")
        return name

    async def uninstall_plugin(
        self,
        install_id: str,
        workspace_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> bool:
        """卸载插件：按 plugin_type 清理对应的运行时资源 + 软删安装记录。"""
        install = self.install_repo.get_by_install_id(install_id)
        if install is None:
            installed = self.install_repo.list_installed(workspace_id, user_id)
            install = next((i for i in installed if i["install_id"] == install_id), None)
        if not install:
            return False

        linked_resource_id = install.get("linked_resource_id", "") or install.get("linked_mcp_id", "")
        plugin_id = install.get("plugin_id", "")
        plugin = self.plugin_repo.get_by_plugin_id(plugin_id)
        plugin_type = (plugin or {}).get("plugin_type", PLUGIN_TYPE_MCP)

        # 按 type 路由到对应的清理逻辑
        if plugin_type == PLUGIN_TYPE_MCP:
            self._cleanup_mcp(linked_resource_id)
        elif plugin_type in (PLUGIN_TYPE_SKILL_PYTHON, PLUGIN_TYPE_SKILL_NODEJS, PLUGIN_TYPE_SKILL_GO):
            await self._cleanup_skill(linked_resource_id)
        elif plugin_type == PLUGIN_TYPE_TOOL:
            self._cleanup_tool(linked_resource_id)

        ok = self.install_repo.soft_delete(install["install_id"])
        logger.info(f"[PluginMarketplace] uninstall: install_id={install['install_id']} type={plugin_type} ok={ok}")
        return ok

    def _cleanup_mcp(self, mcp_id: str) -> None:
        """清理 MCP 配置记录。"""
        if not mcp_id:
            return
        mcp = self.mcp_repo.get_by_mcp_id(mcp_id)
        if mcp:
            self.mcp_service.delete(mcp["pr_key_id"])
            logger.info(f"[PluginMarketplace] 清理关联 MCP: {mcp_id}")

    async def _cleanup_skill(self, skill_id: str) -> None:
        """清理 Skill 记录 + 运行时环境 + 重置 SkillRegistry。"""
        if not skill_id:
            return
        from infrastructure.database.repositories.skill_repository import SkillRepository
        repo = SkillRepository()
        existing = repo.get_by_skill_id(skill_id)
        if existing:
            repo.delete_skill(existing.get("pr_key_id"))
            logger.info(f"[PluginMarketplace] 清理关联 Skill: {skill_id}")

        # 清理运行时环境（venv / node env / go binary）
        try:
            from core.skill.host_manager import SkillHostManager
            host = SkillHostManager.get_instance()
            await host.remove_venv(skill_id)
            await host.remove_node_env(skill_id)
            await host.remove_go_binary(skill_id)
        except Exception as e:
            logger.warning(f"[PluginMarketplace] skill runtime 清理失败 ({skill_id}): {e}")

        try:
            from domain.skill.registry import reset_skill_registry
            reset_skill_registry()
        except Exception as e:
            logger.warning(f"[PluginMarketplace] reset skill registry failed: {e}")

    def _cleanup_tool(self, tool_name: str) -> None:
        """删除 config/tools/{name}.json + reload_config。"""
        if not tool_name:
            return
        agent_dir = Path(__file__).resolve().parent.parent
        tool_config_path = agent_dir / "config" / "tools" / f"{tool_name}.json"
        if tool_config_path.exists():
            tool_config_path.unlink()
            logger.info(f"[PluginMarketplace] 清理关联 Tool 配置: {tool_name}")
        try:
            from api.admin.common import reload_config  # 延迟导入：编排函数，非架构依赖
            reload_config()
        except Exception as e:
            logger.warning(f"[PluginMarketplace] reload_config after tool uninstall failed: {e}")

    def list_installed(
        self, workspace_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """列出已安装插件（附带插件元数据）。"""
        installs = self.install_repo.list_installed(workspace_id, user_id)
        result = []
        for inst in installs:
            plugin = self.plugin_repo.get_by_plugin_id(inst["plugin_id"])
            item = {**inst, "plugin": plugin}
            result.append(item)
        return result

    def set_enabled(self, install_id: str, enabled: bool) -> bool:
        """启用/停用已安装插件（按类型同步启停关联资源）。"""
        install = self.install_repo.get_by_install_id(install_id)
        if not install:
            return False

        linked_resource_id = install.get("linked_resource_id", "") or install.get("linked_mcp_id", "")
        plugin_id = install.get("plugin_id", "")
        plugin = self.plugin_repo.get_by_plugin_id(plugin_id)
        plugin_type = (plugin or {}).get("plugin_type", PLUGIN_TYPE_MCP)

        # 按类型同步启停关联资源
        if plugin_type == PLUGIN_TYPE_MCP and linked_resource_id:
            mcp = self.mcp_repo.get_by_mcp_id(linked_resource_id)
            if mcp:
                self.mcp_repo.update(mcp["pr_key_id"], status="1" if enabled else "0")
        elif plugin_type in (PLUGIN_TYPE_SKILL_PYTHON, PLUGIN_TYPE_SKILL_NODEJS, PLUGIN_TYPE_SKILL_GO) and linked_resource_id:
            from infrastructure.database.repositories.skill_repository import SkillRepository
            repo = SkillRepository()
            existing = repo.get_by_skill_id(linked_resource_id)
            if existing:
                repo.save_skill(
                    pr_key_id=existing.get("pr_key_id"),
                    skill_name=existing.get("skill_name", ""),
                    skill_description=existing.get("skill_desc", ""),
                    enabled=enabled,
                )
        # tool 类型：无需额外操作，ToolRegistry 在 reload 时自动加载启用的工具

        return self.install_repo.set_enabled(install_id, enabled)
