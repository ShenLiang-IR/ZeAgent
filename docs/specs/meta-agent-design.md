# Meta-Agent 设计文档：通过聊天生成 MCP / Skill / External Tool / Agent

> 日期：2026-07-14 | 状态：MCP 管理工具实现中

## 1. 概念

Meta-Agent 是一个**资源管理助手**——通过自然语言对话，帮助用户创建和管理 MCP 服务、Skill、外部工具和 Agent。

用户只需用自然语言描述需求（如"帮我创建一个 MCP，连接 MySQL，暴露 query_table 工具"），meta-agent 调用管理工具完成创建，并回复结果。

## 2. 架构设计

### 2.1 独立包结构

```
meta_agent/                    # 独立包（不放在 tools/ 下，不被 tool_registry 自动发现）
  __init__.py                  # 包入口，导出工具列表
  mcp_tools.py                 # MCP 管理工具（@tool 装饰器，直接调用 McpService）
  system_prompt.py             # meta-agent 的 system prompt
```

**为什么独立包**：
- 管理工具是高权限操作（创建/删除资源），不应被所有 agent 共享
- tool_registry 自动扫描 tools/ 目录，meta_agent/ 不在其扫描范围
- 只有 meta-agent（agent_name="meta-agent"）专门加载 meta_agent 工具

### 2.2 工具加载逻辑

在 `collect_subagent_tools_async`（tool_collector.py）里，加载内置工具后，检查 agent_name：

```python
# 如果是 meta-agent，加载 meta_agent 包的管理工具
agent_name = subagent_config.get('agent_name', '')
if agent_name == 'meta-agent':
    try:
        from meta_agent import get_management_tools
        mgmt_tools = get_management_tools()
        for tool in mgmt_tools:
            _tag_tool_category(tool, 'management')
        subagent_tools.extend(mgmt_tools)
    except Exception as e:
        logger.warning(f"[MetaAgent] 管理工具加载失败: {e}")
```

### 2.3 MCP 管理工具（本轮实现）

| 工具名 | 参数 | 调用的 service | 说明 |
|--------|------|---------------|------|
| `create_mcp` | name, description, connection_type, exec_cmd, params(args列表), enabled | McpService.register | 创建 MCP 服务配置 |
| `sync_mcp_interfaces` | pr_key_id | McpService.sync_interfaces | 从 MCP server 拉取工具列表，写入 tb_mcp_intfc |
| `test_mcp_connection` | connection_type, exec_cmd, params, connection_url | McpService.test_connect | 测试 MCP 连接，返回工具列表（不写库） |
| `list_mcps` | - | McpService.page | 列出所有 MCP 服务 |
| `delete_mcp` | pr_key_id | McpService.delete | 删除 MCP（级联软删接口） |

**工具实现方式**：用 `@tool` 装饰器（langchain），直接调用 McpService（不经过 HTTP）。

```python
from langchain_core.tools import tool

@tool
def create_mcp(name: str, connection_type: str = "stdio", exec_cmd: str = "", 
               params_args: str = "", description: str = "") -> str:
    """创建一个 MCP 服务配置。
    
    Args:
        name: MCP 服务名称（如 "text-analysis-tools"）
        connection_type: 连接类型（"stdio" 或 "sse"）
        exec_cmd: 执行命令（如 "python" 或完整路径）
        params_args: MCP server 脚本参数（JSON 数组字符串，如 '["path/to/server.py"]'）
        description: MCP 服务描述
    
    Returns:
        创建结果（含 pr_key_id 和 mcp_id）
    """
    from services.mcp_service import McpService
    import json
    service = McpService()
    params = {"args": json.loads(params_args)} if params_args else None
    result = service.register(
        mcp_name=name,
        description=description,
        connection_type=connection_type,
        exec_cmd=exec_cmd,
        params=params,
    )
    return f"MCP '{name}' 创建成功。pr_key_id={result['pr_key_id']}, mcp_id={result['mcp_id']}"
```

### 2.4 Meta-Agent 配置

在 tb_agent 表创建记录：
- agent_name: "meta-agent"
- system_prompt: 引导用户用自然语言创建/管理 MCP（含工具使用说明）
- model_id: "qwen3-coder-next:cloud"（或默认模型）

### 2.5 前端集成

ChatView 的 agent 选择器（/subagents 端点 = AgentRepository.get_all）会自动包含 meta-agent。用户选择 meta-agent 后对话即可。

## 3. 数据流

```
用户："帮我创建一个 MCP，用 python 运行 mcp_server.py"
  → chat API (agent="meta-agent")
    → AgentService.chat → ReActExecutor.execute
      → collect_subagent_tools_async(agent_name="meta-agent")
        → 加载内置工具（echo/word_count 等，meta-agent 可能不需要）
        → 加载 meta_agent 管理工具（create_mcp, sync_mcp_interfaces, ...）
      → build_graph（tools = 管理工具）
      → LLM 调用（system_prompt 引导 + 工具列表）
        → LLM 决定调用 create_mcp(name="...", exec_cmd="python", params_args='["mcp_server.py"]')
          → McpService.register → 写入 tb_mcp
        → LLM 决定调用 sync_mcp_interfaces(pr_key_id=...)
          → McpService.sync_interfaces → 写入 tb_mcp_intfc
        → LLM 回复："已创建 MCP，同步了 N 个接口"
```

## 4. 后续扩展

本轮只实现 MCP 管理工具。后续扩展：
- `meta_agent/skill_tools.py`：create_skill, list_skills, delete_skill, import_local_skill
- `meta_agent/tool_tools.py`：create_external_tool, list_external_tools, delete_external_tool
- `meta_agent/agent_tools.py`：create_agent, update_agent, list_agents, delete_agent

每个文件独立，按需加载。

## 5. 安全考虑

- meta-agent 可创建/删除资源（高权限）
- 当前 enable_permission_check=false（内网模式），可接受
- 生产环境需限制 meta-agent 的使用权限
- 管理工具不注册到全局 tool_registry，只有 meta-agent 可用

## 6. 测试策略

- 单元测试：create_mcp 工具直接调用 McpService（类似 test_mcp_crud.py）
- 集成测试：通过 chat API 调用 meta-agent，验证 LLM 调用管理工具
- 验证：创建 MCP → sync → list → delete 全流程
