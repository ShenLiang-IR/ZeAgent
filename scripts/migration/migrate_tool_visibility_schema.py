"""工具类对象（MCP/Skill/外部工具）三层可见性 schema 迁移。

给 tb_mcp / tb_skill / tb_rk_api 三张表补齐与 tb_agent 对齐的可见性字段：
- is_public   INT DEFAULT 0   （旧字段，由 visibility 同步；向后兼容）
- visibility  VARCHAR(20) NULL （新 source of truth：private/workspace/public）
- creator_id  BIGINT NULL      （创建者用户ID，private 隔离用）

幂等设计：用 sqlalchemy.inspect 检查列是否存在，不存在才 ALTER TABLE。
跨平台：MySQL 5.7+ / SQLite 3.x 通用（用 SQLAlchemy 抽象 + 标准 ALTER）。

运行：python scripts/migration/migrate_tool_visibility_schema.py（项目根执行）
"""
import sys
from pathlib import Path

# 项目根 = 本脚本上三级目录（脚本位于 scripts/migration/ 下）
agent_dir = Path(__file__).resolve().parent.parent.parent
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

from loguru import logger
from sqlalchemy import inspect, text
from infrastructure.database.engines import get_config_engine

# 需迁移的表 → 待加列定义
# (列名, DDL 片段)
COLUMNS_TO_ADD = [
    (
        "is_public",
        "ADD COLUMN is_public INT DEFAULT 0 COMMENT '0=私有 1=公开（旧字段，由 visibility 同步）'",
    ),
    (
        "visibility",
        "ADD COLUMN visibility VARCHAR(20) NULL COMMENT '可见性 private/workspace/public（新 source of truth）'",
    ),
    (
        "creator_id",
        "ADD COLUMN creator_id BIGINT NULL COMMENT '创建者用户ID'",
    ),
]

TABLES = ["tb_mcp", "tb_skill", "tb_rk_api"]


def migrate():
    engine = get_config_engine()
    inspector = inspect(engine)

    for table_name in TABLES:
        if table_name not in inspector.get_table_names():
            logger.warning(f"[Migrate] 表 {table_name} 不存在，跳过（应先建表）")
            continue

        existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
        with engine.connect() as conn:
            for col_name, ddl_fragment in COLUMNS_TO_ADD:
                if col_name in existing_cols:
                    logger.info(f"[Migrate] {table_name}.{col_name} 已存在，跳过")
                    continue
                logger.info(f"[Migrate] 给 {table_name} 加 {col_name} 列...")
                conn.execute(text(f"ALTER TABLE {table_name} {ddl_fragment}"))
                conn.commit()
                logger.info(f"[Migrate] {table_name}.{col_name} 加列完成")

    # ─── 验证 ───
    inspector2 = inspect(engine)
    for table_name in TABLES:
        if table_name not in inspector2.get_table_names():
            continue
        cols = {c["name"] for c in inspector2.get_columns(table_name)}
        for col_name, _ in COLUMNS_TO_ADD:
            assert col_name in cols, f"迁移后 {table_name} 应含 {col_name}，实际 {cols}"
    logger.info("[Migrate] 验证通过：三张表均含 is_public/visibility/creator_id")
    logger.info("[Migrate] 迁移完成")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("=" * 60)
    print("工具类对象三层可见性 schema 迁移")
    print("=" * 60)
    migrate()
    print("=" * 60)
    print("完成")
    print("=" * 60)
