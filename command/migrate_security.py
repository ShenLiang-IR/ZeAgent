"""创建 tb_sensitive_word 表（幂等）。

运行: python command/migrate_security.py
"""
import sys
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from loguru import logger
from infrastructure.database.base import Base
from infrastructure.database.models.security import SensitiveWord
from infrastructure.database.engines import get_config_engine


def migrate():
    engine = get_config_engine()
    Base.metadata.create_all(engine, tables=[SensitiveWord.__table__], checkfirst=True)
    logger.info("tb_sensitive_word 表已创建（幂等）")


if __name__ == "__main__":
    migrate()
