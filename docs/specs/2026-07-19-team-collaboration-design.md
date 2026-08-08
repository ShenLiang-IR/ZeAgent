# 团队协作模式 + Agent 间通信 — 第一期设计

> 日期：2026-07-19
> 状态：⏸️ **SHELVED（搁置，暂不实施）** — 2026-07-19。优先实施触发器扩展方案（见 `docs/specs/2026-07-19-trigger-registry-design.md`）。本方案仅作设计参考，不动代码；待触发器方案落地后再评估是否解冻。
> 方案：复用现有 `tb_workspace` 多租户体系，新增"Agent 团队"实体 + "Agent 邮箱"消息机制
> 第一期 scope：项目空间内组建 Agent 团队 + 邮箱式异步消息（共享任务列表作为第二期备选）
> 上下文：承接 `docs/executoranalyse.md` 调度系统分析与 `docs/specs/2026-07-15-dynamic-replanning-design.md` 动态重规划能力

---

## 1. 背景

### 1.1 已具备的能力（梳理后修正）

上一轮分析中我误判"项目无项目空间实体"。本次梳理后确认，项目已具备以下基础：

| 能力 | 现状 | 位置 |
|---|---|---|
| 多租户工作空间 | ✅ `tb_workspace` + `tb_user_workspace` + `tb_user_group` | `infrastructure/database/models/workspace.py` |
| Agent 归属空间 | ✅ `tb_agent.workspace_id` + `is_public` 字段已存在 | `infrastructure/database/models/agent.py:26-27` |
| 多 Agent 编队调度 | ✅ parallel/sequential/dag 三模式 | `services/multi_agent_service.py::dispatch_stream` |
| 调度记录持久化 | ✅ `tb_dispatch_record` | `infrastructure/database/models/dispatch_record.py` |
| 上下文单向传递 | ✅ `WorkflowState.results` reducer | `executor/workflow/stategraph_builder.py` |
| 人工审核 pause | ✅ `ReviewRegistry.await_review` | `services/multi_agent_service.py:276-291` |
| Repository 模式 | ✅ `BaseRepository` 抽象基类 | `infrastructure/database/repositories/base_repository.py` |

### 1.2 仍然缺失的能力（本方案目标）

1. **"Agent 团队"实体**：当前 dispatch 是**临时拼队**（传入 `agent_ids` 列表），无持久化的"团队"概念；Agent 之间无"角色"（调研/分析/执行）元数据。
2. **Agent 间通信机制**：当前 `WorkflowState.results` 是**单向数据流**（上游→下游），不支持：
   - Agent 主动向另一个 Agent 发消息（任意时刻、任意方向）
   - Agent 向团队广播任务/请求
   - 跨 dispatch 的消息保留（多轮协作记忆）

### 1.3 与动态重规划的关系

`2026-07-15-dynamic-replanning-design.md` 已支持"plan 执行完 → 检查 condition/replan_on → LLM 重规划追加 task"。本方案与其正交：团队/邮箱是**配置层 + 通信层**，重规划是**执行层**，两者可叠加（团队成员可触发重规划）。

---

## 2. 目标（第一期）

- **G1 项目空间复用**：不新建"项目空间"表，直接复用 `tb_workspace`。一个 Workspace 下可创建多个 Agent 团队。
- **G2 Agent 团队 CRUD**：在 workspace 下创建/更新/删除团队，团队成员带角色（如 `researcher` / `analyst` / `executor`，角色字符串可自定义）。
- **G3 团队级 dispatch**：`MultiAgentService.dispatch_stream` 扩展 `team_id` 入参，自动展开为成员 agent_ids；与现有 `agent_ids` 入参**互斥向下兼容**。
- **G4 Agent 邮箱**：每个 agent 在 team 内有收件箱；提供 `send_message` / `poll_messages` / `ack_message` API；支持同步拉取（轮询）和异步通知（SSE 推送）。
- **G5 Agent 工具桥接**：暴露 `send_message_to_agent` / `read_my_messages` 内置工具，让 Agent 在 ReAct 循环中主动收发消息。
- **G6 向下兼容**：现有 `/api/admin/subagents` 路由、`MultiAgentService.dispatch_stream(agent_ids=...)` 调用零改动；新功能全部走新路由 / 可选参数。

## 3. 非目标

- 共享任务列表（Kanban 模式）→ 第二期备选（见 §11）
- 团队级共享记忆向量库 → 第二期
- 跨 workspace 的团队协作 → 不做（多租户隔离原则）
- Agent 自主加入/退出团队 → 不做（管理员驱动）
- 同步双向通信（RPC 风格）→ 不做（用邮箱 + 回信模拟，避免阻塞 LLM 调用）

---

## 4. 架构

```
┌──────────────────────────────────────────────────────────────┐
│ tb_workspace（已有，复用）                                       │
│   ┌─────────────────────────────────────────────┐            │
│   │ tb_agent_team（新增）                          │            │
│   │   name / goal / default_mode / workspace_id   │            │
│   │   ┌──────────────────────────────────────┐   │            │
│   │   │ tb_agent_team_member（新增）            │   │            │
│   │   │   team_id / agent_id / role / order   │   │            │
│   │   └──────────────────────────────────────┘   │            │
│   │   ┌──────────────────────────────────────┐   │            │
│   │   │ tb_agent_mailbox（新增）               │   │            │
│   │   │   team_id / from_agent / to_agent     │   │            │
│   │   │   / subject / body / status / ts      │   │            │
│   │   └──────────────────────────────────────┘   │            │
│   └─────────────────────────────────────────────┘            │
│   ┌─────────────────────────────────────────────┐            │
│   │ tb_agent（已有，workspace_id 字段已存在）       │            │
│   └─────────────────────────────────────────────┘            │
│   ┌─────────────────────────────────────────────┐            │
│   │ tb_dispatch_record（已有，加 team_id 列）        │            │
│   └─────────────────────────────────────────────┘            │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
        services/team_service.py（新增）
          ├── TeamCrudService（团队 + 成员 CRUD）
          └── MailboxService（send / poll / ack / broadcast）
                              │
                              ▼
        services/multi_agent_service.py（扩展）
          └── dispatch_stream(team_id=...) → 展开成员 → 现有调度
                              │
                              ▼
        executor/workflow/stategraph_builder.py（不改）
          └── 沿用 WorkflowState.results 单向数据流
                              │
                              ▼
        新增内置工具：send_message_to_agent / read_my_messages
          （注入到 team 成员 agent 的工具集）
```

**关键设计决策**：
- **不引入消息总线/发布订阅中间件**：邮箱用 MySQL 表 + 轮询实现，避免引入 Redis/RabbitMQ 依赖。
- **不在 LangGraph WorkflowState 里加"mailbox 通道"**：邮箱是**任务外的副作用**，不应污染图调度的纯函数性。Agent 通过工具调用收发消息，消息进/出 DB。
- **Agent 间消息不直接进入 prompt**：Agent 必须主动调用 `read_my_messages` 工具拉取，避免被动注入导致 prompt 失控。

---

## 5. 数据模型

### 5.1 新增表 1：`tb_agent_team`

```sql
-- 跨平台 DDL（MySQL 5.7+ / SQLite 3.x 兼容：用 SQLAlchemy 生成，不手写）
-- 模型定义见 infrastructure/database/models/agent_team.py

CREATE TABLE tb_agent_team (
    pr_key_id      BIGINT PRIMARY KEY AUTO_INCREMENT,
    team_id        VARCHAR(64)  NOT NULL UNIQUE COMMENT '业务ID，AGT_TEAM_前缀',
    team_name      VARCHAR(100) NOT NULL,
    team_description TEXT,
    workspace_id   BIGINT       NOT NULL COMMENT '所属 tb_workspace.workspace_id',
    goal           TEXT         COMMENT '团队共同目标，dispatch 时作为 original_query 兜底',
    default_mode   VARCHAR(20)  DEFAULT 'parallel' COMMENT 'parallel|sequential|dag',
    default_tasks  TEXT         COMMENT 'JSON：DAG 模式默认 task 依赖结构',
    status         VARCHAR(1)   DEFAULT '1' COMMENT '1=启用 0=禁用',
    del_flag       VARCHAR(1)   DEFAULT '0',
    creator_id     BIGINT       COMMENT '创建者 user_id',
    create_time    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    update_time    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_workspace (workspace_id),
    INDEX idx_team_id (team_id)
);
```

### 5.2 新增表 2：`tb_agent_team_member`

```sql
CREATE TABLE tb_agent_team_member (
    pr_key_id    BIGINT PRIMARY KEY AUTO_INCREMENT,
    team_id      VARCHAR(64) NOT NULL COMMENT '所属 tb_agent_team.team_id',
    agent_id     BIGINT      NOT NULL COMMENT 'tb_agent.pr_key_id',
    role         VARCHAR(50) NOT NULL COMMENT '角色：researcher|analyst|executor|自定义',
    role_order   INT         DEFAULT 0 COMMENT '同角色内顺序，用于 sequential 模式排序',
    del_flag      VARCHAR(1)  DEFAULT '0',
    create_time   TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
    update_time   TIMESTAMP   DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_team_agent (team_id, agent_id),
    INDEX idx_team (team_id)
);
```

### 5.3 新增表 3：`tb_agent_mailbox`

```sql
CREATE TABLE tb_agent_mailbox (
    pr_key_id   BIGINT PRIMARY KEY AUTO_INCREMENT,
    message_id  VARCHAR(64)  NOT NULL UNIQUE COMMENT '业务ID，AGT_MSG_前缀',
    team_id     VARCHAR(64)  NOT NULL COMMENT '团队作用域（跨 team 不通）',
    from_agent_id BIGINT     COMMENT '发送方 agent_id；NULL=system/user',
    to_agent_id BIGINT       NOT NULL COMMENT '接收方 agent_id；-1=团队广播',
    subject     VARCHAR(255),
    body        TEXT         NOT NULL,
    in_reply_to VARCHAR(64)  COMMENT '回复哪条 message_id（线程化）',
    status      VARCHAR(20) DEFAULT 'unread' COMMENT 'unread|read|ack|failed',
    dispatch_id VARCHAR(64) COMMENT '关联的 tb_dispatch_record.dispatch_id',
    create_time TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
    read_time   TIMESTAMP   NULL,
    INDEX idx_to_agent_status (to_agent_id, status),
    INDEX idx_team (team_id),
    INDEX idx_dispatch (dispatch_id)
);
```

### 5.4 改动表：`tb_dispatch_record`

新增 1 列（向后兼容，DDL 用 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`）：

```sql
ALTER TABLE tb_dispatch_record ADD COLUMN team_id VARCHAR(64) NULL COMMENT '团队 dispatch 时记录';
```

### 5.5 SQLAlchemy 模型文件

新增 `infrastructure/database/models/agent_team.py`，包含 `AgentTeam` / `AgentTeamMember` / `AgentMailbox` 三个类，均继承 `Base` + `TimestampMixinLegacy`（参照 `agent.py` 模式）。`tb_dispatch_record.py` 加 `team_id` 字段。

---

## 6. 服务层

### 6.1 新增 `services/team_service.py`

```python
# services/team_service.py
"""Agent 团队 + 邮箱服务层。复用 BaseRepository + WorkspaceRepository 风格。"""
from typing import Any, Dict, List, Optional
from loguru import logger
from utils.id_generator import generate_uuid  # 复用现有 ID 生成器


class TeamCrudService:
    """团队 + 成员 CRUD（在 workspace 作用域内）。"""

    def __init__(self):
        from infrastructure.database.repositories.agent_team_repository import (
            AgentTeamRepository, AgentTeamMemberRepository,
        )
        self._team_repo = AgentTeamRepository()
        self._member_repo = AgentTeamTeamMemberRepository()

    def create_team(self, workspace_id: int, team_name: str, goal: str = "",
                    default_mode: str = "parallel", creator_id: Optional[int] = None,
                    members: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """创建团队 + 可选初始成员。members: [{agent_id, role, role_order?}]"""
        team_id = f"AGT_TEAM_{generate_uuid()[:12]}"
        # ... 调用 _team_repo.create + 批量 _member_repo.create
        ...

    def get_team(self, team_id: str) -> Optional[Dict[str, Any]]:
        """团队详情 + 成员列表（含 agent_name/role）。"""
        ...

    def list_teams(self, workspace_id: int) -> List[Dict[str, Any]]:
        """列出 workspace 下的所有团队。"""
        ...

    def add_member(self, team_id: str, agent_id: int, role: str, role_order: int = 0) -> bool:
        """添加成员（不允许重复 team_id+agent_id）。"""
        ...

    def remove_member(self, team_id: str, agent_id: int) -> bool:
        """软删成员。"""
        ...

    def delete_team(self, team_id: str) -> bool:
        """软删团队 + 级联软删成员。"""
        ...

    def resolve_member_agent_ids(self, team_id: str, role: Optional[str] = None) -> List[int]:
        """展开团队为 agent_id 列表。role 过滤可选；按 role_order 升序。"""
        ...


class MailboxService:
    """Agent 邮箱服务。"""

    def __init__(self):
        from infrastructure.database.repositories.agent_team_repository import (
            AgentMailboxRepository,
        )
        self._mailbox_repo = AgentMailboxRepository()

    def send_message(self, team_id: str, from_agent_id: Optional[int], to_agent_id: int,
                     subject: str, body: str, in_reply_to: Optional[str] = None,
                     dispatch_id: Optional[str] = None) -> Dict[str, Any]:
        """投递消息。to_agent_id=-1 表示团队广播（fan-out 到所有成员）。"""
        ...

    def poll_messages(self, agent_id: int, team_id: Optional[str] = None,
                      status: str = "unread", limit: int = 50) -> List[Dict[str, Any]]:
        """Agent 主动拉取自己收件箱。"""
        ...

    def mark_read(self, message_id: str) -> bool:
        """标记已读。"""
        ...

    def ack_message(self, message_id: str, status: str = "ack") -> bool:
        """Agent 处理完毕，回执。status: ack|failed。"""
        ...

    def get_thread(self, root_message_id: str) -> List[Dict[str, Any]]:
        """线程化查询（沿 in_reply_to 链向上/向下）。"""
        ...
```

### 6.2 新增 `infrastructure/database/repositories/agent_team_repository.py`

参照 `workspace_repository.py` + `agent_relation_repository.py` 风格：
- `AgentTeamRepository(BaseRepository[AgentTeam, Dict])`：`_pk_name='pr_key_id'`，重写 `_entity_to_dict`
- `AgentTeamMemberRepository`：含 `get_members_by_team(team_id)` / `resolve_agent_ids(team_id, role=None)`
- `AgentMailboxRepository`：含 `get_inbox(agent_id, team_id=None, status='unread')` / `broadcast(team_id, from_agent_id, ...)`

### 6.3 扩展 `services/multi_agent_service.py`

在 `dispatch_stream` 增加 `team_id` 可选参数，**与 `agent_ids` 互斥**（任一必须有且仅有一个）：

```python
async def dispatch_stream(
    self,
    agent_ids: Optional[List[str]] = None,  # 改为可选
    message: str = "",
    mode: str = "parallel",
    tasks: Optional[List[Dict[str, Any]]] = None,
    team_id: Optional[str] = None,          # ← 新增
    team_role: Optional[str] = None,        # ← 新增：仅调度团队内某角色的成员
) -> AsyncGenerator[Dict[str, Any], None]:
    # 入参解析
    if team_id and agent_ids:
        yield {"type": "error", "data": "team_id 与 agent_ids 互斥"}
        return
    if team_id:
        from services.team_service import TeamCrudService
        svc = TeamCrudService()
        agent_ids_int = svc.resolve_member_agent_ids(team_id, role=team_role)
        if not agent_ids_int:
            yield {"type": "error", "data": f"团队 {team_id} 无有效成员"}
            return
        agent_ids = [str(i) for i in agent_ids_int]
        team_meta = svc.get_team(team_id)
        if team_meta and not message:
            message = team_meta.get("goal", "")  # 团队目标兜底
        if team_meta and mode == "parallel":
            mode = team_meta.get("default_mode", "parallel")
    elif not agent_ids:
        yield {"type": "error", "data": "必须传 team_id 或 agent_ids"}
        return
    # ... 现有调度逻辑不变，仅 DispatchRecord 写入时多写一列 team_id
```

**改动量**：约 15 行新代码 + 1 处 DispatchRecord 写入字段，对现有 `agent_ids` 调用零影响。

### 6.4 新增内置工具：`tools/agent_mailbox_tools.py`

```python
# tools/agent_mailbox_tools.py
"""Agent 邮箱工具：注入 team 成员 agent，让其在 ReAct 循环中收发消息。"""
from langchain_core.tools import tool
from services.team_service import MailboxService

@tool
def send_message_to_agent(to_agent_id: int, subject: str, body: str,
                          in_reply_to: str = None) -> str:
    """向团队内另一个 Agent 发消息。当前 agent_id 从执行上下文注入。"""
    # _current_agent_id / _current_team_id 由 LangGraphTaskExecutor 注入
    ...

@tool
def read_my_messages(status: str = "unread", limit: int = 10) -> str:
    """拉取自己收件箱。返回 JSON 字符串。"""
    ...

@tool
def broadcast_to_team(subject: str, body: str) -> str:
    """向团队所有成员广播消息（to_agent_id=-1）。"""
    ...
```

**工具注入策略**：在 `core/builder/tool_collector.py::collect_subagent_tools_async` 中，检测 agent 是否属于某个 team（查 `tb_agent_team_member`），若是则额外收集上述 3 个工具，并把当前 agent_id / team_id 写入 LangGraph `RunnableConfig` 的 `configurable` 字段，供工具函数读取。

---

## 7. API 路由改动点

### 7.1 新增路由文件：`api/admin/team.py`

参照 `api/admin/subagent.py` 风格，注册到 `admin_router`：

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/api/admin/teams` | `require_write("team")` | 在指定 workspace 下创建团队 |
| GET | `/api/admin/teams` | `require_read("team")` | 列出当前 workspace 的团队 |
| GET | `/api/admin/teams/{team_id}` | `require_read("team")` | 团队详情 + 成员 |
| PUT | `/api/admin/teams/{team_id}` | `require_write("team")` | 更新团队基本信息 |
| DELETE | `/api/admin/teams/{team_id}` | `require_delete("team")` | 软删团队 |
| POST | `/api/admin/teams/{team_id}/members` | `require_write("team")` | 添加成员（agent_id + role） |
| DELETE | `/api/admin/teams/{team_id}/members/{agent_id}` | `require_delete("team")` | 移除成员 |
| PATCH | `/api/admin/teams/{team_id}/members/{agent_id}` | `require_write("team")` | 调整角色 / role_order |
| POST | `/api/admin/teams/{team_id}/dispatch` | `require_write("team")` | 触发团队 dispatch（SSE 流式） |

### 7.2 新增路由文件：`api/admin/mailbox.py`

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/api/admin/teams/{team_id}/messages` | `require_write("mailbox")` | 系统侧/用户侧投递消息 |
| GET | `/api/admin/teams/{team_id}/agents/{agent_id}/messages` | `require_read("mailbox")` | 拉取某 agent 收件箱（管理观察用） |
| PATCH | `/api/admin/teams/{team_id}/messages/{message_id}` | `require_write("mailbox")` | 标记 read/ack |
| GET | `/api/admin/teams/{team_id}/messages/{message_id}/thread` | `require_read("mailbox")` | 线程化查询 |

### 7.3 路由注册：`api/admin/__init__.py` 改动

```python
# 新增 2 行
from .team import router as team_router
from .mailbox import router as mailbox_router

# 新增 2 行 include
admin_router.include_router(team_router)
admin_router.include_router(mailbox_router)
```

### 7.4 扩展 `api/chat/` 或 `api/plan/`：团队 dispatch SSE

`api/plan/review_routes.py` 已存在，可在其旁新增 `api/plan/dispatch_routes.py` 或直接在 chat 路由加 `team_id` 入参：

```python
# api/plan/dispatch_routes.py（新增）
@router.post("/teams/{team_id}/dispatch/stream")
async def team_dispatch_stream(team_id: str, message: str = "",
                                user_permissions: UserPermissions = Depends(require_write("team"))):
    svc = MultiAgentService()
    async def gen():
        async for ev in svc.dispatch_stream(team_id=team_id, message=message):
            yield build_sse(ev)
    return StreamingResponse(gen(), media_type="text/event-stream")
```

### 7.5 前端契约（`frontend/src/views/`）

新增 2 个页面（参照现有 `subagent` 页面风格）：
- `frontend/src/views/team/TeamList.vue` — 团队列表 + 创建表单
- `frontend/src/views/team/TeamDetail.vue` — 团队详情 + 成员管理 + 触发 dispatch 按钮
- 可选 `frontend/src/views/team/MailboxViewer.vue` — 观察某 agent 收件箱（调试用）

类型定义新增到 `frontend/src/types/team.ts`：
```typescript
export interface AgentTeam {
  team_id: string
  team_name: string
  workspace_id: number
  goal?: string
  default_mode: 'parallel' | 'sequential' | 'dag'
  members: TeamMember[]
}
export interface TeamMember {
  agent_id: number
  agent_name?: string
  role: string
  role_order: number
}
export interface AgentMessage {
  message_id: string
  team_id: string
  from_agent_id: number | null
  to_agent_id: number
  subject?: string
  body: string
  status: 'unread' | 'read' | 'ack' | 'failed'
  in_reply_to?: string
  create_time: string
  read_time?: string
}
```

---

## 8. 数据流

### 8.1 团队创建流

```
管理员前端 → POST /api/admin/teams {workspace_id, team_name, goal, members:[{agent_id, role}]}
   → TeamCrudService.create_team
       → 校验 workspace_id 存在（WorkspaceRepository.get_by_id）
       → 校验每个 agent_id 属于该 workspace（Agent.workspace_id 或 is_public=1）
       → AgentTeamRepository.create → 拿到 pr_key_id → 批量 AgentTeamMemberRepository.create
   → 返回 team 详情
```

### 8.2 团队 dispatch 流（关键）

```
前端 → POST /api/admin/teams/{team_id}/dispatch/stream {message}
   → MultiAgentService.dispatch_stream(team_id=..., message=...)
       ├── resolve_member_agent_ids(team_id) → [agt_a_id, agt_b_id, agt_c_id]
       ├── 取 team.default_mode → 决定 parallel/sequential/dag
       ├── 现有调度：build StateGraph → astream → SSE 事件流
       ├── DispatchRecord 持久化（写入 team_id 列）
       └── human_approval=true 时 → ReviewRegistry 注册 → 等 SSE approve/modify/reject

                  ┌─── 每个 task node 内部 ───────────────┐
                  │ collect_subagent_tools_async            │
                  │   └── 若 agent 是 team 成员 → 注入       │
                  │       send_message_to_agent /           │
                  │       read_my_messages /                │
                  │       broadcast_to_team 三个工具          │
                  │ LangGraphTaskExecutor.execute_task_stream│
                  │   └── agent ReAct 循环中可主动调工具收发消息│
                  └─────────────────────────────────────────┘
```

### 8.3 Agent 间通信流（邮箱）

```
Agent A（task_0 node 内，ReAct 第 N 步）
   → 调用 send_message_to_agent(to_agent_id=B, subject="需要数据", body="...")
   → MailboxService.send_message
   → 写入 tb_agent_mailbox (status='unread')
   → 返回 "已发送" 字符串给 Agent A 的 LLM

Agent B（task_1 node 内，可能在另一个 super-step 或并行 super-step）
   → 调用 read_my_messages(status='unread')
   → MailboxService.poll_messages
   → 查询 tb_agent_mailbox WHERE to_agent_id=B AND status='unread'
   → 返回 JSON: [{"message_id":..., "from_agent_id":A, "subject":..., "body":...}]
   → Agent B 的 LLM 看到消息，决定是否回复
   → 可选：调用 ack_message(message_id, status='ack') 标记处理完毕
```

**注意**：Agent 间消息**不会自动注入 prompt**，必须 Agent 主动 `read_my_messages`。这是有意为之——避免 LLM 被动收消息导致 prompt 膨胀，且让 Agent 保持 ReAct 主体性。

### 8.4 团队广播流

```
Agent A → broadcast_to_team(subject="任务进度", body="调研阶段完成")
   → MailboxService.send_message(to_agent_id=-1)
   → fan-out：查 tb_agent_team_member WHERE team_id → 为每个成员插入一行
   → 每个 agent 各自 read_my_messages 时拉到
```

---

## 9. 错误处理与兼容性

| 场景 | 处理 |
|---|---|
| `team_id` 与 `agent_ids` 同时传 | 返回 400 `team_id 与 agent_ids 互斥` |
| 团队无有效成员 | 返回 400 + 业务错误（不调度） |
| Agent 不属于该 workspace 且 `is_public=0` | 创建团队时拒绝 |
| 邮箱消息体超过 64KB | 截断 + 标记 `status='failed'`（参照 LangChain ToolMessage 限制） |
| `read_my_messages` 无消息 | 返回空数组字符串 `"[]"`，不让 LLM 重试 |
| `send_message_to_agent` 目标 agent 不在 team | 返回错误字符串，不写库 |
| 现有 `dispatch_stream(agent_ids=[...])` 调用 | 零影响（`team_id=None` 走原路径） |
| `tb_dispatch_record` 旧记录 `team_id` 列 | NULL，向后兼容 |
| 团队软删后调 dispatch | 返回 410 / 业务错误 |
| MySQL / SQLite 切换 | DDL 由 SQLAlchemy `create_all` 生成，不手写 SQL |
| Windows / macOS 路径差异 | 本方案不涉及文件 IO，无平台差异；建表脚本用 `python -c "from infrastructure.database.base import Base; Base.metadata.create_all(...)"`，两平台通用 |

---

## 10. 测试

### 10.1 单元测试（`test/test_team_service.py` 新建）

| 测试 | 验证 |
|---|---|
| `test_create_team_with_members` | 团队 + 成员正确入库 |
| `test_add_duplicate_member` | 唯一约束生效 |
| `test_resolve_member_agent_ids` | 团队 → agent_ids 展开 + role 过滤 |
| `test_resolve_member_order` | sequential 模式按 role_order 排序 |
| `test_delete_team_cascade` | 级联软删成员 |
| `test_mailbox_send_and_poll` | 发送→拉取一致 |
| `test_mailbox_broadcast` | 广播 fan-out 正确 |
| `test_mailbox_ack` | 状态流转 unread→read→ack |
| `test_mailbox_thread` | in_reply_to 链查询 |
| `test_dispatch_team_no_members` | 错误返回，不调度 |

### 10.2 集成测试（`test/test_team_dispatch_e2e.py` 新建）

| 测试 | 验证 |
|---|---|
| `test_team_dispatch_parallel` | 团队并行 dispatch，SSE 事件齐全 |
| `test_team_dispatch_sequential` | 顺序模式，按 role_order 调度 |
| `test_team_dispatch_human_approval` | 触发 plan_review 事件 |
| `test_team_dispatch_with_mailbox` | 两 agent 通过邮箱协作 |
| `test_dispatch_agent_ids_backward_compat` | 旧 `agent_ids=[...]` 调用仍工作 |

### 10.3 验证命令

```bash
# 跨平台通用（Windows/macOS）
python -m pytest test/test_team_service.py -v
python -m pytest test/test_team_dispatch_e2e.py -v

# 建表（首次）
python -c "from infrastructure.database.base import Base; from infrastructure.database.engines import get_config_engine; import infrastructure.database.models.agent_team; Base.metadata.create_all(get_config_engine(), checkfirst=True)"
```

---

## 11. 分阶段

| 阶段 | 内容 | 依赖 |
|---|---|---|
| 1 | 数据模型：`agent_team.py` + `agent_team_repository.py` + `dispatch_record.py` 加列 | 无 |
| 2 | 服务层：`TeamCrudService` + `MailboxService` | 阶段 1 |
| 3 | API 路由：`api/admin/team.py` + `api/admin/mailbox.py` + 注册 | 阶段 2 |
| 4 | 工具注入：`tools/agent_mailbox_tools.py` + `tool_collector.py` 扩展 | 阶段 2 |
| 5 | dispatch 集成：`MultiAgentService.dispatch_stream(team_id=...)` | 阶段 1-2 |
| 6 | 前端：3 个 Vue 页面 + 类型定义 | 阶段 3 |
| 7 | 测试：单元 + 集成 | 阶段 1-5 |

---

## 12. 文件变更

### 新增（11 个）

| 文件 | 类型 |
|---|---|
| `infrastructure/database/models/agent_team.py` | 新建 |
| `infrastructure/database/repositories/agent_team_repository.py` | 新建 |
| `services/team_service.py` | 新建 |
| `tools/agent_mailbox_tools.py` | 新建 |
| `api/admin/team.py` | 新建 |
| `api/admin/mailbox.py` | 新建 |
| `frontend/src/views/team/TeamList.vue` | 新建 |
| `frontend/src/views/team/TeamDetail.vue` | 新建 |
| `frontend/src/views/team/MailboxViewer.vue` | 新建 |
| `frontend/src/types/team.ts` | 新建 |
| `test/test_team_service.py` + `test/test_team_dispatch_e2e.py` | 新建 |

### 修改（5 个）

| 文件 | 改动 |
|---|---|
| `infrastructure/database/models/dispatch_record.py` | 加 `team_id` 字段 |
| `services/multi_agent_service.py` | `dispatch_stream` 加 `team_id` / `team_role` 可选参数 + DispatchRecord 写入列 |
| `core/builder/tool_collector.py` | `collect_subagent_tools_async` 检测 team 成员，注入 mailbox 工具 |
| `api/admin/__init__.py` | 注册 team_router + mailbox_router |
| `frontend/src/router/index.ts`（或等价） | 注册 3 个新页面路由 |

---

## 13. 后续期

| 期 | 内容 |
|---|---|
| 第二期 | 共享任务列表（Kanban 模式）：`tb_team_task` 表 + `claim_task` / `complete_task` 工具，Agent 可主动认领任务 |
| 第二期 | 团队级共享记忆：`tb_team_memory` + 向量库索引，跨 dispatch 保留协作上下文 |
| 第三期 | Agent 自主加入/退出团队（LLM 驱动 + 人工审批） |
| 第三期 | 消息实时推送（SSE/WebSocket）替代轮询 |

---

## 14. 风险

- **轮询性能**：邮箱用轮询，每个 ReAct 步骤可能触发 `read_my_messages`。缓解：默认 `limit=10`、`status='unread'`，且工具结果进 prompt 前经 `ContextEditingMiddleware` 压缩。
- **死信/无限重试**：Agent 反复 `send_message` 但对端无 `read_my_messages`。缓解：消息 `status='failed'` 在超过 N 次 ack 未回时标记（第二期）。
- **跨 dispatch 状态污染**：邮箱消息长期保留，新 dispatch 时旧消息仍可读。缓解：每次 dispatch 启动时可选 `clear_unread=true`，或基于 `dispatch_id` 过滤（已加索引）。
- **并发写消息竞态**：多 agent 并行 `send_message_to_agent` 写同一收件人。缓解：`tb_agent_mailbox` INSERT 无并发冲突（仅 append）；`mark_read` 用行级锁。
- **向下兼容性**：`tb_dispatch_record.team_id` 新列对旧记录为 NULL，旧代码读取无感知；`dispatch_stream` 旧调用走原路径。
- **工具注入性能**：`collect_subagent_tools_async` 多一次 `tb_agent_team_member` 查询。缓解：team 信息按 agent_id 缓存（LRU），TTL 60s。

---

## 15. 关键设计决策（需用户确认）

> 以下 4 个决策项我已给出**默认推荐**，如有不同偏好请在评审时指出：

1. **通信机制**：本方案选**邮箱**（异步、解耦、可线程化），不选共享任务列表（第二期备选）。**理由**：邮箱语义更通用（一对一 + 广播 + 回复链），更贴近"Agent 间消息传递"原意；共享任务列表更偏"工作流编排"，与现有 DAG dispatch 重叠。

2. **团队角色字段**：`role` 用**自由字符串**（推荐 `researcher`/`analyst`/`executor` 作约定值），不强制枚举。**理由**：不同业务团队角色命名不同，硬编码枚举会限制场景；约定值在 prompt 中作为示例引导。

3. **消息注入策略**：**不自动注入** Agent 收件箱到 prompt，必须 Agent 主动 `read_my_messages`。**理由**：避免被动注入导致 prompt 失控膨胀，保持 ReAct 主体性；与 LangChain ToolMessage 的"工具结果显式可见"哲学一致。

4. **工具注入位置**：在 `collect_subagent_tools_async` 里**按需注入**（agent 是 team 成员才注入），不全局注入。**理由**：全局注入会让非 team agent 也能调用，破坏作用域；按需注入确保工具仅对 team 成员可见。
