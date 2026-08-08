"""触发器子系统 schema 迁移：建新表 + 给 tb_dispatch_record 加 trigger_id 列。

幂等设计：
- 新表用 Base.metadata.create_all(checkfirst=True)，已存在则跳过
- 加列用 sqlalchemy.inspect 检查列是否存在，不存在才 ALTER TABLE

跨平台：MySQL 5.7+ / SQLite 3.x 通用（用 SQLAlchemy 抽象，不手写 SQL）

运行：python scripts/migration/migrate_trigger_schema.py（项目根执行）
"""
import sys
from pathlib import Path

# 项目根 = 本脚本上三级目录（脚本位于 scripts/migration/ 下）
agent_dir = Path(__file__).resolve().parent.parent.parent
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

from loguru import logger
from sqlalchemy import inspect, text
from infrastructure.database.base import Base
from infrastructure.database.engines import get_config_engine

# 注册 metadata（import 模型类即可）
import infrastructure.database.models.trigger  # noqa: F401
import infrastructure.database.models.dispatch_record  # noqa: F401
from infrastructure.database.models.trigger import Trigger, TriggerLog


def migrate():
    engine = get_config_engine()
    inspector = inspect(engine)

    # ──── 1. 建 tb_trigger + tb_trigger_log 新表（如果不存在） ────
    logger.info("[Migrate] 建 tb_trigger / tb_trigger_log 表（如果不存在）...")
    Base.metadata.create_all(
        engine,
        tables=[Trigger.__table__, TriggerLog.__table__],
        checkfirst=True,
    )
    logger.info("[Migrate] 新表检查完成")

    # ──── 2. 给 tb_dispatch_record 加 trigger_id 列（如果不存在） ────
    table_name = "tb_dispatch_record"
    if table_name not in inspector.get_table_names():
        logger.warning(f"[Migrate] 表 {table_name} 不存在，跳过 ALTER（应先建表）")
        return

    existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
    if "trigger_id" in existing_cols:
        logger.info(f"[Migrate] {table_name}.trigger_id 已存在，跳过 ALTER")
    else:
        logger.info(f"[Migrate] 给 {table_name} 加 trigger_id 列...")
        # 跨平台 SQL：MySQL 8.0+ 支持 IF NOT EXISTS，但 5.7 不支持；
        # 已通过 inspect 检查，直接 ALTER
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE tb_dispatch_record "
                "ADD COLUMN trigger_id VARCHAR(64) NULL COMMENT '触发器 dispatch 时记录；与 team_id 列并行，互不依赖'"
            ))
            conn.commit()
        logger.info(f"[Migrate] {table_name}.trigger_id 加列完成")

    # ──── 3. 验证：列出现在 inspect 结果中 ────
    # 重新 inspect（engine 可能缓存）
    inspector2 = inspect(engine)
    cols2 = {c["name"] for c in inspector2.get_columns(table_name)}
    assert "trigger_id" in cols2, f"迁移后 {table_name} 应含 trigger_id，实际 {cols2}"
    logger.info(f"[Migrate] 验证通过：{table_name} 字段含 trigger_id")

    # 检查新表存在
    assert "tb_trigger" in inspector2.get_table_names(), "tb_trigger 应已建"
    assert "tb_trigger_log" in inspector2.get_table_names(), "tb_trigger_log 应已建"
    logger.info("[Migrate] 验证通过：tb_trigger / tb_trigger_log 已建")

    logger.info("[Migrate] 迁移完成")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("=" * 60)
    print("触发器子系统 schema 迁移")
    print("=" * 60)
    migrate()
    print("=" * 60)
    print("完成")
    print("=" * 60)
