# 成本统计设计 — token 用量 + 配额管理（P0）

> 日期：2026-07-19
> 状态：📝 DESIGN（待评审）
> 上下文：企业级短板补齐——商业可持续性必备

## 1. 背景

Langfuse 已接入 trace，但**无成本统计**——per workspace / per agent / per user 的 token 用量无记录，无法做配额控制、计费、成本归因。

## 2. 目标

- **G1**：每次 dispatch 完成自动写 `tb_usage_record`（含 prompt/completion tokens + model + cost_usd）
- **G2**：per workspace 配额（月度 token 上限），超限策略可配（拒绝/降级/告警）
- **G3**：前端成本中心页面（按维度图表 + 实时配额进度）
- **G4**：与 Langfuse trace 关联（dispatch_id 关联）
- **G5**：性能不影响主流程（异步写）

## 3. 数据模型

### 新增表 `tb_usage_record`

```sql
CREATE TABLE tb_usage_record (
    pr_key_id        BIGINT PRIMARY KEY AUTO_INCREMENT,
    usage_id         VARCHAR(64)  NOT NULL UNIQUE COMMENT 'USAGE_ 前缀',
    dispatch_id      VARCHAR(64)  COMMENT '关联 tb_dispatch_record',
    trigger_id       VARCHAR(64)  COMMENT '触发器 dispatch 时记录',
    workspace_id     BIGINT       NOT NULL,
    agent_id         BIGINT       COMMENT '具体 agent（多 agent 时多行）',
    user_id          VARCHAR(64)  COMMENT '触发用户',
    model_id         VARCHAR(64)  NOT NULL COMMENT 'LLM 模型 ID',
    prompt_tokens    INT          DEFAULT 0,
    completion_tokens INT         DEFAULT 0,
    total_tokens     INT          DEFAULT 0,
    cost_usd         DECIMAL(10,6) DEFAULT 0 COMMENT '美元成本',
    duration_ms      INT,
    create_time      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_workspace_time (workspace_id, create_time),
    INDEX idx_agent_time (agent_id, create_time),
    INDEX idx_dispatch (dispatch_id)
);
```

### 新增表 `tb_quota`

```sql
CREATE TABLE tb_quota (
    pr_key_id      BIGINT PRIMARY KEY AUTO_INCREMENT,
    workspace_id   BIGINT NOT NULL,
    quota_type     VARCHAR(20) NOT NULL COMMENT 'monthly_token/daily_token/monthly_cost',
    limit_value    BIGINT NOT NULL COMMENT '上限值',
    period         VARCHAR(20) COMMENT 'YYYY-MM 或 YYYY-MM-DD',
    used_value     BIGINT DEFAULT 0 COMMENT '已用值',
    over_limit_action VARCHAR(20) DEFAULT 'warn' COMMENT 'warn/block/degrade',
    status         VARCHAR(20) DEFAULT 'active',
    create_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_workspace_quota_period (workspace_id, quota_type, period)
);
```

### 模型成本矩阵 `tb_model_pricing`（可选，第二期）

记录每个模型的 input/output token 单价。第一期可硬编码常用模型单价。

## 4. 服务层

### `services/usage_service.py`（新建）

```python
class UsageService:
    def record_usage(self, dispatch_id, workspace_id, agent_id, user_id,
                     model_id, prompt_tokens, completion_tokens, duration_ms,
                     trigger_id=None):
        # 计算成本（按 model_pricing 矩阵）
        cost = self._calc_cost(model_id, prompt_tokens, completion_tokens)
        UsageRepository().create(...)

    def check_quota(self, workspace_id, estimated_tokens) -> tuple[bool, str]:
        # 检查月度配额，返回 (allowed, reason)
        ...

    def get_workspace_usage(self, workspace_id, start_date, end_date, group_by='day'):
        # 聚合查询
        ...

    def _calc_cost(self, model_id, prompt_tokens, completion_tokens) -> float:
        # 第一期硬编码常用模型，第二期查 tb_model_pricing
        ...
```

### Hook 进 dispatch_stream

在 `MultiAgentService.dispatch_stream` 完成 hook 里调 `record_usage`：

```python
# services/multi_agent_service.py 改动
async for ev in graph.astream(...):
    # 现有逻辑
    ...
# dispatch 完成后（catch collected_results）
from services.usage_service import UsageService
# 每个 task 的 LLM 调用有 token usage（从 LangGraph state 或 Langfuse 拿）
# 简化：用 dispatch_id 关联，从 Langfuse trace 查询 token usage
UsageService().record_usage(dispatch_id=dispatch_id, ...)
```

**token usage 数据来源**：
- LangChain 的 `AIMessage.usage_metadata`（response_metadata.usage）
- 或 Langfuse trace 的 generation 详情
- 第一期从 `collected_results` 反推不可行（只有文本），需扩展 adapter 暴露 usage

**简化方案（第一期）**：
- 在 `LangGraphTaskExecutor.execute_task_stream` 里捕获 LLM response 的 `usage_metadata`
- 写到 `WorkflowState.usage` dict（新增字段）
- dispatch 完成后从 state 读 usage，调 `record_usage`

### `services/quota_service.py`（新建）

```python
class QuotaService:
    def check_and_deduct(self, workspace_id, quota_type, estimated) -> bool:
        # 1. 检查是否超限
        # 2. 超限 + action=block → 拒绝
        # 3. 超限 + action=degrade → 切备用模型
        # 4. 超限 + action=warn → 告警 + 继续
        # 5. 未超 → 累加 used_value
        ...

    def get_quota_status(self, workspace_id) -> list:
        # 返回当前配额使用情况
        ...
```

## 5. API 路由

新增 `api/admin/usage.py`：

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/api/admin/usage/workspace/{id}` | require_read | workspace 用量聚合（支持 group_by + date_range） |
| GET | `/api/admin/usage/agent/{id}` | require_read | agent 用量聚合 |
| GET | `/api/admin/usage/dispatch/{dispatch_id}` | require_read | 单次 dispatch 用量明细 |
| GET | `/api/admin/quota/{workspace_id}` | require_read | workspace 配额状态 |
| POST | `/api/admin/quota` | require_write + adminOnly | 创建/更新配额 |
| GET | `/api/admin/usage/pricing` | require_read | 模型单价表 |

## 6. 测试

| 测试 | 验证 |
|---|---|
| `test_usage_record_after_dispatch` | dispatch 后 tb_usage_record 有记录 |
| `test_usage_token_count_correct` | prompt/completion tokens 与 LLM 返回一致 |
| `test_usage_cost_calc_by_model` | 不同 model 不同成本计算 |
| `test_quota_check_blocks_when_over` | 超限 + action=block 拒绝 dispatch |
| `test_quota_check_warns_when_over` | 超限 + action=warn 继续执行 + 告警 |
| `test_quota_deduct_after_usage` | usage 写入后 used_value 累加 |
| `test_usage_async_write_no_block` | 异步写不阻塞 dispatch 响应 |

## 7. 文件变更

| 文件 | 类型 |
|---|---|
| `infrastructure/database/models/usage.py` | 新建（UsageRecord + Quota） |
| `infrastructure/database/repositories/usage_repository.py` | 新建 |
| `services/usage_service.py` | 新建 |
| `services/quota_service.py` | 新建 |
| `api/admin/usage.py` | 新建 |
| `api/admin/__init__.py` | 改：注册 usage_router |
| `services/multi_agent_service.py` | 改：dispatch 完成后调 UsageService.record_usage |
| `executor/workflow/stategraph_builder.py` | 改：WorkflowState 加 `usage` dict 字段 |
| `executor/langgraph/task_executor.py` | 改：捕获 LLM response usage_metadata 写入 state |
| `test/test_usage_record.py` | 新建 |
| `frontend/src/views/UsageView.vue` | 新建（成本中心） |
| `frontend/src/api/index.js` | 改：加 usageApi + quotaApi |

## 8. 关键设计决策

1. **token 来源**：从 LangChain `AIMessage.usage_metadata` 拿（标准字段）。**备选**：从 Langfuse trace 查询。**推荐**：直接拿 message 字段，不依赖 Langfuse。
2. **配额策略**：3 种 action（warn/block/degrade）。**第一期**只实施 warn，block/degrade 第二期。**理由**：warn 不破坏现有流程。
3. **成本计算**：第一期硬编码常用模型单价（qwen-turbo/claude-3/gpt-4 等），第二期查 tb_model_pricing。**理由**：最小可行。
4. **异步写**：用 `asyncio.create_task` 写 usage，不阻塞 dispatch 响应。**风险**：崩溃丢 usage。**缓解**：第一期接受少量丢失；可加 fallback 同步写。
5. **多 agent dispatch**：一次 dispatch 多个 task → 每个 task 一行 usage_record。**聚合查询**按 dispatch_id 聚合。
6. **Workspace 配额 vs Agent 配额**：第一期只 workspace 级。第二期加 agent 级。

## 9. 兼容性影响

- `MultiAgentService.dispatch_stream` 加 usage hook，对现有调用零影响（异步写）
- `WorkflowState` 加 `usage` dict 字段，不破坏现有 `results`/`errors` reducer
- LangGraphTaskExecutor 改动只多写一个字段，不影响主流程
- 现有 dispatch 测试应继续通过（usage 写是异步副作用）
