# install_deb_refactor（Agent API Server）

基于 LangChain 1.x / LangGraph 1.x 的企业级多智能体（Multi-Agent）服务平台：**FastAPI 后端 + Vue 3 管理后台**。支持多租户工作空间、Agent 配置/审批/版本发布、多执行器调度（ReAct / DeepAgent / LLM 自主规划 / 远程 A2A）、工具体系（内置工具 / Skill / MCP / 外部 HTTP 工具）、三层记忆、RAG 知识库、触发器编排、全链路监控与审计。

- 服务入口：`server.py`（FastAPI，端口 **8072**，版本 v0.8.0）
- 前端管理后台：`frontend/`（Vue 3 + Element Plus，开发端口 **3000**）
- 仓库地址：https://github.com/ShenLiang-IR/install_deb_refactor

## 技术栈

| 分层 | 技术 |
|---|---|
| 后端 | Python 3.13 · FastAPI 0.139 · SQLAlchemy 2.x · Pydantic v2 · LangChain 1.x / LangGraph 1.x · deepagents · APScheduler · loguru |
| 前端 | Vue 3 · Element Plus · Vite 5 · Vitest · ECharts · Mermaid · vue-router |
| 数据存储 | MySQL 8.0（业务主库）· Redis（限流/事件，可选）· ChromaDB（RAG 向量库，可选）· MinIO / 本地文件存储 |
| 可观测 | prometheus-fastapi-instrumentator（`/metrics`）· Prometheus · Grafana · Langfuse（可选） |
| 环境管理 | conda（依赖声明为 pip 格式 `requirements.txt`） |

## 项目结构

```
install_deb_refactor/
├── server.py                  # FastAPI 服务入口（端口 8072，lifespan 加载触发器/心跳/配置热重载）
├── api/                       # 路由层
│   ├── admin/                 #   管理端 REST API（agent/skill/mcp/trigger/audit/权限/配额...）
│   ├── chat/                  #   对话与会话（SSE 流式、执行事件、命令处理）
│   ├── auth/                  #   登录认证 + RBAC 管理端点
│   ├── plan/                  #   计划评审（人工审批节点）
│   ├── rag/                   #   RAG 知识库端点
│   ├── middleware/            #   请求追踪 / 限流 / 审计中间件
│   └── ws_approvals.py        #   WebSocket 审批通道（/ws/approvals，Redis 跨 worker 广播）
├── services/                  # 业务服务（agent_crud/agent_version/multi_agent/auth/quota/usage/eval...）
│   └── trigger/               #   触发器（registry + cron/webhook/file_watch + leader 选举 + 记忆定时任务）
├── core/                      # 核心构建层（builder: agent_factory/tool_collector/subagent · security: 内容过滤 · subagent）
├── executor/                  # 执行器
│   ├── react/deep_agent/plan/sql_template 执行器 + factory
│   ├── langgraph/             #   LangGraph 任务执行/事件解析/工具健康跟踪
│   └── workflow/              #   统一调度（stategraph_builder/runner/replan/remote_a2a_adapter）
├── delegation/                # Agent 间委派（delegate_agent，深度控制防递归）
├── meta_agent/                # 元代理（由 LLM 动态创建工具/MCP/Skill/Agent）
├── domain/                    # 领域层（skill/knowledge/session/message 的实体与仓储契约）
├── infrastructure/            # 基础设施
│   ├── database/              #   models（tb_* 表）/ repositories / sessions / 迁移
│   ├── sandbox/               #   沙箱（provider 抽象 + 本地沙箱回退）
│   ├── storage/               #   文件存储（minio/local/http provider）
│   └── reranking/persistence/ #   重排序 / 持久化
├── memory/                    # 记忆系统（瞬时/短期/长期 + 向量/混合检索 + 衰减/合并/冲突解决）
├── rag/rag_system/            # RAG（chunker/hybrid_retriever/reranker/query_rewriter/qdrant_store...）
├── tools/                     # 工具层（registry / mcp_client 进程池 / external_tool / http_request / text2sql...）
├── skills/                    # 磁盘 Skill 实现（db-query/csv-tool/code-runner/pdf-extractor/excel-tool 等 24 个）
├── skill_registry/            # Skill 运行时环境（venv/node_envs/go 二进制隔离，运行时生成）
├── db_skills/text2sql/        # 数据库类 Skill（text2sql 工厂 + 连接管理）
├── compression/               # 上下文压缩（ACON 框架适配）
├── config/                    # 运行时配置（agent_config.json / subagents/ / tools/，支持热重载）
├── command/                   # 现行迁移与 seed 脚本（workspace 字段/通配权限/版本回填/模板/加密工具）
├── scripts/
│   ├── migration/             #   历史一次性迁移（trigger schema/tool visibility/plugin resource id...）
│   └── tools/                 #   MCP 测试服务器、流程图生成等辅助工具
├── utils/                     # 工具类（config 加载与热重载 / crypto / llm / RBAC / SSE / observability...）
├── test/                      # pytest 后端测试（168 个测试文件、1000+ 用例；pytest.ini 位于本目录）
├── frontend/                  # Vue 3 管理后台（src/{views,components,api,layouts,router}）
├── docker/                    # Dockerfile.backend / Dockerfile.frontend + docker-compose 编排
├── prometheus/                # Prometheus 配置（prometheus.yml + alerts.yml）
├── grafana/                   # Grafana provisioning（数据源自动配置）
├── alembic/ + alembic.ini     # Alembic 数据库迁移
├── docs/                      # 设计文档与规格说明（docs/specs/ 为各专题设计稿）
├── data/ · logs/              # 运行数据与日志（gitignore）
├── bge-small-zh-v1___5/       # 本地中文 embedding 模型目录（大文件，gitignore）
├── .github/                   # CI 工作流 + dependabot
├── start_server.bat / .sh     # 后端启动脚本（自动激活 conda 环境 install_deb_refactor）
├── start_vite.bat             # 前端开发服务器启动脚本（Windows）
└── requirements.txt / requirements.rag.txt   # 核心依赖 / RAG 可选依赖（含 torch CPU，约 5GB）
```

## 核心流程

### 对话与任务调度

```
前端 ChatView ──POST /api/chat（SSE）──▶ chat_routes
  ──▶ MultiAgentService.dispatch_stream
        ├─ 单 Agent：executor/factory 按 agent.backend 选择执行器
        │    （langgraph=ReAct / deepagents / planning=PlanExecutor 自主规划）
        └─ 多 Agent：StateGraphBuilder 编排（parallel / sequential / dag / langgraph 四种模式）
  ──▶ 工具层注入：tool_registry 内置工具 + skills/ 磁盘技能 + MCP（进程池）+ 外部 HTTP 工具
  ──▶ SSE 流式回传：content 分片、execution_event（执行时间线）、metadata["is_final"] 标记最终结果
```

- Agent 间可经 `delegation` 委派子任务（config `agent.execution.delegation`，默认关，嵌套深度受限）；
- 上游结果经 `TaskResultEnvelope` 传递，下游可经 `get_upstream_result` 工具无损读取完整结果；
- 实验性远程 A2A：`executor/workflow/remote_a2a_adapter`（a2a-sdk 优先，httpx JSON-RPC 回退）。

### Agent 审批与版本发布（主线闭环）

设计文档：`docs/agent-approval-version-design.md`

- **编辑即失效**：编辑已发布/待审批的 Agent 一旦有改动 → 自动回退草稿 + 作废 pending 版本
- **提交审批**：冻结工作副本为 `pending_review` 版本快照（skills/mcp/visibility/agent_config 全字段）
- **审批 = 发布**：通过 → 版本 `published` 并归档旧版；拒绝 → 回草稿。**无独立 publish API**，发布统一经审批流
- **线上管控**：对话/调度/委派读取"已发布版本快照"（`get_effective_agent`），编辑不即时影响线上

### 触发器

- `TriggerRegistry`（单例）在服务 lifespan 启动时从 `tb_trigger` 加载并注册 enabled 触发器
- 类型：cron（APScheduler，jobstore 持久化）/ webhook / 文件监听 / lifespan 内置任务（记忆衰减、偏好摘要、记忆合并）
- 多 worker 部署可开 `agent.execution.trigger_leader_election`：DB 租约 leader 选举，webhook/file_watch 仅 leader 副本执行，primary 下线自动切换

## 快速开始

### 后端

```bash
# 1. 创建并激活 conda 环境（Python 3.13）
conda create -n install_deb_refactor python=3.13 -y
conda activate install_deb_refactor

# 2. 安装依赖
pip install -r requirements.txt
# RAG 功能可选（含 torch CPU 版，约 5GB）
# pip install -r requirements.rag.txt

# 3. 配置：仓库已随附 config/agent_config.json（可能含占位值），
#    按需修改其中的 API 密钥与数据库连接；若缺失可从模板复制：
copy config\agent_config.json.example config\agent_config.json    # Windows
cp config/agent_config.json.example config/agent_config.json      # Linux/macOS
# 如需环境变量管理密钥，复制 .env.example 为 .env 并填写

# 4. 数据库迁移（MySQL 8.0 需先就绪，连接配置在 agent_config.json 的 database 段）
python command/migrate_agent_workspace_config.py        # 多租户 workspace 字段
python command/migrate_admin_wildcard_permissions.py    # admin 通配权限
python command/migrate_agent_published_versions.py      # 存量已发布 agent 回填版本快照
python command/migrate_security.py                      # 安全相关字段
alembic upgrade head                                    # Alembic 迁移链

# 5. 启动
python server.py
# 或使用启动脚本（自动激活 conda 环境，启动前校验 agent_config.json）：
start_server.bat       # Windows
./start_server.sh      # Linux/macOS
```

启动后：

| 地址 | 说明 |
|---|---|
| http://localhost:8072 | API 根路径（版本/状态） |
| http://localhost:8072/docs | Swagger 文档（另有 /redoc） |
| http://localhost:8072/health | 深度健康检查（DB + Redis 连通性，供探针/负载均衡用） |
| http://localhost:8072/metrics | Prometheus 指标抓取端点 |
| ws://localhost:8072/ws/approvals | 审批 WebSocket 通道 |

### 前端

```bash
cd frontend
npm install
npm run dev               # http://localhost:3000（Vite 代理 /api → http://localhost:8072）
# Windows 也可直接在仓库根执行 start_vite.bat
```

管理后台页面覆盖：对话（ChatView）、Agent 列表/审批、团队、技能、MCP、外部工具、触发器、Prompt 模板、知识库（RAG/Text2SQL）、记忆、事件订阅、审计日志、用量统计、评测、插件市场、用户与工作空间管理、系统配置等。

## API 概览

所有路由在 `server.py` 注册；统一响应格式 `{code, message, data}`，统一异常处理（422/429/500 均返回该格式）。

| 前缀 | 说明 |
|---|---|
| `/api/admin/*` | 管理端（agents/agent_version/teams/skills/mcp/apis(外部工具)/triggers/prompts/memory/audit/usage/quota/observability/eval/security 等，写操作自动审计） |
| `/api/chat/*` | 对话与会话（SSE 流式、会话管理、命令处理） |
| `/api/auth/*` | 登录认证（provider 可插拔：invres/standalone JWT/apikey/OAuth2/自定义类） |
| `/api/plan/*` | 执行计划评审（人工审批节点） |
| `/api/rag/*` | RAG 知识库管理 |
| `/api/text2sql/*` | Text2SQL |
| `/api/models`、`/api/dict` | 模型资源管理、数据字典 |

## 测试

```bash
# 后端：pytest.ini 位于 test/ 目录，必须显式 -c 指定
pytest test/ -c test/pytest.ini -v
# 当前规模：168 个测试文件、1000+ 用例，连接真实 MySQL
# 集成测试（需外部环境：MCP/LLM/HTTP server）默认 skip，显式启用：
pytest test/ -c test/pytest.ini --runintegration

# 前端
cd frontend && npm test          # vitest run（14 个测试文件 / 87 用例）
```

注意事项：

- CI 中忽略 `test/test_skills.py`（依赖本地 Skill 运行时）；
- 多个路由测试通过 `app.dependency_overrides` 绕过鉴权；给测试文件新增 override 时，使用 autouse fixture 注册（防止被其他文件 teardown 的 `overrides.clear()` 抹掉）。

## 核心特性

### 权限系统（DB 驱动 RBAC）

- 权限从 `tb_role_permission` 表加载；权限码格式 `domain:resource_type:resource_id`，支持 `*` 通配
- **admin 始终超管**：代码层强制合并 5 个域通配权限（read/write/delete/execute/manage `:*:*`）
- 端点双层鉴权：router 级 `verify_token` + 端点级 `require_read/write/delete/manage("资源")`
- 工具对象三层可见性：private / workspace / public（`can_read_object` / `can_modify_object` 校验）

### 多租户工作空间隔离

- `tb_workspace` 顶层租户，`tb_user_workspace` 多对多关联
- Agent 三层可见性：`private` / `workspace` / `public`（public 穿透隔离）
- 普通用户按 token 中 `workspace_id` 过滤资源；admin 可跨空间

### 工具体系

- **内置工具**：`tools/registry.py` 代码注册（memory/knowledge_base/sql_template/http_request/sandbox 等）
- **Skill**：`skills/` 磁盘目录（SKILL.md 描述）+ 数据库技能（`agent.use_skill_backend` 走 DeepAgents Skills 路径），`skill_registry/` 提供 venv/node/go 运行时隔离
- **MCP**：`tools/data_providers/mcp_client`（进程池复用 + stdio/http 双协议）
- **外部工具**：HTTP 调用配置化（`tools/external_tool`），支持 `http_config_name` 集中管理多环境基址
- **元代理**：`meta_agent/` 允许 LLM 在对话中动态创建工具/MCP/Skill/Agent

### 记忆系统

三层记忆（瞬时 LRU / 短期带 TTL / 长期），`memory/memory_manager` 统一入口：向量召回（本地 bge-small-zh / DashScope embedding）+ BM25 混合检索 + 写前 LLM 冲突检测 + 定时衰减/合并/偏好摘要（lifespan 触发器）。配置见 `agent_config.json` 的 `memory` 段。

### RAG（可选依赖）

`rag/rag_system/`：文档解析（含 MinerU / 内网异步解析）→ chunker → ChromaDB/Qdrant 向量库 → 混合检索 + reranker + query 重写；配套结构化/非结构化知识库与 Text2SQL。未安装 `requirements.rag.txt`（torch）时优雅降级。

### 监控与安全

- `/metrics`（prometheus-fastapi-instrumentator）+ `prometheus/alerts.yml` 告警规则 + Grafana provisioning
- 统一错误响应格式、API 限流（slowapi：有 `REDIS_URL` 用 Redis 共享计数，否则 in-memory）
- 请求追踪（`X-Request-ID` + loguru contextvar）、审计日志（`/api/admin/*` 写操作自动拦截，before/after_data 快照）
- 密钥加密：`agent_config.json` 支持 `enc:` 密文字段（`JASYPT_MASTER_KEY` 主密钥，`python command/encrypt_secret.py encrypt "明文"` 生成）
- 内容安全过滤：`core/security/content_filter`（敏感词 `tb_sensitive_word`）

## 配置说明

### agent_config.json

- `${VAR:default}` 语法：加载时解析环境变量（未设置则用冒号后的默认值）
- `enc:` 前缀：运行时按 `JASYPT_MASTER_KEY` 自动解密（明文无 `enc:` 前缀向下兼容）
- 主要段落：`llm`（默认模型/providers）、`database`（config_db/chat_db，也可改用独立的 `config/db_config.json`，后者优先级更高，详见 `config/README.md`）、`auth`（provider/jwt/权限开关/默认 token）、`agent`（backend 引擎/auto_plan/skills_dir/sandbox）、`agent.execution`（委派/限流/leader 选举/远程 A2A）、`memory`、`compression`（ACON）、`storage`（minio/local/http）、`context`（历史截断/压缩）
- 支持热重载：`config/` 下配置文件被修改后自动 reload（`utils/config/config_watcher`），无需重启

### 环境变量（.env）

复制 `.env.example` 为 `.env`。docker-compose 经 `env_file: .env` 注入；常用项：`JASYPT_MASTER_KEY`、`JWT_SECRET`、`CORS_ORIGINS`、`REDIS_URL`、`DASHSCOPE_API_KEY`、`MINIO_SECRET_KEY`、`MINERU_API_KEY`、`LOG_DIR` 等。

> 注意：Python 侧未集成 dotenv——本地直接 `python server.py` 不会自动读 `.env`，需 shell 导出变量；`.env` 的自动生效路径是 Docker 部署。

### 无登录模式

`auth.enable_permission_check=false` 时按标准 JWT 解析且 roles 强制为 `["admin"]`（仅限开发/测试环境使用）。

## 脚本与数据库迁移

| 目录 | 说明 |
|---|---|
| `command/` | 现行迁移/seed：workspace 字段、admin 通配权限、已发布版本回填、安全字段、prompt 模板 seed、`encrypt_secret.py` 加密工具 |
| `scripts/migration/` | 历史一次性迁移（trigger schema、tool visibility、plugin resource id 等），幂等，含 sys.path 自举可直接执行 |
| `scripts/tools/` | MCP stdio 测试服务器（集成测试用）、流程图生成等 |
| `alembic/` | `alembic upgrade head` / `alembic revision --autogenerate -m "msg"`（DB URL 与运行时配置同源） |

核心业务表约 50 张（`tb_*`）：agent 与版本（`tb_agent`/`tb_agent_version`/`tb_agent_relation`/`tb_agent_team`）、认证授权（`tb_user`/`tb_role`/`tb_role_permission`/`tb_user_workspace`）、对话（`tb_chat_session`/`tb_chat_message`/`tb_dispatch_record`）、工具（`tb_skill`/`tb_mcp`/`tb_plugin`）、知识库（`tb_knowledge_base*`/`tb_rag_knowledge_base`/`tb_doc_management`）、治理（`tb_trigger*`/`tb_audit_log`/`tb_usage_record`/`tb_quota`/`tb_eval_*`）等。

## Docker 部署

Docker 文件集中在 `docker/` 目录；`.dockerignore` 保留在项目根（Docker 只从构建上下文根读取）。

```bash
# 在项目根目录执行；--project-directory 指回项目根，
# 保证 compose 内 ./config、.env 等相对路径按项目根解析
docker compose --project-directory . -f docker/docker-compose.yml up -d
```

编排的服务：

| 服务 | 端口 | 说明 |
|---|---|---|
| backend | 8072 | uvicorn 4 worker（生产限流需配 `REDIS_URL`，compose 已内置指向 redis 服务） |
| frontend | 3000 | nginx 静态托管 + `/api` 反代 backend |
| mysql | - | MySQL 8.0（业务数据 + APScheduler jobstore + 审计日志） |
| redis | - | Redis 7（限流共享计数 + WS 跨 worker 广播） |
| prometheus | 9090 | 每 15s 抓取 backend `/metrics`，保留 30 天 |
| grafana | 3001 | provisioning 自动接 Prometheus 数据源 |

compose 必需环境变量：`MYSQL_ROOT_PASSWORD`、`MYSQL_PASSWORD`、`GRAFANA_ADMIN_PASSWORD`（建议写进 `.env`）。

```bash
# RAG 镜像（含 torch CPU，镜像体积 +约 5GB）
docker build --build-arg INSTALL_RAG=true -f docker/Dockerfile.backend -t agent-backend:rag .

# Langfuse 自托管可观测性栈（可选，独立编排）
docker compose -f docker/docker-compose.langfuse.yml up -d
```

## CI/CD

- **GitHub Actions**（`.github/workflows/ci.yml`，push 到 main/develop 与 PR 触发）：
  - `backend-test`：真实 MySQL 8.0 service → 迁移 → pytest（忽略 test_skills.py）
  - `security-scan`：pip-audit 扫描 requirements.txt CVE（告警不阻塞）
  - `frontend-test`：Node 20 → vitest → vite build
  - `docker-build`：两个 Dockerfile 的镜像构建验证
- **dependabot**（`.github/dependabot.yml`）：pip / npm / docker 镜像 / GitHub Actions 周更检测
- **pre-commit**（`.pre-commit-config.yaml`）：ruff lint + format、大文件/合并冲突标记检查、mypy、main 分支保护


## 相关文档

- 设计文档目录：`docs/`（`agent-approval-version-design.md`、`flow.md`、`executoranalyse.md` 等；`docs/specs/` 收录触发器注册、监控、限流、审计、容器化、团队协作、用量统计等专题设计稿）
- 配置目录说明：`config/README.md`（db_config/http_config/subagents/外部工具配置）
- API 文档：http://localhost:8072/docs
