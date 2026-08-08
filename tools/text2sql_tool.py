"""Text2SQL 工具 — 让 agent 通过自然语言查库（复用 db_skills.text2sql）。

挂载方式：agent 配置 tools=["text2sql_query"]，collect_subagent_tools_async 按名从
tool_registry 查找挂载。模块顶部只 import 轻量依赖，TextSQL/DB 经 factory 惰性初始化。
"""
import asyncio
from loguru import logger
from langchain_core.tools import tool


def _get_tsql():
    """惰性获取 TextSQL 单例（委托 factory）。"""
    from db_skills.text2sql.factory import get_textsql
    return get_textsql()


def _format_result(r) -> str:
    """把 TextSQL.ask 的 SQLResult 格式化为 markdown（SQL + 数据表 + 错误）。"""
    parts = []
    sql = getattr(r, "sql", "") or ""
    if sql:
        parts.append(f"SQL:\n```sql\n{sql}\n```")
    error = getattr(r, "error", "") or ""
    if error:
        parts.append(f"错误: {error}")
    data = getattr(r, "data", None) or []
    if data:
        cols = list(data[0].keys())
        lines = ["| " + " | ".join(cols) + " |",
                 "| " + " | ".join(["---"] * len(cols)) + " |"]
        for row in data:
            lines.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
        parts.append(f"数据（{len(data)} 行）:\n" + "\n".join(lines))
    elif getattr(r, "success", False) and not error:
        parts.append("查询成功，无数据返回。")
    return "\n\n".join(parts) if parts else "无结果"


@tool
async def text2sql_query(question: str, max_rows: int = 20) -> str:
    """用自然语言查询数据库（Text2SQL）。输入用户的问题（如"列出所有 agent 的名称和状态"），
    返回生成的 SQL 与查询结果（markdown 表）。max_rows 限制返回行数（默认 20，最大 500）。
    """
    max_rows = max(1, min(int(max_rows), 500))
    try:
        tsql = _get_tsql()
        r = await asyncio.to_thread(tsql.ask, question, max_rows)
        return _format_result(r)
    except Exception as e:
        logger.warning(f"[text2sql_query] failed: {e}")
        return f"查询失败: {e}"
