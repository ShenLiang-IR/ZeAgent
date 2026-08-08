# Tool Execution Approval (Human-in-the-Loop) — 设计规格

> **版本**: v1.0 | **日期**: 2026-08-07 | **状态**: Implemented

## 1. 动机

当前 Agent 执行过程中，LLM 可以自主调用任何已注册的 tool，包括破坏性操作（删除文件、发送邮件、执行 shell 命令、调用外部 API）。企业 AI 中台需要"执行中实时审批"能力：当 Agent 决定调用高危操作时，必须有人工确认才能执行。

## 2. 设计原则

- **不让 LLM 判断风险**：高危判定由管理员预定义的规则驱动，不依赖 LLM 推理
- **最小侵入**：复用现有 `ReviewRegistry` 暂停/唤醒机制，不改动 LangGraph/LangChain 核心
- **工具级别粒度**：按 tool_name 审批，不做参数级别模式匹配（Phase 1）
- **超时自动拒绝**：审批超时默认拒绝，安全优先

## 3. 核心概念

### 3.1 工具风险等级 (`risk_level`)

| 等级 | 含义 | 示例 tool |
|---|---|---|
| `read_only` | 纯读操作，无副作用 | `read_file`, `knowledge_base_search`, `memory.recall` |
| `write_safe` | 写入但可逆/低风险 | `write_file`(沙箱内), `memory.remember`, `csv-tool`(写) |
| `destructive` | 不可逆破坏性操作 | `sandbox.execute_command`, `delete_file`, `sql_template`(写) |
| `external` | 外部通信/资金/权限 | `http_request`(外部), `email_sender`, MCP tool |

### 3.2 Agent 审批策略 (`approval_policy`)

```json
{
  "enabled": true,
  "threshold": "destructive",
  "timeout_seconds": 600,
  "tools_override": {
    "http_request": "always",
    "memory.remember": "never"
  }
}
```

- `threshold`：默认放行所有 <= threshold 的 tool
- `tools_override`：特例覆盖（always=强制审批，never=强制放行）
- `timeout_seconds`：等待审批的最大秒数，超时自动拒绝

### 3.3 审批流程

```
LLM tool_call ──▶ ToolExecutionGuard.check(tool_name, args, agent_id)
                      │
                      ├─ resolve risk_level (from ToolRegistry)
                      ├─ resolve approval_policy (from Agent config)
                      ├─ evaluate: risk_level vs threshold + override
                      │
                      ├─ PASS → execute tool normally
                      │
                      └─ REQUIRE_APPROVAL
                            │
                            ├─ ReviewRegistry.pause(dispatch_id)
                            ├─ SSE notify frontend (event: tool_approval_required)
                            ├─ await review_result (timeout)
                            │
                            ├─ approve → execute tool → return result
                            ├─ reject  → return rejection error to LLM
                            └─ timeout → return timeout error to LLM
```

## 4. 数据模型

### 4.1 ToolMeta (扩展)

```python
# tools/registry.py
@dataclass
class ToolMeta:
    name: str
    risk_level: str = "read_only"       # NEW
    risk_description: str = ""          # NEW
    # ... existing fields
```

### 4.2 Agent Approval Policy (JSON 存储在 tb_agent 或 agent_config)

```python
# 新增 Pydantic model
class AgentApprovalPolicy(BaseModel):
    enabled: bool = False
    threshold: str = "destructive"  # read_only | write_safe | destructive | external | always
    timeout_seconds: int = 600
    tools_override: Dict[str, str] = {}  # tool_name → "always" | "never"
```

### 4.3 审批记录（复用 tb_audit_log）

每次审批决策记录到审计日志：
- `resource_type`: "tool_approval"
- `action`: "approve" | "reject" | "timeout"
- `resource_id`: dispatch_id
- `before_data`: {tool_name, args, risk_level, agent_id}
- `after_data`: {decision, reviewer_id, timestamp}

## 5. API 设计

### 5.1 提交审批结果

```
POST /api/admin/tool-approval/{dispatch_id}/review
Body: {"action": "approve" | "reject", "reason": "optional"}
Response: {"status": "ok", "dispatch_id": "...", "action": "..."}
```

### 5.2 查询待审批列表

```
GET /api/admin/tool-approval/pending
Response: {
  "list": [
    {
      "dispatch_id": "disp-xxx",
      "tool_name": "sandbox.execute_command",
      "tool_args": {"command": "rm -rf /tmp/*"},
      "risk_level": "destructive",
      "risk_description": "该操作会删除服务器文件",
      "agent_name": "运维助手",
      "session_id": "sess-xxx",
      "requested_at": "2026-08-07T10:00:00Z"
    }
  ]
}
```

## 6. 前端交互

### 6.1 审批中心新增 "Tool 审批" 标签页

- 显示等待审批的 tool 调用列表
- 每项卡片展示：Agent 名称、tool 名称、参数预览、风险说明
- 操作按钮：[通过] [拒绝]
- 支持 SSE 实时推送新审批通知

### 6.2 SSE 事件格式

```
event: tool_approval_required
data: {"dispatch_id": "disp-xxx", "tool_name": "...", "risk_level": "destructive", ...}
```

## 7. 实施路径

| Phase | 内容 | 预估工作量 |
|---|---|---|
| Phase 1 | Tool 风险分级 + ToolExecutionGuard + API + 基础前端 | 核心功能 |
| Phase 2 | SSE 推送 + 审批历史查询 + 批量审批 | 体验优化 |
| Phase 3 | 参数级别条件规则 + 审批升级链 + 会话信任 | 高级策略 |

## 8. 与现有审批系统的关系

| 系统 | 审批对象 | 触发时机 | 机制 |
|---|---|---|---|
| Agent 发布审批 | Agent 配置 | 提交发布前 | DB 状态机 |
| Plan 执行前审批 | 执行计划 | Plan 生成后、执行前 | ReviewRegistry |
| **Tool 执行审批** (NEW) | Tool 调用 | Tool 执行前 | ReviewRegistry |

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 审批人不在导致超时堆积 | timeout 后可配置较长值（如 1小时）；支持审批代理 |
| LLM 反复尝试被拒的 tool | ToolExecutionGuard 缓存最近拒绝决策，同类请求自动拒绝 |
| 频繁审批影响对话体验 | read_only/write_safe 默认放行；同一 session 内支持"信任本次会话" |
