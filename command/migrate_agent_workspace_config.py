"""添加 agent_config 和 workspace config 字段 — 支持工作空间级/Agent级配置覆盖。

运行: python command/migrate_agent_workspace_config.py
幂等: 字段不存在时加列，已存在时跳过。
"""
import sys
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from loguru import logger
from sqlalchemy import text
from infrastructure.database.sessions import get_config_session


def migrate():
    with get_config_session() as session:
        # 1. tb_agent 加 agent_config
        try:
            session.execute(text(
                "ALTER TABLE tb_agent ADD COLUMN agent_config TEXT NULL "
                "COMMENT 'Agent 级执行配置覆盖 (JSON)'"
            ))
            session.commit()
            logger.info("tb_agent.agent_config 已添加")
        except Exception as e:
            session.rollback()
            if "Duplicate column" in str(e) or "already exists" in str(e):
                logger.info("tb_agent.agent_config 已存在，跳过")
            else:
                logger.warning(f"tb_agent.agent_config 添加失败: {e}")

        # 2. tb_workspace 加 config
        try:
            session.execute(text(
                "ALTER TABLE tb_workspace ADD COLUMN config TEXT NULL "
                "COMMENT '工作空间级配置覆盖 (JSON)'"
            ))
            session.commit()
            logger.info("tb_workspace.config 已添加")
        except Exception as e:
            session.rollback()
            if "Duplicate column" in str(e) or "already exists" in str(e):
                logger.info("tb_workspace.config 已存在，跳过")
            else:
                logger.warning(f"tb_workspace.config 添加失败: {e}")


if __name__ == "__main__":
    migrate()
    logger.info("迁移完成")
