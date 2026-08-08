"""Alembic 迁移环境。

设计目标：
- 与项目 SQLAlchemy Base.metadata 集成，支持 autogenerate
- 从项目 utils/config 拿 DB URL（与运行时一致）
- 自动 import 所有 model 模块让 autogenerate 能检测到

使用：
- 生成迁移：alembic revision --autogenerate -m "message"
- 应用迁移：alembic upgrade head
- 回滚：alembic downgrade -1
- 查看状态：alembic current
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ─── 集成项目 Base.metadata ───
# 导入项目的 Base 和所有 model 模块，让 autogenerate 能检测到表结构
import sys
from pathlib import Path

# 把项目根加入 sys.path（alembic 命令在项目根跑）
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 走 service 层入口打破 utils ↔ repositories 循环 import
# （参考 docs/specs/2026-07-19-audit-log-design.md 循环 import 修复说明）
try:
    from services.agent_crud_service import AgentCrudService  # noqa: F401
except Exception:
    pass  # service 层加载失败不阻塞 alembic（可单独 import Base）

from infrastructure.database.base import Base  # noqa: E402

# 导入所有 model 让 Base.metadata 包含全部表
import infrastructure.database.models.agent  # noqa: F401, E402
import infrastructure.database.models.agent_team  # noqa: F401, E402
import infrastructure.database.models.agent_version  # noqa: F401, E402
import infrastructure.database.models.api  # noqa: F401, E402
import infrastructure.database.models.audit  # noqa: F401, E402
import infrastructure.database.models.chat  # noqa: F401, E402
import infrastructure.database.models.config  # noqa: F401, E402
import infrastructure.database.models.dashboard  # noqa: F401, E402
import infrastructure.database.models.dispatch_record  # noqa: F401, E402
import infrastructure.database.models.eval  # noqa: F401, E402
import infrastructure.database.models.event_subscription  # noqa: F401, E402
import infrastructure.database.models.kb_version  # noqa: F401, E402
import infrastructure.database.models.knowledge  # noqa: F401, E402
import infrastructure.database.models.mcp  # noqa: F401, E402
import infrastructure.database.models.mode  # noqa: F401, E402
import infrastructure.database.models.model_config  # noqa: F401, E402
import infrastructure.database.models.plugin  # noqa: F401, E402
import infrastructure.database.models.prompt_template  # noqa: F401, E402
import infrastructure.database.models.rag_knowledge_base  # noqa: F401, E402
import infrastructure.database.models.rbac  # noqa: F401, E402
import infrastructure.database.models.rls  # noqa: F401, E402
import infrastructure.database.models.security  # noqa: F401, E402
import infrastructure.database.models.skill  # noqa: F401, E402
import infrastructure.database.models.sys_model_res_mgmt  # noqa: F401, E402
import infrastructure.database.models.trigger  # noqa: F401, E402
import infrastructure.database.models.trigger_leader  # noqa: F401, E402
import infrastructure.database.models.usage  # noqa: F401, E402
import infrastructure.database.models.user  # noqa: F401, E402
import infrastructure.database.models.workspace  # noqa: F401, E402
import infrastructure.database.models.writing  # noqa: F401, E402

target_metadata = Base.metadata

# ─── 从项目 utils/config 拿 DB URL（与运行时一致） ───
def _get_db_url() -> str:
    """从项目 utils.config 拿 config DB URL，与运行时一致。"""
    try:
        from utils.config import get_database_config
        from infrastructure.database.engines import build_database_url
        cfg = get_database_config("config")
        if cfg:
            return build_database_url(cfg)
    except Exception:
        pass
    # fallback：从环境变量
    import os
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    host = os.getenv("MYSQL_HOST", "localhost")
    port = os.getenv("MYSQL_PORT", "3306")
    database = os.getenv("MYSQL_DATABASE", "agent")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"

# 覆盖 alembic.ini 里的 sqlalchemy.url
config.set_main_option("sqlalchemy.url", _get_db_url())


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本（不连 DB）。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连 DB 执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # 比较类型时考虑 server_default
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
