# 审计日志设计 — 用户操作审计（P0）

> 日期：2026-07-19
> 状态：📝 DESIGN（待评审）
> 上下文：承接 `docs/specs/2026-07-19-trigger-registry-design.md` 触发器扩展完成后的企业级短板补齐

## 1. 背景

当前 `tb_dispatch_record` 只记录 Agent 调度，**无用户操作审计**——谁改了 Agent 配置、谁启用了触发器、谁删了 Skill 完全无追溯。这是企业级合规底线，与 Langfuse trace（请求链路）正交互补。

## 2. 目标

- **G1**：所有 admin 写操作（POST/PUT/DELETE/PATCH）自动记录审计日志，业务代码零侵入
- **G2**：记录 before/after 数据快照，可回放
- **G3**：按 user/resource_type/action/time 维度查询
- **G4**：保留期策略（90 天热 + 1 年冷归档，第二期）
- **G5**：性能影响 < 5ms P99（异步写不阻塞主流程）

## 3. 数据模型

### 新增表 `tb_audit_log`

```sql
CREATE TABLE tb_audit_log (
    pr_key_id     BIGINT PRIMARY KEY AUTO_INCREMENT,
    audit_id      VARCHAR(64)  NOT NULL UNIQUE COMMENT 'AUDIT_ 前缀',
    user_id       VARCHAR(64)  NOT NULL COMMENT '操作者',
    username      VARCHAR(100) COMMENT '冗余用户名便于查询',
    workspace_id  BIGINT       COMMENT '操作所在空间',
    http_method   VARCHAR(10) COMMENT 'POST/PUT/DELETE/PATCH',
    path          VARCHAR(255) COMMENT '请求路径',
    resource_type VARCHAR(50)  COMMENT 'agent/trigger/skill/mcp/...',
    resource_id   VARCHAR(128) COMMENT '操作对象 ID',
    action        VARCHAR(20)  COMMENT 'create/update/delete/enable/disable',
    before_data   TEXT         COMMENT 'JSON：操作前快照',
    after_data    TEXT         COMMENT 'JSON：操作后快照',
    client_ip     VARCHAR(64),
    user_agent    VARCHAR(255),
    status_code   INT          COMMENT '响应状态码',
    duration_ms   INT,
    error         TEXT,
    create_time   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_time (user_id, create_time),
    INDEX idx_resource (resource_type, resource_id),
    INDEX idx_workspace_time (workspace_id, create_time)
);
```

## 4. 服务层 + 中间件

### `infrastructure/database/models/audit.py`（新建）

参照 `dispatch_record.py` 风格，含 `AuditLog` ORM + `TimestampMixinLegacy`。

### `infrastructure/database/repositories/audit_repository.py`（新建）

参照 `trigger_repository.py`，含 `create()` / `list_by_user()` / `list_by_resource()` / `list_by_workspace()`。

### `api/middleware/audit_middleware.py`（新建）

FastAPI middleware 拦截所有 `/api/admin/*` 写操作：

```python
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    if request.method not in ("POST", "PUT", "DELETE", "PATCH") or \
       not request.url.path.startswith("/api/admin"):
        return await call_next(request)
    # 1. 解析 user_id（从 verify_token 注入的 user_permissions）
    # 2. 解析 resource_type/resource_id（从 path 参数推断）
    # 3. before_data：GET 旧记录（PUT/DELETE 时）
    # 4. 执行请求 → 拿到 response.status_code + after_data
    # 5. 异步写 tb_audit_log（asyncio.create_task，不阻塞响应）
```

**resource_type 推断**：path 模板 `/{resource_type}s/{id}` → `agents` → `agent`，`triggers` → `trigger`。

**before/after 拿取策略**：
- before：在 middleware 里调对应 repository.get_by_id 拿旧记录
- after：从 response.body 读（FastAPI middleware 可以读 response body，但要小心流式响应）

**性能**：用 `asyncio.create_task` 异步写，不阻塞响应；before 查询走现有 repository 缓存。

## 5. API 路由

新增 `api/admin/audit.py`：

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/api/admin/audit/logs` | `require_read("audit")` + adminOnly | 列表查询（支持 user/resource/workspace/time 过滤） |
| GET | `/api/admin/audit/logs/{audit_id}` | `require_read("audit")` + adminOnly | 详情（含 before/after diff） |

## 6. 测试

| 测试 | 验证 |
|---|---|
| `test_audit_log_write_after_post` | POST /admin/triggers 后 tb_audit_log 有 create 记录 |
| `test_audit_log_before_after_captured` | PUT /admin/agents/{id} 后 before/after 数据完整 |
| `test_audit_log_query_by_user` | 按 user_id 过滤查询 |
| `test_audit_log_query_by_resource` | 按 resource_type + id 过滤 |
| `test_audit_log_skips_get` | GET 请求不写审计 |
| `test_audit_log_skips_non_admin` | /api/chat/* 不写审计 |
| `test_audit_log_async_writes` | 异步写不阻塞响应（响应时间 < 同步写耗时） |

## 7. 文件变更

| 文件 | 类型 |
|---|---|
| `infrastructure/database/models/audit.py` | 新建 |
| `infrastructure/database/repositories/audit_repository.py` | 新建 |
| `api/middleware/audit_middleware.py` | 新建 |
| `api/admin/audit.py` | 新建 |
| `api/admin/__init__.py` | 改：注册 audit_router |
| `server.py` | 改：注册 audit middleware |
| `test/test_audit_log.py` | 新建 |
| `frontend/src/views/AuditLogView.vue` | 新建（第二期，可选） |

## 8. 关键设计决策

1. **异步写不阻塞**：用 `asyncio.create_task` 写审计，主响应不等待。**风险**：进程崩溃丢失审计。**缓解**：第一期接受少量丢失；第二期加 queue + retry。
2. **before 查询性能**：PUT/DELETE 前要查旧记录，多一次 DB 查询。**缓解**：用 repository 缓存（agent 等热数据）；冷数据接受额外耗时。
3. **resource_type 推断**：从 path 解析。**备选**：在路由装饰器显式声明（侵入大）。**推荐**：path 推断，普适且零侵入。
4. **保留期**：第一期不实施归档，全量保留；第二期加 `audit_retention_days` 配置 + 定时清理任务。
5. **adminOnly 访问**：只有 admin 角色可查询审计日志（合规要求）。

## 9. 兼容性影响

- 现有 admin 路由**零改动**（middleware 全局拦截）
- 性能影响：每个写请求多一次 before 查询（PUT/DELETE）+ 异步写日志，P99 增加 < 5ms
- 新增 `/api/admin/audit/*` 路由，不冲突现有路由
