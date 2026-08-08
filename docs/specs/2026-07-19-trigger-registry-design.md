# 触发器扩展设计 — 定时 / Webhook / 文件变更触发

> 日期：2026-07-19
> 方案：统一 `TriggerRegistry` 抽象 + 3 个具体触发器实现，所有触发归约到 `MultiAgentService.dispatch_stream`
> 第一期 scope：CronTrigger（定时） + WebhookTrigger（事件驱动） + FileWatchTrigger（文件/数据变更）
> 上下文：承接 `docs/executoranalyse.md` 调度系统分析；与 `docs/specs/2026-07-19-team-collaboration-design.md`（⏸️ SHELVED）正交解耦——团队是"谁做"，触发器是"何时做"

---

## 1. 背景

### 1.1 现状（基于上一轮调研）

| 触发方式 | 现状 | 证据 |
|---|---|---|
| 手动调用 | ✅ 支持 | `server.py` 注册 8 类路由，`MultiAgentService.dispatch_stream` 现成可调 |
| 定时触发 | ❌ 不支持 | 业务代码 0 处使用 APScheduler（仅 `requirements.txt:69` 作为 alibabacloud-credentials 传递依赖） |
| Webhook 事件驱动 | ❌ 不支持 | 全项目无 `/webhook` 路由入口 |
| 文件/数据变更触发 | ❌ 不支持 | 业务代码 0 处使用 `watchfiles`/`watchdog`（仅 `requirements.txt:525` 作为 uvicorn `--reload` 传递依赖） |
| FastAPI lifespan 钩子 | ❌ 无 | `server.py` 全文 60 行，无 `@app.on_event("startup")` / `lifespan` 注册 |

### 1.2 关键观察：依赖已就位，缺的是业务集成

`apscheduler==3.11.2` 和 `watchfiles==1.1.1` **都已经在 `requirements.txt` 中**（虽然是传递依赖）。这意味着：

- ✅ **无新增 Python 依赖**（第一期）
- ✅ **无新增运维负担**（不引入 Redis/RabbitMQ）
- ⚠️ **需要把传递依赖升级为显式声明**（写入 `pyproject.toml` 的 `[project] dependencies`，避免上游 SDK 改动导致依赖消失）

### 1.3 与团队协作方案的关系

`docs/specs/2026-07-19-team-collaboration-design.md` 已 SHELVED。本方案**不依赖团队实体**——所有触发器通过 `target_agent_ids`（agent_id 列表）调用 `dispatch_stream(agent_ids=...)`。将来团队方案解冻后，只需在 `tb_trigger` 加一列 `target_team_id` 即可叠加，**完全正交**。

---

## 2. 目标（第一期）

- **G1 统一抽象**：定义 `ITrigger` 接口（`start()` / `stop()` / `handle(event)`），所有触发器实现此接口，由 `TriggerRegistry` 统一管理注册/启停/日志。
- **G2 CronTrigger**：支持标准 cron 表达式（如 `0 9 * * *` 每日 9 点），按时区触发，调用 `dispatch_stream`。
- **G3 WebhookTrigger**：暴露 `POST /api/admin/triggers/{trigger_id}/webhook` 入站端点，HMAC-SHA256 验签，payload 渲染成 message 后调 `dispatch_stream`。
- **G4 FileWatchTrigger**：监听指定目录（默认 RAG 知识库 `data/knowledge/`），文件 created/modified/deleted 触发，带防抖（5 秒窗口）。
- **G5 配置持久化 + 热更新**：触发器配置存 `tb_trigger` 表；新增/启停通过 API 完成，不需要重启服务（runtime registry 查 DB 重载）。
- **G6 执行历史**：每次触发写入 `tb_trigger_log`，记录 status/dispatch_id/error，可观测可回查。
- **G7 向下兼容**：现有手动调用零影响；`server.py` 加 lifespan 不破坏现有路由；新依赖显式声明不删传递链。

## 3. 非目标

- 触发器配置界面（前端 Vue）→ 第二期（先开放 API + Swagger 验证）
- 分布式 worker（拆进程）→ 第二期（第一期同进程）
- 消息队列（Redis/RabbitMQ）→ 不引入
- 数据库 CDC（监听 MySQL binlog 触发）→ 不做（用 FileWatch 监听文件 + Webhook 接 DB 事件代替）
- 触发器失败自动重试 → 第二期（第一期仅记录 failed 状态）
- 触发器条件表达式（如 "仅当 payload.event == push 时"）→ 第二期（第一期用 message_template 渲染）
- 团队级触发（`target_team_id`）→ 团队方案解冻后加列

---

## 4. 架构

```
┌─────────────────────────────────────────────────────────────────┐
│ server.py（扩展 lifespan）                                         │
│   @asynccontextmanager                                             │
│   async def lifespan(app):                                        │
│       registry = TriggerRegistry.get_instance()                    │
│       await registry.load_from_db()    # 加载所有 enabled trigger  │
│       yield                                                         │
│       await registry.shutdown()       # 优雅停止所有 trigger       │
│   app = FastAPI(lifespan=lifespan, ...)                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ services/trigger_registry.py（新增）                                │
│   class TriggerRegistry:                                           │
│       _triggers: dict[trigger_id, ITrigger]                        │
│       _semaphores: dict[trigger_id, asyncio.Semaphore(1)]          │
│       ├── load_from_db()          # 启动时从 tb_trigger 加载         │
│       ├── register(trigger)      # 动态注册                         │
│       ├── unregister(trigger_id) # 动态注销                         │
│       ├── reload(trigger_id)     # 配置变更后热重载                  │
│       └── shutdown()             # 全部 stop()                      │
└─────────────────────────────────────────────────────────────────┘
        │                  │                  │
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│ CronTrigger   │  │ WebhookTrigger│  │ FileWatchTrigger │
│ (APScheduler)│  │ (FastAPI 路由)│  │ (watchfiles)     │
│ AsyncIOSched  │  │ + HMAC 验签   │  │ awatch() 生成器   │
│ add_job(cron) │  │              │  │ + 5s 防抖         │
└──────────────┘  └──────────────┘  └──────────────────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ▼
              ITrigger.handle(event) 抽象方法
                           │
                           ▼
        ┌──────────────────────────────────────────┐
        │  统一归约（所有触发器最终走这里）            │
        │  1. message = render_template(template, ctx)│
        │  2. await MultiAgentService                │
        │       .dispatch_stream(                    │
        │           agent_ids=target_agent_ids,     │
        │           message=message,                 │
        │           mode=...)                        │
        │  3. 写 tb_trigger_log + 更新 tb_dispatch_  │
        │     record.trigger_id                     │
        └──────────────────────────────────────────┘
```

**关键设计决策**（详见 §15）：
- **不引入消息队列**：APScheduler + watchfiles 同进程跑，靠 `asyncio.Semaphore(1)` per-trigger 串行化防雪崩。
- **不在 LangGraph 图里加触发器入口**：触发器是**外部时序源**，只负责"何时调用 dispatch_stream"，不进入 `WorkflowState`。
- **HMAC 验签而非 OAuth/JWT**：Webhook 是机器对机器，HMAC-SHA256 简单、无状态、与 GitHub/Stripe 通行风格一致。
- **不监听代码目录**：`FileWatchTrigger` 默认监听 `data/knowledge/`，绝不监听 `*.py`，避免与 uvicorn `--reload` 冲突。

---

## 5. 数据模型

### 5.1 新增表 1：`tb_trigger`

```sql
-- 跨平台 DDL：由 SQLAlchemy create_all 生成，不手写 SQL
-- 模型定义见 infrastructure/database/models/trigger.py

CREATE TABLE tb_trigger (
    pr_key_id        BIGINT PRIMARY KEY AUTO_INCREMENT,
    trigger_id       VARCHAR(64)  NOT NULL UNIQUE COMMENT '业务ID，TRG_前缀',
    trigger_name     VARCHAR(100) NOT NULL,
    trigger_type     VARCHAR(20)  NOT NULL COMMENT 'cron|webhook|file_watch',
    config           TEXT         NOT NULL COMMENT 'JSON：类型相关配置',
    target_agent_ids VARCHAR(500) NOT NULL COMMENT '逗号分隔 agent_id 列表',
    target_mode      VARCHAR(20)  DEFAULT 'parallel' COMMENT 'dispatch 模式',
    message_template TEXT         NOT NULL COMMENT 'Jinja2 模板，渲染触发上下文',
    workspace_id     BIGINT       NOT NULL COMMENT '所属 tb_workspace',
    enabled          VARCHAR(1)   DEFAULT '1' COMMENT '1=启用 0=禁用',
    del_flag         VARCHAR(1)   DEFAULT '0',
    creator_id       BIGINT       COMMENT '创建者 user_id',
    create_time      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    update_time      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_workspace (workspace_id),
    INDEX idx_type_enabled (trigger_type, enabled)
);
```

**`config` 字段 JSON 结构**（按 trigger_type 不同）：

```jsonc
// CronTrigger
{"cron": "0 9 * * *", "timezone": "Asia/Shanghai"}

// WebhookTrigger
{"secret": "<hmac_key_string>", "allowed_ips": ["10.0.0.0/8"]}

// FileWatchTrigger
{"watch_path": "data/knowledge/", "event_types": ["created","modified","deleted"], "debounce_ms": 5000, "glob": "*.md"}
```

### 5.2 新增表 2：`tb_trigger_log`

```sql
CREATE TABLE tb_trigger_log (
    pr_key_id    BIGINT PRIMARY KEY AUTO_INCREMENT,
    log_id       VARCHAR(64)  NOT NULL UNIQUE COMMENT '业务ID，TRG_LOG_前缀',
    trigger_id   VARCHAR(64)  NOT NULL,
    trigger_type VARCHAR(20)  NOT NULL COMMENT '快照，便于查询',
    event_data   TEXT         COMMENT 'JSON：触发上下文（payload/cron 时间/文件路径等）',
    dispatch_id  VARCHAR(64)  COMMENT '关联 tb_dispatch_record.dispatch_id',
    status       VARCHAR(20)  DEFAULT 'running' COMMENT 'running|completed|failed|skipped',
    error        TEXT,
    duration_ms  INT,
    create_time  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_trigger (trigger_id, create_time),
    INDEX idx_dispatch (dispatch_id)
);
```

### 5.3 改动表：`tb_dispatch_record`

新增 1 列（与团队方案的 `team_id` 列并行，互不依赖）：

```sql
ALTER TABLE tb_dispatch_record
  ADD COLUMN IF NOT EXISTS trigger_id VARCHAR(64) NULL COMMENT '触发器 dispatch 时记录';
```

> 注意：团队方案的 `team_id` 列定义在 SHELVED 状态下不实施，但本方案的 `trigger_id` 列独立实施。若将来两个方案都落地，两列并存无冲突。

### 5.4 SQLAlchemy 模型文件

新增 `infrastructure/database/models/trigger.py`，包含 `Trigger` / `TriggerLog` 两个类，均继承 `Base` + `TimestampMixinLegacy`（参照 `dispatch_record.py` 模式）。`dispatch_record.py` 加 `trigger_id` 字段。

---

## 6. 服务层

### 6.1 抽象接口：`services/trigger/base.py`

```python
# services/trigger/base.py
"""触发器抽象接口 + 渲染工具。"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from datetime import datetime


class ITrigger(ABC):
    """所有触发器实现此接口。生命周期：register → start → handle×N → stop。"""

    def __init__(self, trigger_id: str, config: Dict[str, Any],
                 target_agent_ids: list, target_mode: str,
                 message_template: str, workspace_id: int):
        self.trigger_id = trigger_id
        self.config = config
        self.target_agent_ids = target_agent_ids
        self.target_mode = target_mode
        self.message_template = message_template
        self.workspace_id = workspace_id
        self._semaphore = asyncio.Semaphore(1)  # per-trigger 串行化

    @abstractmethod
    async def start(self) -> None: ...  # 启动监听（注册 cron job / 路由 / watcher）

    @abstractmethod
    async def stop(self) -> None: ...  # 停止监听 + 释放资源

    async def handle(self, event: Dict[str, Any]) -> str:
        """统一归约：渲染模板 → 调 dispatch_stream → 写 log。
        event 示例：
          CronTrigger:    {"triggered_at": "2026-07-19T09:00:00+08:00"}
          WebhookTrigger: {"payload": {...}, "headers": {...}, "client_ip": "..."}
          FileWatchTrigger: {"file": "data/knowledge/x.md", "event": "modified"}
        """
        async with self._semaphore:  # 串行化，防雪崩
            log_id = f"TRG_LOG_{generate_uuid()[:16]}"
            started = datetime.utcnow()
            try:
                message = render_template(self.message_template, event)
                from services.multi_agent_service import MultiAgentService
                svc = MultiAgentService()
                dispatch_id = None
                async for ev in svc.dispatch_stream(
                    agent_ids=self.target_agent_ids,
                    message=message,
                    mode=self.target_mode,
                ):
                    if ev.get("type") == "dispatch_started":
                        dispatch_id = ev.get("dispatch_id")
                status = "completed"
            except Exception as e:
                logger.error(f"[Trigger {self.trigger_id}] handle failed: {e}", exc_info=True)
                status = "failed"
                error = str(e)[:500]
                dispatch_id = None
            finally:
                duration_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
                self._write_log(log_id, event, dispatch_id, status,
                                locals().get("error", ""), duration_ms)
            return log_id

    def _write_log(self, log_id, event, dispatch_id, status, error, duration_ms):
        """写 tb_trigger_log（同步 DB 操作，与现有 Repository 模式一致）。"""
        from infrastructure.database.repositories.trigger_repository import TriggerLogRepository
        TriggerLogRepository().create(
            log_id=log_id, trigger_id=self.trigger_id,
            trigger_type=self.__class__.__name__.replace("Trigger", "").lower(),
            event_data=json.dumps(event, ensure_ascii=False, default=str),
            dispatch_id=dispatch_id, status=status, error=error,
            duration_ms=duration_ms,
        )


def render_template(template: str, ctx: Dict[str, Any]) -> str:
    """Jinja2 渲染。第一期仅支持 {{ var }} 简单替换，不启用完整 Jinja2（避免 RCE 风险）。
    若需复杂模板，第二期引入 jinja2（已是 langchain-core 依赖，无需新增）。"""
    # 第一期：str.format 风格的安全替换
    try:
        return template.format(**ctx)
    except (KeyError, IndexError):
        return template  # 渲染失败兜底用原文
```

### 6.2 CronTrigger：`services/trigger/cron_trigger.py`

```python
# services/trigger/cron_trigger.py
"""定时触发器：用 APScheduler AsyncIOScheduler。
注意：APScheduler 是 alibabacloud-credentials 的传递依赖，本方案同时把它升级为
pyproject.toml 的显式 dependencies（见 §12 文件变更），避免上游 SDK 变动导致依赖消失。
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from .base import ITrigger


class CronTrigger(ITrigger):
    _scheduler: AsyncIOScheduler = None  # 进程级单例，所有 cron trigger 共享

    @classmethod
    def get_scheduler(cls) -> AsyncIOScheduler:
        if cls._scheduler is None or not cls._scheduler.running:
            cls._scheduler = AsyncIOScheduler()
            cls._scheduler.start()
        return cls._scheduler

    async def start(self):
        cron_expr = self.config["cron"]
        timezone = self.config.get("timezone", "Asia/Shanghai")
        sched = self.get_scheduler()
        # 标准 cron 表达式：分 时 日 月 周
        trigger = CronTrigger.from_crontab(cron_expr, timezone=timezone)
        sched.add_job(self._on_tick, trigger=trigger, id=self.trigger_id,
                      coalesce=True, max_instances=1,  # 防叠加
                      misfire_grace_time=60)  # 错过 60 秒内仍补跑

    async def stop(self):
        sched = self.get_scheduler()
        sched.remove_job(self.trigger_id)

    async def _on_tick(self):
        import datetime as dt
        await self.handle({"triggered_at": dt.datetime.now().isoformat()})
```

### 6.3 WebhookTrigger：`services/trigger/webhook_trigger.py`

```python
# services/trigger/webhook_trigger.py
"""Webhook 触发器：入站事件 → HMAC-SHA256 验签 → 调度。
路由在 api/admin/trigger.py 中定义，触发器实例只持有 secret + IP 白名单做校验。
"""
import hmac, hashlib, ipaddress
from fastapi import Request, HTTPException
from .base import ITrigger


class WebhookTrigger(ITrigger):
    async def start(self):
        pass  # 路由在 FastAPI app 层注册，无需启动后台任务

    async def stop(self):
        pass

    async def verify(self, request: Request) -> Dict:
        """校验签名 + IP 白名单，返回 payload。"""
        # IP 白名单
        allowed = self.config.get("allowed_ips", [])
        if allowed:
            client_ip = ipaddress.ip_address(request.client.host)
            if not any(client_ip in ipaddress.ip_network(cidr, strict=False)
                       for cidr in allowed):
                raise HTTPException(403, "IP not allowed")
        # HMAC-SHA256 验签
        secret = self.config["secret"].encode()
        body = await request.body()
        sig = request.headers.get("X-Webhook-Signature", "")
        expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(401, "Invalid signature")
        # 防重放：要求 X-Webhook-Timestamp，5 分钟内有效
        ts = request.headers.get("X-Webhook-Timestamp")
        if ts and abs(int(time.time()) - int(ts)) > 300:
            raise HTTPException(401, "Timestamp out of range")
        return {"payload": await request.json(),
                "headers": dict(request.headers),
                "client_ip": request.client.host}
```

### 6.4 FileWatchTrigger：`services/trigger/file_watch_trigger.py`

```python
# services/trigger/file_watch_trigger.py
"""文件变更触发器：用 watchfiles.awatch() 异步生成器。
watchfiles 是 uvicorn 的传递依赖，本方案同时升级为 pyproject.toml 显式 dependencies。
"""
from pathlib import Path
from watchfiles import awatch
from .base import ITrigger


class FileWatchTrigger(ITrigger):
    _task = None

    async def start(self):
        watch_path = Path(self.config["watch_path"])
        event_types = set(self.config.get("event_types", ["created", "modified"]))
        debounce_ms = self.config.get("debounce_ms", 5000)
        glob_pattern = self.config.get("glob", "*")
        self._task = asyncio.create_task(self._watch_loop(
            watch_path, event_types, debounce_ms, glob_pattern))

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _watch_loop(self, watch_path, event_types, debounce_ms, glob_pattern):
        # 跨平台：watchfiles 在 Windows 上对 UNC 路径 \\server\share 行为受限，
        # 项目部署用本地路径 F:\... 或 /home/... 不用 UNC
        pending = {}  # file_path -> last_event
        async for changes in awatch(str(watch_path), watch_filter=lambda _, path:
                                     Path(path).match(glob_pattern)):
            for change_type, file_path in changes:
                # change_type: watchfiles.Change.added/modified/deleted
                ev_name = change_type.name.lower()  # 'added'/'modified'/'deleted'
                if ev_name not in event_types:
                    continue
                # 防抖：debounce_ms 内同文件多次变更只触发最后一次
                pending[file_path] = ev_name
            # 处理 pending（debounce 窗口）
            await asyncio.sleep(debounce_ms / 1000)
            for file_path, ev_name in list(pending.items()):
                await self.handle({"file": file_path, "event": ev_name})
                pending.pop(file_path, None)
```

### 6.5 Registry：`services/trigger/registry.py`

```python
# services/trigger/registry.py
"""触发器注册中心：单例，由 server.py lifespan 驱动。"""
from typing import Dict, Optional
from .base import ITrigger
from .cron_trigger import CronTrigger
from .webhook_trigger import WebhookTrigger
from .file_watch_trigger import FileWatchTrigger


class TriggerRegistry:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._triggers: Dict[str, ITrigger] = {}
        self._TRIGGER_CLASSES = {
            "cron": CronTrigger, "webhook": WebhookTrigger, "file_watch": FileWatchTrigger,
        }

    async def load_from_db(self):
        """启动时加载所有 enabled trigger。幂等。"""
        from infrastructure.database.repositories.trigger_repository import TriggerRepository
        rows = TriggerRepository().get_all(filters={"enabled": "1", "del_flag": "0"})
        for row in rows:
            await self.register(row)

    async def register(self, config_row: Dict):
        """根据 config_row 实例化 trigger 并 start()。"""
        ttype = config_row["trigger_type"]
        cls = self._TRIGGER_CLASSES.get(ttype)
        if not cls:
            logger.warning(f"[TriggerRegistry] 未知类型 {ttype}，跳过")
            return
        trigger = cls(
            trigger_id=config_row["trigger_id"],
            config=json.loads(config_row["config"]),
            target_agent_ids=config_row["target_agent_ids"].split(","),
            target_mode=config_row.get("target_mode", "parallel"),
            message_template=config_row["message_template"],
            workspace_id=config_row["workspace_id"],
        )
        await trigger.start()
        self._triggers[trigger.trigger_id] = trigger
        logger.info(f"[TriggerRegistry] registered {trigger.trigger_id} ({ttype})")

    async def unregister(self, trigger_id: str):
        t = self._triggers.pop(trigger_id, None)
        if t:
            await t.stop()

    async def reload(self, trigger_id: str):
        """配置变更后热重载：先 stop 旧实例 → 从 DB 取新配置 → register。"""
        await self.unregister(trigger_id)
        from infrastructure.database.repositories.trigger_repository import TriggerRepository
        row = TriggerRepository().get_by_trigger_id(trigger_id)
        if row and row.get("enabled") == "1":
            await self.register(row)

    async def get_webhook_trigger(self, trigger_id: str) -> Optional[WebhookTrigger]:
        """供路由层调用：取已注册的 webhook trigger 实例做验签。"""
        t = self._triggers.get(trigger_id)
        return t if isinstance(t, WebhookTrigger) else None

    async def shutdown(self):
        for tid in list(self._triggers.keys()):
            await self.unregister(tid)
        # 关闭共享 scheduler
        from .cron_trigger import CronTrigger
        if CronTrigger._scheduler and CronTrigger._scheduler.running:
            CronTrigger._scheduler.shutdown(wait=False)
```

---

## 7. API 路由改动点

### 7.1 新增路由文件：`api/admin/trigger.py`

参照 `api/admin/subagent.py` 风格：

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/api/admin/triggers` | `require_write("trigger")` | 创建触发器（不自动启动） |
| GET | `/api/admin/triggers` | `require_read("trigger")` | 列出当前 workspace 的触发器 |
| GET | `/api/admin/triggers/{trigger_id}` | `require_read("trigger")` | 触发器详情 |
| PUT | `/api/admin/triggers/{trigger_id}` | `require_write("trigger")` | 更新配置（自动 reload） |
| DELETE | `/api/admin/triggers/{trigger_id}` | `require_delete("trigger")` | 软删 + 注销 |
| POST | `/api/admin/triggers/{trigger_id}/enable` | `require_write("trigger")` | 启用（register + start） |
| POST | `/api/admin/triggers/{trigger_id}/disable` | `require_write("trigger")` | 禁用（unregister） |
| POST | `/api/admin/triggers/{trigger_id}/test` | `require_write("trigger")` | 手动触发一次（用空 event） |
| GET | `/api/admin/triggers/{trigger_id}/logs` | `require_read("trigger")` | 查询执行历史 |
| **POST** | **`/api/admin/triggers/{trigger_id}/webhook`** | **公开**（HMAC 验签） | **Webhook 入站端点** |

**Webhook 路由特殊处理**：该端点**不走 `verify_token`**（admin 默认鉴权），而是用 `WebhookTrigger.verify` 做 HMAC 验签。路由注册时单独处理：

```python
# api/admin/trigger.py
@router.post("/{trigger_id}/webhook")
async def webhook_inbound(trigger_id: str, request: Request):
    """Webhook 入站：不依赖 admin verify_token，用 HMAC 验签。"""
    registry = TriggerRegistry.get_instance()
    trigger = await registry.get_webhook_trigger(trigger_id)
    if not trigger:
        raise HTTPException(404, "Webhook trigger not found or not enabled")
    event = await trigger.verify(request)  # 验签失败 raise 401/403
    log_id = await trigger.handle(event)
    return {"log_id": log_id, "status": "triggered"}
```

### 7.2 路由注册：`api/admin/__init__.py` 改动

```python
# 新增 2 行
from .trigger import router as trigger_router
# ...
admin_router.include_router(trigger_router)
```

### 7.3 `server.py` 加 lifespan

```python
# server.py
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    from services.trigger.registry import TriggerRegistry
    registry = TriggerRegistry.get_instance()
    await registry.load_from_db()
    logger.info(f"[Lifespan] {len(registry._triggers)} triggers loaded")
    yield
    # shutdown
    await registry.shutdown()
    logger.info("[Lifespan] triggers stopped")

app = FastAPI(title="Agent API", ..., lifespan=lifespan)
```

> 注意：`app = FastAPI(...)` 行需要改 1 处：加 `lifespan=lifespan` 参数。其余注册逻辑不变。

### 7.4 前端契约（第二期）

第一期不写前端，仅用 Swagger `/docs` 验证。第二期新增 `frontend/src/views/trigger/TriggerList.vue` + `TriggerDetail.vue`。

---

## 8. 数据流

### 8.1 CronTrigger 触发流

```
APScheduler AsyncIOScheduler
    │ 到达 cron 表达式时间点（如每日 9:00 Asia/Shanghai）
    ▼
CronTrigger._on_tick()
    │ await self.handle({"triggered_at": "2026-07-19T09:00:00+08:00"})
    ▼
ITrigger.handle（串行 semaphore）
    ├── render_template("生成每日报告，日期：{triggered_at}", event)
    │   → message = "生成每日报告，日期：2026-07-19T09:00:00+08:00"
    ├── MultiAgentService.dispatch_stream(agent_ids=[...], message=message)
    │   → yield SSE events → 收集 dispatch_id
    └── TriggerLogRepository.create({status: completed/failed, dispatch_id, ...})
```

### 8.2 WebhookTrigger 触发流

```
外部系统（GitHub/Stripe/自建）
    │ POST /api/admin/triggers/TRG_xxx/webhook
    │   Headers: X-Webhook-Signature: sha256=..., X-Webhook-Timestamp: 1234567890
    │   Body: {"event": "push", "data": {...}}
    ▼
api/admin/trigger.py::webhook_inbound
    │ registry.get_webhook_trigger(trigger_id)
    ▼
WebhookTrigger.verify(request)
    ├── IP 白名单校验（可选）
    ├── HMAC-SHA256 签名校验（hmac.compare_digest，防时序攻击）
    └── Timestamp 防重放（5 分钟窗口）
    ▼
trigger.handle({"payload": {...}, "headers": {...}, "client_ip": "..."})
    ├── render_template("处理 webhook 事件：{payload[event]}", event)
    └── dispatch_stream → TriggerLog
```

### 8.3 FileWatchTrigger 触发流

```
用户在 data/knowledge/ 新增 文件 x.md
    ▼
watchfiles.awatch() 检测到 Change.added
    ▼
FileWatchTrigger._watch_loop
    ├── pending["data/knowledge/x.md"] = "added"
    ├── await asyncio.sleep(5.0)  # 5 秒防抖窗口
    │   （5 秒内 x.md 又被修改 → pending 更新为 "modified"，只触发一次）
    └── handle({"file": "data/knowledge/x.md", "event": "modified"})
        ├── render_template("文件 {file} 变更（{event}），请重新索引", event)
        └── dispatch_stream → 触发 RAG agent 重新索引
```

### 8.4 创建 + 启用触发器流

```
管理员 → POST /api/admin/triggers {trigger_type: cron, config: {cron: "0 9 * * *"}, ...}
    │ TriggerRepository.create（写 tb_trigger，enabled='0'）
    ▼
管理员 → POST /api/admin/triggers/{trigger_id}/enable
    │ TriggerRepository.update(enabled='1')
    │ TriggerRegistry.reload(trigger_id) → unregister(旧) → register(新) → start()
    ▼
触发器进入运行态，按类型开始监听
```

---

## 9. 错误处理与兼容性

| 场景 | 处理 |
|---|---|
| cron 表达式非法 | 创建时校验 `CronTrigger.from_crontab`，失败返回 400 |
| Webhook 验签失败 | 401 + 写 log（status='failed', error='Invalid signature'） |
| Webhook IP 不在白名单 | 403 + 写 log |
| Webhook timestamp 超时 | 401（防重放） |
| FileWatch 监听路径不存在 | start() 时 `watchfiles` raise → log + registry 标记 disabled |
| FileWatch 权限不足（Windows/macOS） | start() 时 raise → log；建议运行账号对监听目录有读权限 |
| dispatch_stream 失败 | handle() except 块写 log status='failed'，不重试（第一期） |
| 触发器叠加（同一 trigger 同时多次触发） | per-trigger `Semaphore(1)` 串行化，后续触发排队 |
| APScheduler job 错过执行窗口 | `misfire_grace_time=60` 60 秒内补跑，超出跳过 |
| 服务重启 | lifespan startup → `load_from_db()` 重新加载所有 enabled trigger；MemoryJobStore 不持久化但配置在 DB 不丢 |
| 服务关闭 | lifespan shutdown → `registry.shutdown()` 停所有 trigger + 关闭 scheduler |
| `tb_dispatch_record.trigger_id` 新列对旧记录 | NULL，向后兼容 |
| 现有手动 `dispatch_stream(agent_ids=[...])` 调用 | 零影响（trigger_id=None） |
| 跨平台路径 | `FileWatchTrigger` 用 `pathlib.Path`；Windows 不支持 UNC `\\server\share`（部署用本地盘）；macOS/Linux 通用 |
| `apscheduler` 作为传递依赖被上游移除 | 本方案同时写入 `pyproject.toml` 显式 dependencies（见 §12），锁住 |
| `watchfiles` 同上 | 同上处理 |

---

## 10. 测试

### 10.1 单元测试（`test/test_trigger_service.py` 新建）

| 测试 | 验证 |
|---|---|
| `test_render_template_basic` | `{triggered_at}` 替换正确 |
| `test_render_template_missing_key` | 缺 key 兜底返回原文 |
| `test_cron_trigger_start_stop` | add_job / remove_job 调用正确 |
| `test_cron_trigger_invalid_expr` | 非法 cron 抛 ValueError |
| `test_webhook_verify_hmac_valid` | 正确签名通过 |
| `test_webhook_verify_hmac_invalid` | 错误签名 raise 401 |
| `test_webhook_verify_ip_blocked` | IP 不在白名单 raise 403 |
| `test_webhook_verify_timestamp_replay` | 超时戳 raise 401 |
| `test_file_watch_debounce` | 5 秒内多次变更只触发 1 次 |
| `test_file_watch_glob_filter` | glob 不匹配的事件被过滤 |
| `test_trigger_log_write` | handle 后 tb_trigger_log 有记录 |
| `test_trigger_semaphore_serializes` | 并发 handle 排队执行 |

### 10.2 集成测试（`test/test_trigger_e2e.py` 新建）

| 测试 | 验证 |
|---|---|
| `test_cron_trigger_dispatch` | 手动调 `_on_tick` → dispatch_stream 启动 → SSE 事件齐全 |
| `test_webhook_trigger_dispatch` | POST webhook → dispatch 启动 → log status=completed |
| `test_file_watch_trigger_dispatch` | 写入测试文件 → 5 秒后 dispatch 启动 |
| `test_trigger_lifespan_startup_shutdown` | lifespan 启动时 load_from_db，关闭时 shutdown |
| `test_trigger_reload_after_update` | PUT 配置后自动 reload，新配置生效 |
| `test_dispatch_backward_compat` | 旧 `dispatch_stream(agent_ids=[...])` 仍工作 |

### 10.3 验证命令

```bash
# 跨平台通用（Windows/macOS/Linux）
python -m pytest test/test_trigger_service.py -v
python -m pytest test/test_trigger_e2e.py -v

# 建表（首次）
python -c "from infrastructure.database.base import Base; from infrastructure.database.engines import get_config_engine; import infrastructure.database.models.trigger; Base.metadata.create_all(get_config_engine(), checkfirst=True)"

# 手动验证 cron（创建后等下次触发，或调 /api/admin/triggers/{id}/test）
# 手动验证 webhook（curl 示例，跨平台）
python -c "import hmac,hashlib,time; secret=b'test'; body=b'{\"event\":\"push\"}'; ts=int(time.time()); sig='sha256='+hmac.new(secret,body,hashlib.sha256).hexdigest(); print(f'curl -X POST http://localhost:8072/api/admin/triggers/TRG_xxx/webhook -H \"X-Webhook-Signature: {sig}\" -H \"X-Webhook-Timestamp: {ts}\" -H \"Content-Type: application/json\" -d \\'{\"event\":\"push\"}\\'')"
```

---

## 11. 分阶段

| 阶段 | 内容 | 依赖 |
|---|---|---|
| 1 | 数据模型：`trigger.py`（Trigger + TriggerLog） + `dispatch_record.py` 加 `trigger_id` 列 | 无 |
| 2 | 抽象层：`services/trigger/base.py`（ITrigger + render_template + handle 归约） | 阶段 1 |
| 3 | 3 个具体触发器：`cron_trigger.py` / `webhook_trigger.py` / `file_watch_trigger.py` | 阶段 2 |
| 4 | Registry：`services/trigger/registry.py`（load_from_db / register / reload / shutdown） | 阶段 2-3 |
| 5 | lifespan 集成：`server.py` 改 ~10 行（加 lifespan + 改 app 初始化） | 阶段 4 |
| 6 | API 路由：`api/admin/trigger.py`（含 webhook 入站端点） + 注册到 `admin_router` | 阶段 4 |
| 7 | 依赖显式声明：`pyproject.toml` 加 `apscheduler>=3.11` + `watchfiles>=1.1` | 阶段 3-5 |
| 8 | 测试：单元 + E2E | 阶段 1-6 |

---

## 12. 文件变更

### 新增（8 个）

| 文件 | 类型 |
|---|---|
| `infrastructure/database/models/trigger.py` | 新建 |
| `infrastructure/database/repositories/trigger_repository.py` | 新建 |
| `services/trigger/__init__.py` | 新建（包初始化） |
| `services/trigger/base.py` | 新建（ITrigger + render_template） |
| `services/trigger/cron_trigger.py` | 新建 |
| `services/trigger/webhook_trigger.py` | 新建 |
| `services/trigger/file_watch_trigger.py` | 新建 |
| `services/trigger/registry.py` | 新建 |
| `api/admin/trigger.py` | 新建 |
| `test/test_trigger_service.py` + `test/test_trigger_e2e.py` | 新建 |

### 修改（4 个）

| 文件 | 改动 |
|---|---|
| `infrastructure/database/models/dispatch_record.py` | 加 `trigger_id` 字段（与团队方案 `team_id` 列并行，互不依赖） |
| `api/admin/__init__.py` | 注册 `trigger_router`（2 行） |
| `server.py` | 加 lifespan（~10 行）+ 改 `app = FastAPI(...)` 加 `lifespan=lifespan` 参数 |
| `pyproject.toml` | `[project] dependencies` 显式加 `apscheduler>=3.11` + `watchfiles>=1.1`（升级传递依赖为显式声明） |

---

## 13. 后续期

| 期 | 内容 |
|---|---|
| 第二期 | 触发器失败自动重试（指数退避 + max_retries 配置） |
| 第二期 | 触发器条件表达式（如 `payload.event == "push"` 时才触发） |
| 第二期 | 前端管理页面（TriggerList.vue + TriggerDetail.vue + 实时日志查看） |
| 第二期 | 分布式 worker（拆进程，APScheduler jobstore 用 Redis/MySQL 持久化） |
| 第三期 | 数据库 CDC 触发器（监听 MySQL binlog，行变更触发） |
| 第三期 | 触发器链式编排（A 触发器完成后触发 B 触发器） |
| 第三期 | 完整 Jinja2 模板引擎（含安全沙箱，支持条件/循环） |

---

## 14. 风险

- **APScheduler 同进程阻塞**：`_on_tick` 同步执行 `dispatch_stream` 可能阻塞 scheduler 线程。缓解：`AsyncIOScheduler` 与 FastAPI 共享 event loop；`Semaphore(1)` 串行化；`misfire_grace_time` 防叠加。
- **Webhook 公开端点安全**：`/webhook` 路由不走 admin 鉴权。缓解：强制 HMAC-SHA256 + IP 白名单 + timestamp 防重放；secret 存 DB 时加密（第二期）。
- **FileWatch Windows 兼容性**：`watchfiles` 在 Windows 上对 UNC 路径 `\\server\share` 行为受限。缓解：部署文档注明用本地盘 `F:\...` 或 `C:\...`；测试用例覆盖 Windows 路径。
- **防抖逻辑边界**：5 秒窗口内不同文件变更会被合并批量触发。缓解：`pending` dict 按文件路径独立计数；每个文件只触发一次。
- **配置热更新竞态**：`reload` 时旧实例 stop + 新实例 start 之间如果有触发到达，会被丢弃。缓解：`Semaphore(1)` 串行化，reload 等待 in-flight 完成；第一期接受少量丢失。
- **依赖漂移**：`apscheduler` 当前作为 `alibabacloud-credentials` 的传递依赖存在，上游 SDK 改动可能移除。缓解：§11 阶段 7 显式写入 `pyproject.toml`，锁住。
- **MemoryJobStore 重启丢失**：APScheduler 用 `MemoryJobStore`，进程重启时未执行的 job 丢失。缓解：配置在 DB 不丢；重启后 `load_from_db` 重新注册；第二期可切 `SQLAlchemyJobStore` 持久化。
- **触发器 → 团队方案耦合**：第一期用 `target_agent_ids`（agent_id 列表），团队方案 SHELVED。将来团队方案解冻后加一列 `target_team_id` 即可叠加，**无破坏性改动**。
- **跨平台路径分隔符**：`pathlib.Path` 自动处理；`watchfiles` 内部用 `os.fsencode`；测试用例覆盖 Windows + POSIX。

---

## 15. 关键设计决策（需用户确认）

> 以下 6 个决策项我已给出**默认推荐**，如有不同偏好请在评审时指出：

1. **统一抽象层 `TriggerRegistry`**：推荐做统一抽象（vs 3 个独立 service）。**理由**：可观测性（统一 log）、配置一致（一张表）、未来扩展简单（新触发器类型只需实现 ITrigger）。

2. **CronTrigger 实现选型**：推荐 **APScheduler `AsyncIOScheduler`**（vs 纯 `asyncio.sleep` 循环）。**理由**：APScheduler 已装、支持 cron 表达式 + 时区 + misfire 处理 + max_instances 防叠加；纯 asyncio 要自己实现这些语义，重复造轮子。

3. **Webhook 鉴权方式**：推荐 **HMAC-SHA256 + IP 白名单 + timestamp 防重放**（vs OAuth/JWT）。**理由**：机器对机器通信，HMAC 无状态、与 GitHub/Stripe 通行风格一致、无 token 刷新问题。

4. **FileWatch 监听对象**：推荐**仅监听 `data/knowledge/`（RAG 知识库目录）**（vs 全项目目录）。**理由**：避免与 uvicorn `--reload` 冲突；RAG 是最自然的文件触发场景（文件变更 → 重新索引）；其他场景让用户在 `config.watch_path` 显式指定。

5. **触发器配置存储**：推荐 **DB 表 `tb_trigger` 热更新**（vs 配置文件）。**理由**：热更新不需要重启；API 友好（CRUD）；与现有 `tb_dispatch_record` 持久化风格一致。

6. **执行隔离**：推荐 **同进程 + per-trigger `Semaphore(1)` 串行化**（vs 独立 worker 进程）。**理由**：第一期目标是最小可行，避免引入 Celery/RQ；同进程共享 event loop 与现有 dispatch_stream 调用最简单；第二期可拆 worker。

---

## 16. 与搁置的团队协作方案的关系

- 团队方案 `2026-07-19-team-collaboration-design.md` 标记为 ⏸️ SHELVED，**本方案不依赖它**。
- 本方案 `target_agent_ids` 直接传 agent_id 列表，团队方案解冻后只需在 `tb_trigger` 加一列 `target_team_id`（与 `target_agent_ids` 互斥，二选一），**无破坏性改动**。
- 触发器写 `tb_dispatch_record.trigger_id` 列；团队方案写 `team_id` 列；两列并存无冲突。
- 触发器调 `MultiAgentService.dispatch_stream`，团队方案扩展同方法加 `team_id` 参数；两者扩展点不同，可叠加。
