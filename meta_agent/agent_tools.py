"""Meta-Agent Agent 管理工具。

直接调用 AgentCrudService（不经过 HTTP），返回 LLM 可读的字符串。
"""
import json
from langchain_core.tools import tool


@tool
async def create_agent(
    name: str,
    system_prompt: str,
    mcps: str = "",
    skills: str = "",
    model_id: str = "",
) -> str:
    """创建一个新的 Agent。当用户想创建一个新的智能体时使用此工具。

    Args:
        name: Agent 名称（如 "text-analysis-agent"）
        system_prompt: 系统提示词（定义 agent 的角色和行为）
        mcps: 要绑定的 MCP 服务名称列表，JSON 数组字符串（如 '["text-analysis-tools"]'），留空则不绑定
        skills: 要绑定的 Skill 名称列表，JSON 数组字符串（如 '["text-stats"]'），留空则不绑定
        model_id: 使用的模型 ID（如 "qwen3-coder-next:cloud"），留空用默认

    Returns:
        创建结果，含 pr_key_id
    """
    from services.agent_crud_service import AgentCrudService

    svc = AgentCrudService()
    mcp_list = []
    if mcps:
        try:
            mcp_list = json.loads(mcps)
        except json.JSONDecodeError:
            return f"参数错误: mcps 不是有效的 JSON 数组: {mcps}"
    skill_list = []
    if skills:
        try:
            skill_list = json.loads(skills)
        except json.JSONDecodeError:
            return f"参数错误: skills 不是有效的 JSON 数组: {skills}"
    try:
        result = svc.create(
            agent_name=name,
            system_prompt=system_prompt,
            mcps=mcp_list,
            skills=skill_list,
            model_id=model_id,
        )
        return f"Agent '{name}' 创建成功。pr_key_id={result['pr_key_id']}"
    except Exception as e:
        return f"创建 Agent 失败: {e}"


@tool
async def list_agents() -> str:
    """列出所有 Agent。"""
    from services.agent_crud_service import AgentCrudService

    svc = AgentCrudService()
    agents = svc.agent_repo.get_all() or []
    lines = []
    for a in agents:
        status = "启用" if a.get("enabled") else "禁用"
        tools = a.get("tools", [])
        mcps = a.get("mcp_tools", [])
        lines.append(
            f"- {a.get('agent_name', '')} "
            f"(pr_key_id={a.get('pr_key_id')}, {status}, "
            f"skills={len(tools)}, mcps={len(mcps)})"
        )
    return f"共 {len(agents)} 个 Agent:\n" + "\n".join(lines)


@tool
async def delete_agent(pr_key_id: str) -> str:
    """删除一个 Agent。

    Args:
        pr_key_id: Agent 的 pr_key_id

    Returns:
        删除结果
    """
    from services.agent_crud_service import AgentCrudService

    svc = AgentCrudService()
    try:
        ok = svc.delete(int(pr_key_id))
        if ok:
            return f"Agent (pr_key_id={pr_key_id}) 删除成功。"
        return f"Agent (pr_key_id={pr_key_id}) 不存在或删除失败。"
    except Exception as e:
        return f"删除失败: {e}"
