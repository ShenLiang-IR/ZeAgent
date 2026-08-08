"""三层可见性迁移：给 tb_agent / tb_agent_team 加 visibility 列并迁移存量数据。

幂等：列已存在则跳过 ALTER；存量行 visibility IS NULL → 按 is_public 映射
（tb_agent: is_public=1→public，否则 workspace，保留原空间共享行为；tb_agent_team→workspace）。
新建对象由应用层设默认 private（不经过本迁移）。
"""
from loguru import logger
from sqlalchemy import text


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE LOWER(table_name) = LOWER(:t) AND LOWER(column_name) = LOWER(:c)"
    ), {"t": table, "c": column})
    return (result.scalar() or 0) > 0


def migrate_visibility() -> None:
    """执行可见性迁移（幂等，可在启动时安全调用）。"""
    from .sessions import get_config_engine
    engine = get_config_engine()
    try:
        with engine.begin() as conn:
            # 1. 加列（幂等）
            if not _column_exists(conn, "tb_agent", "visibility"):
                conn.execute(text("ALTER TABLE tb_agent ADD COLUMN visibility VARCHAR(20) NULL"))
                logger.info("[migrate_visibility] tb_agent.visibility 列已添加")
            if not _column_exists(conn, "tb_agent_team", "visibility"):
                conn.execute(text("ALTER TABLE tb_agent_team ADD COLUMN visibility VARCHAR(20) NULL"))
                logger.info("[migrate_visibility] tb_agent_team.visibility 列已添加")
            if not _column_exists(conn, "tb_agent_team", "creator_id"):
                conn.execute(text("ALTER TABLE tb_agent_team ADD COLUMN creator_id BIGINT NULL"))
                logger.info("[migrate_visibility] tb_agent_team.creator_id 列已添加")

            # 2. 迁移存量数据（仅 visibility IS NULL 的行，幂等）
            r1 = conn.execute(text(
                "UPDATE tb_agent SET visibility = CASE WHEN is_public = 1 THEN 'public' ELSE 'workspace' END "
                "WHERE visibility IS NULL"
            ))
            if r1.rowcount:
                logger.info(f"[migrate_visibility] tb_agent 迁移 {r1.rowcount} 行")
            r2 = conn.execute(text(
                "UPDATE tb_agent_team SET visibility = 'workspace' WHERE visibility IS NULL"
            ))
            if r2.rowcount:
                logger.info(f"[migrate_visibility] tb_agent_team 迁移 {r2.rowcount} 行")
        logger.info("[migrate_visibility] 完成")
    except Exception as e:
        # 迁移失败不阻塞启动（查询层对 NULL 有回退逻辑）
        logger.warning(f"[migrate_visibility] 迁移跳过/失败: {e}")


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    migrate_visibility()
