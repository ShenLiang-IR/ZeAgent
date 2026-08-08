from utils.common.json_utils import parse_json_field
from typing import Any, Dict, Optional
from loguru import logger
from tools.registry import get_tool_registry
from tools.external_tool import load_all_external_tools
from utils.mcp_util import create_mcp_langchain_tool
from utils.config import get_config_db, get_config
from .external_tool_builder import create_external_tool
def _tag_tool_category(tool, category: str):
    if hasattr(tool, 'metadata'):
        existing = tool.metadata or {}
        tool.metadata = {**existing, 'tool_category': category}
def _build_mcp_connection_config(mcp_config: Dict[str, Any]) -> Dict[str, Any]:
    import json
    conn = {}
    connection_type = mcp_config.get('connection_type', 'stdio')
    if connection_type == 'HTTP' or mcp_config.get('connection_url'):
        conn['mcp_type'] = 'sse'
        conn['url'] = mcp_config.get('connection_url', '')
        conn['headers'] = {}
        conn['url_params'] = {}
        auth_info = mcp_config.get('auth_info')
        if auth_info:
            try:
                auth_data = parse_json_field(auth_info)
                conn['headers'] = auth_data.get('headers', {})
                conn['url_params'] = auth_data.get('url_params', {})
            except (json.JSONDecodeError, TypeError):
                pass
    else:
        conn['mcp_type'] = 'stdio'
        exec_cmd = mcp_config.get('exec_cmd', '')
        if exec_cmd:
            parts = exec_cmd.split()
            conn['command'] = parts[0] if parts else ''
            conn['args'] = parts[1:] if len(parts) > 1 else []
        else:
            conn['command'] = ''
            conn['args'] = []
        extra_params = mcp_config.get('params')
        if extra_params:
            try:
                params_data = parse_json_field(extra_params)
                conn['env'] = params_data.get('env', {})
                # 从 params 追加 args（如 MCP server 脚本路径），避免调用时缺脚本
                extra_args = params_data.get('args', [])
                if extra_args:
                    conn['args'] = list(conn.get('args', [])) + list(extra_args)
            except (json.JSONDecodeError, TypeError):
                conn['env'] = {}
        else:
            conn['env'] = {}
    return conn
async def collect_all_tools_async(
    return_skill_ids: bool = False
) -> tuple:
    skill_index_text = ""
    skill_ids = []
    all_tools = []
    seen_names = set()
    tool_registry = get_tool_registry()
    registered_tools = tool_registry.get_all()
    for tool in registered_tools:
        # Only include actual tool instances (with name + invoke), not classes/functions
        if not (hasattr(tool, 'name') and hasattr(tool, 'invoke')):
            continue
        tool_name = getattr(tool, 'name', 'unknown')
        _tag_tool_category(tool, 'built_in')
        all_tools.append(tool)
        seen_names.add(tool_name)
    logger.debug(f"已注册 {len(registered_tools)} 个内置工具")
    external_tools = load_all_external_tools()
    external_count = 0
    skipped_count = 0
    for tool_name, external_tool in external_tools.items():
        if external_tool.enabled:
            if tool_name in seen_names:
                logger.debug(f"加载工具: {tool_name}")
                skipped_count += 1
                continue
            langchain_tool = external_tool.to_langchain_tool()
            if langchain_tool:
                _tag_tool_category(langchain_tool, 'api')
                all_tools.append(langchain_tool)
                seen_names.add(tool_name)
                external_count += 1
    logger.debug(f"外部工具: 加载 {external_count} 个, 跳过 {skipped_count} 个")
    try:
        from domain.skill.registry import get_skill_registry
        skill_registry = await get_skill_registry()
        all_skill_metadata = skill_registry.get_all_metadata()
        if all_skill_metadata:
            skill_tools = skill_registry.get_all_langchain_tools()
            skill_count = 0
            for tool in skill_tools:
                tool_name = getattr(tool, 'name', 'unknown')
                if tool_name not in seen_names:
                    _tag_tool_category(tool, 'skill')
                    all_tools.append(tool)
                    seen_names.add(tool_name)
                    skill_count += 1
                else:
                    logger.debug(f"加载工具: {tool_name}")
            skill_ids = list(all_skill_metadata.keys())
            logger.info(f"[-]  {skill_count} ")
        else:
            logger.debug("")
    except ImportError:
        logger.debug("技能模块未安装，跳过")
    except Exception as e:
        logger.warning(f"收集技能工具失败: {e}")
    if return_skill_ids:
        return all_tools, skill_index_text, skill_ids
    return all_tools, skill_index_text
async def collect_subagent_tools_async(
    subagent_config: Dict[str, Any],
    agent_pr_key_id: Optional[int] = None,
    return_skill_ids: bool = False,
    return_kb_stats: bool = False
) -> tuple:
    skill_index_text = ""
    skill_ids = []
    subagent_tools = []
    kb_stats = {
        'structured': 0,
        'unstructured': 0,
        'details': []
    }
    tool_registry = get_tool_registry()
    tool_map = {}
    all_registered_tools = tool_registry.get_all()
    for tool_obj in all_registered_tools:
        if hasattr(tool_obj, 'name'):
            tool_map[tool_obj.name] = tool_obj
    subagent_tool_names = subagent_config.get('tools', [])
    if isinstance(subagent_tool_names, str):
        import json
        try:
            subagent_tool_names = json.loads(subagent_tool_names)
        except json.JSONDecodeError:
            subagent_tool_names = []
    for tool_name in subagent_tool_names:
        if isinstance(tool_name, str) and tool_name in tool_map:
            tool = tool_map[tool_name]
            _tag_tool_category(tool, 'built_in')
            subagent_tools.append(tool)
        elif not isinstance(tool_name, str):
            _tag_tool_category(tool_name, 'built_in')
            subagent_tools.append(tool_name)
    # 自动注入基础工具（http_request, write_file, list_dir），所有 agent 都可用
    _base_tool_names = ['http_request', 'write_file', 'list_dir']
    for btn in _base_tool_names:
        if btn in tool_map and btn not in subagent_tool_names:
            tool = tool_map[btn]
            _tag_tool_category(tool, 'built_in')
            subagent_tools.append(tool)
            logger.debug(f"自动注入基础工具: {btn}")
    subagent_external_tool_names = subagent_config.get('external_tools', [])
    if isinstance(subagent_external_tool_names, str):
        import json
        try:
            subagent_external_tool_names = json.loads(subagent_external_tool_names)
        except json.JSONDecodeError:
            subagent_external_tool_names = []
    for tool_name in subagent_external_tool_names:
        if isinstance(tool_name, str):
            external_tool = create_external_tool(tool_name)
            if external_tool:
                _tag_tool_category(external_tool, 'api')
                subagent_tools.append(external_tool)
        elif not isinstance(tool_name, str):
            _tag_tool_category(tool_name, 'api')
            subagent_tools.append(tool_name)
    mcp_tools_list = subagent_config.get('mcp_tools', [])
    logger.info(f"[MCP] SubAgent {subagent_config.get('agent_id', 'unknown')}  {len(mcp_tools_list)}  MCP : {mcp_tools_list}")
    multi_server_tools = {}
    simple_mcp_names = []
    for item in mcp_tools_list:
        if isinstance(item, str) and ":" in item:
            parts = item.split(":")
            if len(parts) == 3:
                s, ts, t = parts
                if (s, ts) not in multi_server_tools:
                    multi_server_tools[(s, ts)] = []
                if multi_server_tools[(s, ts)] is not None:
                    multi_server_tools[(s, ts)].append(t)
            elif len(parts) == 2:
                s, ts = parts
                multi_server_tools[(s, ts)] = None
        elif isinstance(item, str) and item.strip():
            simple_mcp_names.append(item.strip())
    # 从 agent_pr_key_id 补充 MCP 绑定（与 config['mcp_tools'] 互补，去重）
    if agent_pr_key_id:
        try:
            from infrastructure.database.repositories.agent_relation_repository import AgentRelationRepository
            _rel_repo = AgentRelationRepository()
            _mcp_ids = _rel_repo.get_mcp_ids(agent_pr_key_id)
            if _mcp_ids:
                from infrastructure.database.repositories.mcp_repository import McpRepository
                _mcp_repo = McpRepository()
                for _mid in _mcp_ids:
                    _mcp = _mcp_repo.get_by_id(_mid)
                    if _mcp and _mcp.get('mcp_name') and _mcp['mcp_name'] not in simple_mcp_names:
                        simple_mcp_names.append(_mcp['mcp_name'])
        except Exception as e:
            logger.warning(f"[MCP] 从 agent_pr_key_id 加载 MCP 失败: {e}")
    mcp_loaded_count = 0
    if simple_mcp_names:
        try:
            from infrastructure.database.repositories.mcp_repository import McpRepository, McpIntfcRepository
            mcp_repo = McpRepository()
            intfc_repo = McpIntfcRepository()
            for mcp_name in simple_mcp_names:
                mcp_config = mcp_repo.get_by_name(mcp_name)
                if not mcp_config:
                    logger.warning(f"[MCP]  MCP : {mcp_name}")
                    continue
                mcp_id = mcp_config.get('mcp_id') or mcp_config.get('pr_key_id')
                connection_url = mcp_config.get('connection_url', '')
                connection_type = mcp_config.get('connection_type', '')
                if connection_url or connection_type == 'HTTP':
                    try:
                        from utils.mcp_util import fetch_mcp_tools_from_url
                        conn = _build_mcp_connection_config(mcp_config)
                        url = conn.get('url', '')
                        if url:
                            logger.info(f"[MCP] : {url}")
                            tools = await fetch_mcp_tools_from_url(url)
                            if tools:
                                for tool_def in tools:
                                    try:
                                        langchain_tool = create_mcp_langchain_tool(conn, tool_def)
                                        _tag_tool_category(langchain_tool, 'mcp')
                                        subagent_tools.append(langchain_tool)
                                        tool_name = tool_def.get('name', 'unknown')
                                        logger.info(f"[MCP]  MCP : {mcp_name}:{tool_name}")
                                        mcp_loaded_count += 1
                                    except Exception as e:
                                        tool_name = tool_def.get('name', 'unknown')
                                        logger.error(f"[MCP]  MCP  {mcp_name}:{tool_name}: {str(e)}")
                            else:
                                logger.warning(f"[MCP]  MCP {mcp_name} ")
                        else:
                            logger.warning(f"[MCP] MCP {mcp_name}  connection_url")
                    except Exception as e:
                        logger.error(f"[MCP]  MCP {mcp_name} : {str(e)}")
                else:
                    if not mcp_id:
                        logger.warning(f"[MCP] MCP  mcp_id: {mcp_name}")
                        continue
                    interfaces = intfc_repo.get_by_mcp_id(mcp_id)
                    if not interfaces:
                        logger.warning(f"[MCP] MCP {mcp_name} ")
                        continue
                    for intfc in interfaces:
                        if intfc.get('status') != '1':
                            continue
                        intfc_name = intfc.get('intfc_name', '')
                        if not intfc_name:
                            continue
                        try:
                            conn = _build_mcp_connection_config(mcp_config)
                            # input_param_ex 可能是完整 inputSchema(含 properties/required)或仅 properties 字典
                            input_param_ex = intfc.get('input_param_ex', {})
                            if isinstance(input_param_ex, dict) and 'properties' in input_param_ex:
                                input_schema = input_param_ex
                            else:
                                input_schema = {
                                    'type': 'object',
                                    'properties': input_param_ex,
                                    'required': []
                                }
                            tool_def = {
                                'name': intfc_name,
                                'description': intfc.get('description', ''),
                                'inputSchema': input_schema,
                            }
                            langchain_tool = create_mcp_langchain_tool(conn, tool_def)
                            _tag_tool_category(langchain_tool, 'mcp')
                            subagent_tools.append(langchain_tool)
                            logger.info(f"[MCP]  MCP : {mcp_name}:{intfc_name}")
                            mcp_loaded_count += 1
                        except Exception as e:
                            logger.error(f"[MCP]  MCP  {mcp_name}:{intfc_name}: {str(e)}")
        except Exception as e:
            logger.error(f"[MCP]  MCP : {str(e)}")
    if multi_server_tools:
        try:
            config_db = get_config_db()
            for (s_name, ts_name), selected_tools in multi_server_tools.items():
                mcp_config = config_db.mcps.get_by_name(s_name)
                if not mcp_config:
                    logger.warning(f"[MCP]  MCP : {s_name}")
                    continue
                tool_sets = mcp_config.get('tool_sets', [])
                target_set = next((ts for ts in tool_sets if ts['name'] == ts_name), None)
                if not target_set:
                    logger.warning(f"[MCP]  MCP : {ts_name} (MCP Config: {s_name})")
                    continue
                tools_defs = target_set.get('tools', [])
                conn = mcp_config.get('config_json', {}).get('mcp_connection', {})
                if not conn:
                    conn = mcp_config.get('config_json', {})
                if selected_tools is not None:
                    selected_set = set(selected_tools)
                    tools_defs = [t for t in tools_defs if (t.get('name') if isinstance(t, dict) else t) in selected_set]
                for tool_def in tools_defs:
                    try:
                        langchain_tool = create_mcp_langchain_tool(conn, tool_def)
                        _tag_tool_category(langchain_tool, 'mcp')
                        subagent_tools.append(langchain_tool)
                        tool_name = tool_def.get('name') if isinstance(tool_def, dict) else tool_def
                        logger.info(f"[MCP]  MCP : {tool_name}")
                        mcp_loaded_count += 1
                    except Exception as e:
                        tool_name = tool_def.get('name') if isinstance(tool_def, dict) else tool_def
                        logger.error(f"[MCP]  MCP  {tool_name}: {str(e)}")
        except Exception as e:
            logger.error(f"[MCP]  MCP : {str(e)}")
    logger.info(f"[MCP]  {mcp_loaded_count}  MCP ")
    if agent_pr_key_id:
        try:
            from infrastructure.database.repositories.agent_relation_repository import AgentRelationRepository
            agent_relation_repo = AgentRelationRepository()
            skill_ids = agent_relation_repo.get_skill_ids(agent_pr_key_id)
            if skill_ids:
                from domain.skill.registry import get_skill_registry
                skill_registry = await get_skill_registry()
                skill_tools = skill_registry.get_agent_skills(agent_pr_key_id, agent_relation_repo)
                for tool in skill_tools:
                    _tag_tool_category(tool, 'skill')
                subagent_tools.extend(skill_tools)
                from core.builder.skill_backend import should_use_skill_backend
                use_skills_path = should_use_skill_backend()
                if use_skills_path:
                    logger.info(
                        f"[] Agent={agent_pr_key_id}  {len(skill_ids)} , "
                        f" {len(skill_tools)}  + read_file "
                    )
                else:
                    logger.info(
                        f"[ToolCollector] Agent={agent_pr_key_id} 加载 {len(skill_ids)} 个技能ID, "
                        f"技能工具 {len(skill_tools)} 个"
                    )
            else:
                logger.debug(f"[] Agent={agent_pr_key_id} ")
        except ImportError:
            logger.debug("[] ")
        except Exception as e:
            logger.warning(f"[]  Agent : {e}")
    if agent_pr_key_id:
        try:
            from domain.knowledge.registry import get_knowledge_registry
            from domain.knowledge.entities import KnowledgeType
            from infrastructure.database.repositories.agent_relation_repository import AgentRelationRepository
            if 'agent_relation_repo' not in dir():
                agent_relation_repo = AgentRelationRepository()
            kb_ids = agent_relation_repo.get_knowledge_base_ids(agent_pr_key_id)
            if kb_ids:
                knowledge_registry = await get_knowledge_registry()
                knowledge_tools = knowledge_registry.get_agent_knowledge_tools(
                    agent_pr_key_id, agent_relation_repo
                )
                for tool in knowledge_tools:
                    _tag_tool_category(tool, 'knowledge')
                subagent_tools.extend(knowledge_tools)
                for tool in knowledge_tools:
                    tool_name = getattr(tool, 'name', '')
                    if tool_name in ('query_structured_knowledge', 'execute_sql_template'):
                        kb_stats['structured'] += 1
                    elif tool_name == 'query_unstructured_knowledge':
                        kb_stats['unstructured'] += 1
                for metadata in knowledge_registry.get_bound_metadata(agent_pr_key_id):
                    kb_type = "" if metadata.knowledge_type == KnowledgeType.STRUCTURED else ""
                    sql_count = len(metadata.sql_models) if hasattr(metadata, 'sql_models') else 0
                    detail = f"{metadata.knowledge_name}({kb_type}"
                    if sql_count:
                        detail += f", {sql_count}SQL"
                    detail += ")"
                    kb_stats['details'].append(detail)
                logger.info(
                    f"[]  {len(knowledge_tools)}  Agent  "
                    f"(: {kb_stats['structured']}, : {kb_stats['unstructured']})"
                )
            else:
                logger.debug(f"[] Agent={agent_pr_key_id} ")
        except ImportError:
            logger.debug("[] ")
        except Exception as e:
            logger.warning(f"[]  Agent : {e}")
    # 如果是 meta-agent，加载 meta_agent 包的管理工具（隔离，不注册到全局 tool_registry）
    agent_name = subagent_config.get('agent_name', '')
    if agent_name == 'meta-agent':
        try:
            from meta_agent import get_management_tools
            mgmt_tools = get_management_tools()
            for tool in mgmt_tools:
                _tag_tool_category(tool, 'management')
            subagent_tools.extend(mgmt_tools)
            logger.info(f"[MetaAgent] 加载了 {len(mgmt_tools)} 个管理工具")
        except Exception as e:
            logger.warning(f"[MetaAgent] 管理工具加载失败: {e}")
    # L4: agent 间委派工具（delegation），config 开启时为所有 agent 加载
    # 支持 Agent 级配置覆盖
    from utils.config.config_loader import get_agent_config
    if get_agent_config("agent.execution.delegation.enabled", False, agent_id=agent_pr_key_id):
        try:
            from delegation import get_delegation_tools
            del_tools = get_delegation_tools()
            for t in del_tools:
                _tag_tool_category(t, 'delegation')
            subagent_tools.extend(del_tools)
            logger.info(f"[Delegation] 加载了 {len(del_tools)} 个委派工具")
        except Exception as e:
            logger.warning(f"[Delegation] 委派工具加载失败: {e}")
    # W1: 上游完整结果检索工具，config 开启时为所有 agent 加载（解 dep 文本截断）
    if get_config("agent.execution.upstream_result_tool.enabled", False):
        try:
            from executor.workflow import get_upstream_result_tools
            ur_tools = get_upstream_result_tools()
            for t in ur_tools:
                _tag_tool_category(t, 'upstream_result')
            subagent_tools.extend(ur_tools)
            logger.info(f"[UpstreamResult] 加载了 {len(ur_tools)} 个上游结果工具")
        except Exception as e:
            logger.warning(f"[UpstreamResult] 上游结果工具加载失败: {e}")
    tool_names = [getattr(t, 'name', str(t)) for t in subagent_tools]
    logger.info(f"[SubAgent] Agent={agent_pr_key_id or 'unknown'}, ={len(subagent_tools)}")
    logger.info(f"[SubAgent] : {tool_names}")
    if skill_index_text:
        logger.info(f"[SubAgent] : ")
    if return_skill_ids and return_kb_stats:
        return subagent_tools, skill_index_text, skill_ids, kb_stats
    if return_skill_ids:
        return subagent_tools, skill_index_text, skill_ids
    return subagent_tools, skill_index_text
# collect_subagent_tools() 已删除 — 请使用 collect_subagent_tools_async()