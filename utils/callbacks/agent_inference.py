from typing import Optional, Dict, List
from core.subagent.registry import get_subagent_registry
def load_subagent_names() -> List[str]:
    try:
        registry = get_subagent_registry()
        subagents = registry.get_all()
        names = [subagent.name for subagent in subagents]
        return names
    except Exception as e:
        return []
def load_tool_to_subagent_map() -> Dict[str, str]:
    tool_map = {}
    try:
        registry = get_subagent_registry()
        subagents = registry.get_all()
        for subagent in subagents:
            all_tools = []
            if hasattr(subagent, 'tools'):
                tools = subagent.tools if subagent.tools else []
                if isinstance(tools, list):
                    all_tools.extend(tools)
            if hasattr(subagent, 'external_tools'):
                external_tools = subagent.external_tools if subagent.external_tools else []
                if isinstance(external_tools, list):
                    all_tools.extend(external_tools)
            for tool in all_tools:
                if isinstance(tool, str):
                    tool_map[tool] = subagent.name
                elif hasattr(tool, 'name'):
                    tool_map[tool.name] = subagent.name
    except Exception as e:
        pass
    return tool_map
def infer_agent_from_tool(tool_identifier: str, tool_to_subagent_map: Dict[str, str]) -> Optional[str]:
    if not tool_identifier:
        return None
    if tool_identifier.startswith('task:'):
        subagent_type = tool_identifier.split(':', 1)[1]
        return subagent_type.replace('_', ' ').title()
    if tool_identifier in tool_to_subagent_map:
        subagent_name = tool_to_subagent_map[tool_identifier]
        return subagent_name.replace('_', ' ').title()
    return None
def find_agent_from_task_tool(tool_run_map: Dict[str, str]) -> Optional[str]:
    task_tools = [(rid, tid) for rid, tid in tool_run_map.items() if tid.startswith('task:')]
    if task_tools:
        tool_run_id, tool_identifier = task_tools[-1]
        if tool_identifier.startswith('task:'):
            subagent_type = tool_identifier.split(':', 1)[1]
            return subagent_type.replace('_', ' ').title()
    return None
def extract_agent_name(chain_name: str, subagent_names: List[str]) -> Optional[str]:
    if not chain_name or chain_name == 'unknown':
        return None
    chain_lower = chain_name.lower()
    framework_chain_names = ['langgraph', 'agentexecutor']
    if any(framework_name in chain_lower for framework_name in framework_chain_names):
        return None
    subagent_keywords = [name.lower() for name in subagent_names]
    for subagent_name in subagent_names:
        if subagent_name.lower() in chain_lower:
            return subagent_name.replace('_', ' ').title()
    for keyword in subagent_keywords:
        if keyword in chain_lower:
            for subagent_name in subagent_names:
                if subagent_name.lower() == keyword:
                    return subagent_name.replace('_', ' ').title()
    if 'agent' in chain_lower and 'executor' not in chain_lower:
        for keyword in subagent_keywords:
            if keyword in chain_lower:
                for subagent_name in subagent_names:
                    if subagent_name.lower() == keyword:
                        return subagent_name.replace('_', ' ').title()
    return None