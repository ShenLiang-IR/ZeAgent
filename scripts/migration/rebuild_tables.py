"""重建数据库表 — pr_key_id 从 String(32) 改为 BigInteger autoincrement

运行：python scripts/migration/rebuild_tables.py（项目根执行）
"""
import sys
from pathlib import Path

# 项目根 = 本脚本上三级目录（脚本位于 scripts/migration/ 下）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from infrastructure.database.base import Base
from infrastructure.database.engines import get_config_engine
from sqlalchemy import text

# Import all models
from infrastructure.database.models.skill import Skill
from infrastructure.database.models.agent import Agent, AgentRelation
from infrastructure.database.models.mcp import Mcp, McpIntfc
from infrastructure.database.models.api import RkApiNode, RkApi, RkApiParam
from infrastructure.database.models.mode import Mode
from infrastructure.database.models.config import SystemConfig
from infrastructure.database.models.rls import RLSSysRule

engine = get_config_engine()

tables_to_drop = [
    'tb_agent_relation',
    'tb_skill',
    'tb_agent',
    'tb_mcp',
    'tb_mcp_intfc',
    'tb_rk_api_param',
    'tb_rk_api',
    'tb_rk_api_node',
    'tb_mode',
]

with engine.connect() as conn:
    for table in tables_to_drop:
        conn.execute(text(f"DROP TABLE IF EXISTS `{table}`"))
        print(f"Dropped: {table}")
    conn.commit()

Base.metadata.create_all(engine, tables=[
    Agent.__table__,
    AgentRelation.__table__,
    Skill.__table__,
    Mcp.__table__,
    McpIntfc.__table__,
    RkApiNode.__table__,
    RkApi.__table__,
    RkApiParam.__table__,
    Mode.__table__,
])
print("All tables recreated")
print(f"Skill.pr_key_id type: {Skill.__table__.c.pr_key_id.type}")
