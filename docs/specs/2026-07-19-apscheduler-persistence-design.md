# APScheduler 持久化设计 — SQLAlchemyJobStore（P0）

> 日期：2026-07-19
> 状态：📝 DESIGN（待评审）
> 上下文：承接 `docs/specs/2026-07-19-trigger-registry-design.md` 触发器扩展完成后补齐高可用短板

## 1. 背景

当前 `CronTrigger` 用 `MemoryJobStore`——进程重启时**未执行的 cron tick 丢失**（`misfire_grace_time=60` 只能补 60 秒内）。多 worker 部署时也无法共享 job 状态，每个 worker 都会触发同一 job。

## 2. 目标

- **G1**：CronTrigger 切换到 `SQLAlchemyJobStore`，job 持久化到 MySQL
- **G2**：进程重启后未执行的 job 自动恢复（按 misfire_grace_time 补跑或跳过）
- **G3**：多 worker 部署时同一 job 只被一个 worker 执行（基于 DB 行锁）
- **G4**：向下兼容——`tb_trigger` 配置不动，仅改 `CronTrigger` 内部实现
- **G5**：无新增依赖（apscheduler 已支持 SQLAlchemyJobStore）

## 3. 数据模型

### 复用现有 `get_config_engine`

`SQLAlchemyJobStore` 会自动建表 `tb_apscheduler_job`（schema 由 apscheduler 管理，不需要我们写 ORM）。

> 注意：这表是 APScheduler 自己管，不进我们的 Base.metadata。建表在 CronTrigger.get_scheduler() 第一次启动时自动完成。

## 4. 服务层改动

### `services/trigger/cron_trigger.py` 改动

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from infrastructure.database.engines import get_config_engine

class CronTrigger(ITrigger):
    _scheduler: AsyncIOScheduler = None

    @classmethod
    def get_scheduler(cls) -> AsyncIOScheduler:
        if cls._scheduler is None or not cls._scheduler.running:
            engine = get_config_engine()
            cls._scheduler = AsyncIOScheduler(
                jobstores={
                    'default': SQLAlchemyJobStore(engine=engine)
                },
                # 多 worker 时基于 DB 行锁，同一 job 只被一个 worker 执行
                job_defaults={
                    'coalesce': True,      # 多次错过合并为 1 次
                    'max_instances': 1,    # 同一 job 不并发
                    'misfire_grace_time': 60,
                },
            )
            cls._scheduler.start()
        return cls._scheduler
```

**关键变化**：
- 之前：`AsyncIOScheduler()` 用默认 MemoryJobStore
- 之后：显式配置 `SQLAlchemyJobStore(engine=get_config_engine())`

**多 worker 共享**：所有 worker 连同一 MySQL，APScheduler 用 `SELECT ... FOR UPDATE` 锁 job 行，保证同一 job 同时只被一个 worker 执行（`coalesce=True` + `max_instances=1`）。

### 其他文件零改动

- `services/trigger/base.py`：不动
- `services/trigger/webhook_trigger.py`：不动（start/stop 是 noop）
- `services/trigger/file_watch_trigger.py`：不动（用 asyncio.Task，不进 scheduler）
- `services/trigger/registry.py`：不动（load_from_db 逻辑不变）
- `server.py` lifespan：不动

## 5. 测试

| 测试 | 验证 |
|---|---|
| `test_cron_jobstore_is_sqlalchemy` | get_scheduler().jobstores['default'] 是 SQLAlchemyJobStore 实例 |
| `test_cron_job_persists_after_restart` | start() 后 stop() 再 start()，job 仍存在（jobstore 持久化） |
| `test_cron_misfire_recovery` | 模拟错过 30 秒的 tick，重启后应补跑（misfire_grace_time 内） |
| `test_cron_misfire_skip_after_grace` | 模拟错过 120 秒的 tick，重启后应跳过（超 grace_time） |
| `test_cron_multi_worker_no_duplicate` | 模拟两个 scheduler 实例连同一 DB，同一 job 不重复执行 |

**测试隔离**：每个测试用独立的 jobstore 表名或 `trigger_id`，避免跨测试污染。conftest 的 `_reset_cron_scheduler` fixture 扩展为清空 jobstore。

## 6. 文件变更

| 文件 | 类型 |
|---|---|
| `services/trigger/cron_trigger.py` | 改：get_scheduler 用 SQLAlchemyJobStore |
| `test/conftest.py` | 改：_reset_cron_scheduler fixture 清空 jobstore |
| `test/test_cron_persistence.py` | 新建：持久化测试 |
| `docs/specs/2026-07-19-trigger-registry-design.md` | 改：备注 §6.2 已升级为 SQLAlchemyJobStore |

## 7. 关键设计决策

1. **jobstore 共享 engine**：用项目 `get_config_engine()`，避免新建连接池。**理由**：连接池统一管理。
2. **misfire_grace_time=60 不变**：保持现状，错过 60 秒内补跑，超出跳过。**风险**：长时间宕机会丢任务。**缓解**：第二期加告警（错过数 > 阈值告警）。
3. **多 worker 行锁**：APScheduler 用 `SELECT FOR UPDATE` 保证唯一执行。**注意**：MySQL 默认 `innodb_lock_wait_timeout=50s`，长任务可能超时——`max_instances=1` 已保证单实例。
4. **不引入 Redis JobStore**：第一期不引入 Redis 依赖，MySQL 够用。**第二期**高并发场景再考虑 RedisJobStore。
5. **FileWatchTrigger 不持久化**：文件监听是 asyncio Task，进程重启必然重启监听（配置在 tb_trigger 不丢）。**理由**：watchfiles 无状态，无需持久化。

## 8. 兼容性影响

- `tb_trigger` 配置不动，触发器 CRUD API 不动
- `CronTrigger._scheduler` 单例从 MemoryJobStore 升级为 SQLAlchemyJobStore——首次启动时自动建 `tb_apscheduler_job` 表（checkfirst）
- 现有 cron 测试（4 个）应继续通过，仅需调整 conftest fixture 清空 jobstore
- 多 worker 部署时**必须**共享同一 MySQL，否则各自独立 jobstore 会重复触发
