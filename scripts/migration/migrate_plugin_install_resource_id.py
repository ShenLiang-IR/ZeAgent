"""插件安装表 linked_resource_id 列迁移。

给 tb_plugin_install 加 linked_resource_id 列，统一记录安装时生成的运行时资源 ID
（MCP 的 mcp_id / Skill 的 skill_id / Tool 的 tool_name）。
保留 linked_mcp_id 向后兼容。

幂等设计：用 sqlalchemy.inspect 检查列是否存在，不存在才 ALTER TABLE。

运行：python scripts/migration/migrate_plugin_install_resource_id.py（项目根执行）
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

TABLE = "tb_plugin_install"
COLUMN_NAME = "linked_resource_id"
DDL = (
    "ADD COLUMN linked_resource_id VARCHAR(128) NULL "
    "COMMENT '统一资源ID：mcp_id / skill_id / tool_name'"
)


def migrate():
    engine = get_config_engine()
    inspector = inspect(engine)

    if TABLE not in inspector.get_table_names():
        logger.warning(f"[Migrate] 表 {TABLE} 不存在，跳过（应先建表）")
        return

    existing_cols = {c["name"] for c in inspector.get_columns(TABLE)}
    if COLUMN_NAME in existing_cols:
        logger.info(f"[Migrate] {TABLE}.{COLUMN_NAME} 已存在，跳过")
        return

    logger.info(f"[Migrate] 给 {TABLE} 加 {COLUMN_NAME} 列...")
    with engine.connect() as conn:
        conn.execute(text(f"ALTER TABLE {TABLE} {DDL}"))
        conn.commit()
    logger.info(f"[Migrate] {TABLE}.{COLUMN_NAME} 加列完成")

    # 验证
    inspector2 = inspect(engine)
    cols = {c["name"] for c in inspector2.get_columns(TABLE)}
    assert COLUMN_NAME in cols, f"迁移后 {TABLE} 应含 {COLUMN_NAME}，实际 {cols}"
    logger.info("[Migrate] 验证通过")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("=" * 60)
    print("插件安装表 linked_resource_id 列迁移")
    print("=" * 60)
    migrate()
    print("=" * 60)
    print("完成")
    print("=" * 60)
