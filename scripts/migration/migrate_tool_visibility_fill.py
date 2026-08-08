"""存量工具对象 visibility NULL → 显式化迁移。

背景：三层可见性改造给 tb_mcp/tb_skill/tb_rk_api 加了 visibility 列，存量行
visibility=NULL，代码层按"回退同空间可见"兜底。本脚本把 NULL 行显式置为
workspace（与回退语义一致），让数据自解释、便于审计。

tb_agent 的 NULL 回退逻辑含 is_public==1，故用 is_public_to_visibility 反推：
- is_public==1 → public
- is_public==0/NULL → workspace

幂等：只 UPDATE visibility IS NULL 的行；已显式赋值的行不动。
运行：python scripts/migration/migrate_tool_visibility_fill.py（项目根执行）
"""
import sys
from pathlib import Path

# 项目根 = 本脚本上三级目录（脚本位于 scripts/migration/ 下）
agent_dir = Path(__file__).resolve().parent.parent.parent
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

from loguru import logger
from sqlalchemy import text
from infrastructure.database.engines import get_config_engine


def migrate():
    engine = get_config_engine()
    with engine.connect() as conn:
        # ── 工具类对象：NULL → workspace ──
        for table in ["tb_mcp", "tb_skill", "tb_rk_api"]:
            result = conn.execute(text(
                f"UPDATE {table} SET visibility = 'workspace' "
                f"WHERE visibility IS NULL AND del_flag = '0'"
            ))
            conn.commit()
            logger.info(f"[Fill] {table}: {result.rowcount} 行 NULL → workspace")

        # ── tb_agent：NULL → is_public==1 ? 'public' : 'workspace' ──
        # 分两步 UPDATE，语义清晰
        r1 = conn.execute(text(
            "UPDATE tb_agent SET visibility = 'public' "
            "WHERE visibility IS NULL AND del_flag = '0' AND is_public = 1"
        ))
        r2 = conn.execute(text(
            "UPDATE tb_agent SET visibility = 'workspace' "
            "WHERE visibility IS NULL AND del_flag = '0' AND (is_public IS NULL OR is_public = 0)"
        ))
        conn.commit()
        logger.info(f"[Fill] tb_agent: {r1.rowcount} 行 → public, {r2.rowcount} 行 → workspace")

    # ── 验证：无 NULL 残留 ──
    with engine.connect() as conn:
        for table in ["tb_mcp", "tb_skill", "tb_rk_api", "tb_agent"]:
            cnt = conn.execute(text(
                f"SELECT COUNT(*) FROM {table} WHERE visibility IS NULL AND del_flag = '0'"
            )).scalar()
            assert cnt == 0, f"{table} 仍有 {cnt} 行 visibility=NULL"
            logger.info(f"[Fill] 验证通过：{table} 无 NULL 残留")
    logger.info("[Fill] 迁移完成")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("=" * 60)
    print("存量工具对象 visibility NULL 显式化迁移")
    print("=" * 60)
    migrate()
    print("=" * 60)
    print("完成")
    print("=" * 60)
