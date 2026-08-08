## agent 管理
Agent 配置在 tb_agent 表，包含 agent_name、system_prompt、model_id 等。
- tb_agent_relation 表记录 agent 绑定的 tools/skills/mcp（relation_flag: 1=API 2=KB 3=MCP 4=SKILL）
- tb_agent.pr_key_id 是主键

## mcp 管理
MCP 服务在 tb_mcp 表，包含 mcp_name、connection_type、exec_cmd 等。
- tb_mcp_intfc 表记录 MCP 的接口（工具）列表
- connection_type: stdio 或 HTTP

## skill 管理
Skill 在 tb_skill 表，包含 skill_name、skill_desc、module_path 等。
- tb_skill.pr_key_id 是主键
- skill 可以通过 module_path+function_name 实现或 lazy 加载

## 权限管理
用户权限通过角色管理：tb_user → tb_user_role → tb_role → tb_role_permission → tb_permission
- tb_permission 的 permission_code 格式: domain:resource_type:* (如 read:agent:*)
- domain: read/write/delete/manage
- resource_type: agent/mcp/tool/external_tool/skill/workspace/user/menu/rag

## 工作空间
工作空间在 tb_workspace 表，用于多租户隔离。
- tb_user_workspace 记录用户与空间的关联
- 工具链表（tb_agent/tb_mcp/tb_skill 等）有 workspace_id + is_public + creator_id 字段
