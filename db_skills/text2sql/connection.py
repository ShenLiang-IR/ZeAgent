"""Database connection wrapper using SQLAlchemy.

适配项目：MySQL 连接加 charset=utf8mb4 避免中文编码问题。
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, Inspector


class Database:
    """Thin wrapper around a SQLAlchemy engine."""

    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        # MySQL 连接加 charset=utf8mb4 避免中文编码问题
        if "mysql" in connection_string and "charset" not in connection_string:
            sep = "?" if "?" not in connection_string else "&"
            connection_string = f"{connection_string}{sep}charset=utf8mb4"
        engine_kwargs = {}
        # MySQL 连接池配置：与主应用 engines.py 保持一致，防止 stale 连接导致 Access denied
        if "mysql" in connection_string:
            engine_kwargs["connect_args"] = {"ssl_disabled": True}
            engine_kwargs["pool_pre_ping"] = True
            engine_kwargs["pool_recycle"] = 3600
        self.engine: Engine = create_engine(connection_string, **engine_kwargs)

    def execute(self, sql: str, params: dict | None = None) -> list[dict]:
        """Execute SQL and return rows as list of dicts."""
        with self.engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            if result.returns_rows:
                columns = list(result.keys())
                return [dict(zip(columns, row)) for row in result.fetchall()]
            return []

    def get_inspector(self) -> Inspector:
        """Return a SQLAlchemy Inspector for schema introspection."""
        return inspect(self.engine)

    @property
    def dialect(self) -> str:
        """Return the database dialect name (e.g. 'sqlite', 'postgresql')."""
        return self.engine.dialect.name

    def test_connection(self) -> bool:
        """Verify the connection works."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def get_schema_summary(self) -> dict:
        """Return structured schema summary using SQLAlchemy Inspector.

        Returns a dict of tables, each with columns (name, type, nullable,
        comment/description), primary keys, and foreign keys.
        """
        inspector = self.get_inspector()
        schema = {}

        for table_name in inspector.get_table_names():
            columns = []
            for col in inspector.get_columns(table_name):
                columns.append({
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "comment": col.get("comment") or "",
                })

            pk = inspector.get_pk_constraint(table_name)
            pk_columns = pk.get("constrained_columns", []) if pk else []

            fks = []
            for fk in inspector.get_foreign_keys(table_name):
                fks.append({
                    "constrained_columns": fk.get("constrained_columns", []),
                    "referred_table": fk.get("referred_table", ""),
                    "referred_columns": fk.get("referred_columns", []),
                })

            table_comment = ""
            try:
                tc = inspector.get_table_comment(table_name)
                table_comment = tc.get("text") or "" if tc else ""
            except (NotImplementedError, Exception):
                pass

            schema[table_name] = {
                "columns": columns,
                "primary_keys": pk_columns,
                "foreign_keys": fks,
                "comment": table_comment,
            }

        return schema
