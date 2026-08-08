from typing import Dict, Optional, Any
from loguru import logger
class ConfigDatabase:
    def __init__(self):
        from infrastructure.database.repositories.agent_repository import AgentRepository
        from infrastructure.database.repositories.api_repository import ApiRepository
        from infrastructure.database.repositories.mode_repository import ModeRepository
        from infrastructure.database.repositories.mcp_repository import McpRepository
        from infrastructure.database.repositories.system_config_repository import SystemConfigRepository
        from infrastructure.database.repositories.knowledge_repository import KnowledgeBaseRepository, KnowledgeBaseSqlModelRepository, KnowledgeBaseTableFieldRepository
        from infrastructure.database.repositories.sys_model_res_mgmt_repository import SysModelResMgmtRepository
        from infrastructure.database.repositories.rls_rule_repository import RLSRuleRepository
        self.agents = AgentRepository()
        self.subagents = self.agents  # 向后兼容 alias（旧代码用 config_db.subagents）
        self.http_configs = ApiRepository()
        self.external_tools = ApiRepository()
        self.modes = ModeRepository()
        self.mcps = McpRepository()
        self.system = SystemConfigRepository()
        self.knowledge_bases = KnowledgeBaseRepository()
        self.knowledge_sql_models = KnowledgeBaseSqlModelRepository()
        self.knowledge_table_fields = KnowledgeBaseTableFieldRepository()
        self.model_res = SysModelResMgmtRepository()
        self.rls_rules = RLSRuleRepository()
        logger.info("[ConfigDatabase] ")
    def load_external_tools_from_json(self, json_path: str = None) -> int:
        """从 JSON 文件导入外部工具配置（种子导入用）。

        原默认读 config/external_tools.json（已删除，数据在 DB）。
        现仅在显式传入 json_path 时导入。
        """
        import json
        import os
        if json_path is None:
            logger.debug("[ConfigDatabase] load_external_tools_from_json: no json_path, skip")
            return 0
        if not os.path.exists(json_path):
            logger.warning(f"外部工具配置文件不存在: {json_path}")
            return 0
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            tools = data.get('external_tools', [])
            count = 0
            for tool in tools:
                parameters_list = tool.get('parameter_list', [])
                success = self.external_tools.save_external_tool_config(
                    name=tool.get('name'),
                    api_endpoint=tool.get('api_endpoint'),
                    method=tool.get('method', 'POST'),
                    display_name=tool.get('display_name', ''),
                    description=tool.get('description', ''),
                    parameter_descriptions=tool.get('parameter_descriptions', {}),
                    return_description=tool.get('return_description', ''),
                    examples=tool.get('examples', []),
                    api_base_url=tool.get('api_base_url'),
                    headers=tool.get('headers', {}),
                    parameters=tool.get('parameters', {}),
                    http_config_name=tool.get('http_config_name'),
                    enabled=tool.get('enabled', True),
                    enable_reranking=tool.get('enable_reranking', False),
                    reranking_config=tool.get('reranking_config'),
                    config_json=tool.get('config_json'),
                    parameters_list=parameters_list
                )
                if success:
                    count += 1
            return count
        except Exception as e:
            logger.error(f"加载外部工具配置失败: {e}", exc_info=True)
            return 0
    def get_system_name(self) -> str:
        return self.system.get_config('system_name') or ''
    def get_system_description(self) -> str:
        return self.system.get_config('system_description') or ''
    def set_system_name(self, name: str) -> bool:
        return self.system.set_config('system_name', name)
    def set_system_description(self, description: str) -> bool:
        return self.system.set_config('system_description', description)
    def get_subagent_config(self, name: str) -> Optional[Dict[str, Any]]:
        agent_id = f'AGT_{name}' if not name.startswith('AGT_') else name
        return self.subagents.get_by_id(agent_id, return_dict=True)
    def get_all_subagents(self, enabled_only: bool = False) -> list[Dict[str, Any]]:
        return self.subagents.get_all(enabled_only=enabled_only)

    def get_effective_agent(self, agent_id) -> Optional[Dict[str, Any]]:
        """线上生效配置：有 published 版本→快照覆盖可变字段；无→工作副本（纯草稿/测试态）。

        运行态（对话/调度）应经此取数，使编辑已发布 agent 不即时影响线上，
        只有审批通过（新版本 published）才切换线上内容。
        """
        import json
        aid = str(agent_id)
        working = self.subagents.get_by_id(aid, return_dict=True)
        if not working:
            return None
        aid_int = int(aid) if aid.lstrip('-').isdigit() else None
        if aid_int is None:
            return working
        try:
            from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository
            pub = AgentVersionRepository().get_published(aid_int)
        except Exception:
            pub = None
        if not pub or not pub.get("snapshot"):
            return working
        try:
            snap = json.loads(pub["snapshot"])
        except Exception:
            return working
        effective = dict(working)
        for k, v in snap.items():
            if v is not None:
                effective[k] = v
        # is_public 由快照 visibility 派生，保持与快照一致
        vis = snap.get("visibility")
        if vis:
            try:
                from utils.common.visibility import visibility_to_is_public
                effective["is_public"] = visibility_to_is_public(vis)
            except Exception:
                pass
        return effective

    def get_all_effective_agents(self, enabled_only: bool = False) -> list:
        """批量返回所有 agent 的生效配置（已发布版本快照优先，无则工作副本）。

        供子代理 registry 等批量加载场景使用——agent 间委派也读已发布版本，
        使编辑已发布 agent 不即时影响委派链。
        """
        import json
        agents = self.subagents.get_all(enabled_only=enabled_only)
        try:
            from infrastructure.database.repositories.agent_version_repository import AgentVersionRepository
            vrepo = AgentVersionRepository()
            result = []
            for a in agents:
                aid = a.get("pr_key_id")
                aid_int = int(aid) if aid is not None and str(aid).lstrip('-').isdigit() else None
                pub = vrepo.get_published(aid_int) if aid_int is not None else None
                if not pub or not pub.get("snapshot"):
                    result.append(a)
                    continue
                try:
                    snap = json.loads(pub["snapshot"])
                    eff = dict(a)
                    for k, v in snap.items():
                        if v is not None:
                            eff[k] = v
                    vis = snap.get("visibility")
                    if vis:
                        try:
                            from utils.common.visibility import visibility_to_is_public
                            eff["is_public"] = visibility_to_is_public(vis)
                        except Exception:
                            pass
                    result.append(eff)
                except Exception:
                    result.append(a)
            return result
        except Exception:
            return agents
    def get_http_config(self, name: str) -> Optional[Dict[str, Any]]:
        return self.http_configs.get_by_name(name)
    def get_all_http_configs(self, enabled_only: bool = False) -> list[Dict[str, Any]]:
        return self.http_configs.get_all(enabled_only=enabled_only)
    def get_external_tool_config(self, name: str) -> Optional[Dict[str, Any]]:
        return self.external_tools.get_by_name(name, return_format='external_tool')
    def get_all_external_tool_configs(self, enabled_only: bool = False) -> list[Dict[str, Any]]:
        return self.external_tools.get_all(enabled_only=enabled_only, return_format='external_tool')
    def get_mode_config(self, name: str) -> Optional[Dict[str, Any]]:
        return self.modes.get_by_name(name)
    def get_mcp_config(self, name: str) -> Optional[Dict[str, Any]]:
        return self.mcps.get_by_name(name)
    def get_all_mcp_configs(self, enabled_only: bool = False) -> list[Dict[str, Any]]:
        return self.mcps.get_all(enabled_only=enabled_only)
    def get_system_config(self, key: str) -> Optional[str]:
        return self.system.get_config(key)
    def get_all_system_configs(self) -> Dict[str, str]:
        return self.system.get_all_configs()
_config_db: Optional[ConfigDatabase] = None
def get_config_db() -> ConfigDatabase:
    global _config_db
    if _config_db is None:
        _config_db = ConfigDatabase()
    return _config_db