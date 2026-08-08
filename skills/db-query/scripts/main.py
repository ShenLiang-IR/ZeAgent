#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据库查询工具 — 执行 SQL 查询返回 JSON 结果。

只读模式：仅允许 SELECT 语句，自动添加 LIMIT 保护。
"""
import argparse
import json
import sys
import re

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="数据库查询工具")
    parser.add_argument("--sql", required=True, help="SQL 查询语句")
    parser.add_argument("--db", default="config", help="数据库名称")
    parser.add_argument("--limit", type=int, default=100, help="返回行数限制")
    parser.add_argument("--output", default="", help="输出文件路径")
    args = parser.parse_args()

    sql = args.sql.strip()
    if not sql.upper().startswith("SELECT"):
        print(json.dumps({"error": "仅支持 SELECT 查询"}, ensure_ascii=False))
        sys.exit(1)

    # 自动添加 LIMIT（如果没有）
    if not re.search(r"\blimit\s+\d+", sql, re.IGNORECASE):
        sql = sql.rstrip(";") + f" LIMIT {args.limit}"

    try:
        from infrastructure.database.sessions import get_database_config, get_config_engine
        from sqlalchemy import create_engine, text

        db_config = get_database_config(args.db)
        db_type = (db_config.get("type") or db_config.get("dbtype", "mysql")).lower()
        user = db_config.get("user") or db_config.get("username", "")
        password = db_config.get("password") or db_config.get("pwd", "")
        host = db_config.get("host", "127.0.0.1")
        port = db_config.get("port", 3306)
        database = db_config.get("database", "")

        if db_type in ("mysql", "doris"):
            from urllib.parse import quote_plus
            url = f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{database}?charset=utf8mb4"
        elif db_type in ("postgresql", "postgres"):
            from urllib.parse import quote_plus
            url = f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{database}"
        else:
            print(json.dumps({"error": f"不支持的数据库类型: {db_type}"}, ensure_ascii=False))
            sys.exit(1)

        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]

            # 序列化 datetime/date
            for row in rows:
                for k, v in row.items():
                    if hasattr(v, "isoformat"):
                        row[k] = v.isoformat()
                    elif isinstance(v, bytes):
                        row[k] = v.decode("utf-8", errors="replace")

        output = json.dumps({"columns": columns, "rows": rows, "count": len(rows)}, ensure_ascii=False, indent=2, default=str)
        if args.output:
            from pathlib import Path
            Path(args.output).write_text(output, encoding="utf-8")
            print(json.dumps({"success": True, "count": len(rows), "output_file": args.output}, ensure_ascii=False))
        else:
            print(output)

    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
