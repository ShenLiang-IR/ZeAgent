"""seed_database_query_agent.py — 把"数据库查询" agent upsert 到 tb_agent。

幂等：按 agent_name 查找，存在则更新，不存在则新建。
挂载工具 text2sql_query（tool_registry 注册名，collect_subagent_tools_async 按名挂载）。
需 config DB（MySQL）可用；不可用时跳过（非致命）。

用法：python command/seed_database_query_agent.py
"""
import sys
from pathlib import Path

agent_dir = Path(__file__).resolve().parents[1]
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

from loguru import logger

AGENT_NAME = "数据库查询"
DESCRIPTION = "用自然语言查询数据库的助手（Text2SQL），生成 SQL 并返回结果"
SYSTEM_PROMPT = (
    "你是一个数据库查询助手。用户会用自然语言提问，请调用 text2sql_query 工具查询数据库，"
    "然后把 SQL 和结果用清晰的表格或文字回复给用户。如果查询失败或结果为空，如实告知。"
    "复杂问题可分步查询。"
)
TOOLS = ["text2sql_query"]
DEFAULT_WORKSPACE_ID = 1


def main() -> int:
    try:
        from infrastructure.database.repositories.agent_repository import AgentRepository
        repo = AgentRepository()
    except Exception as e:
        logger.error(f"seed agent 初始化仓储失败（DB 不可用？）: {e}")
        return 1
    try:
        existing = repo.get_by_name(AGENT_NAME)
        pk = existing["pr_key_id"] if existing else 0  # 0 = 新建哨兵（autoincrement）
        ok = repo.save_agent(
            pr_key_id=pk,
            agent_name=AGENT_NAME,
            system_prompt=SYSTEM_PROMPT,
            tools=TOOLS,
            agent_description=DESCRIPTION,
            model_id=None,
            enabled=True,
        )
        if not ok:
            logger.error(f"seed agent 失败: {AGENT_NAME}")
            return 1
        # save_agent 不设 workspace_id/is_public，补一下（默认工作空间 + 公开可见）
        seeded = repo.get_by_name(AGENT_NAME)
        if seeded:
            repo.update(seeded["pr_key_id"], workspace_id=DEFAULT_WORKSPACE_ID, is_public=1)
        logger.info(f"seed agent 完成: {AGENT_NAME} (tools={TOOLS}, workspace={DEFAULT_WORKSPACE_ID})")
        return 0
    except Exception as e:
        logger.error(f"seed agent 异常（config DB 不可用？）: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
