from .base_extractor import (
    BaseMetadataExtractor,
)
class PostgresMetadataExtractor(BaseMetadataExtractor):
    GET_TABLES_SQL = """
        SELECT c.relname AS table_name, obj_description(c.oid) AS table_comment
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relkind = 'r'
          AND c.relname NOT LIKE 'pg_%%' AND c.relname NOT LIKE 'sql_%%'
        ORDER BY c.relname;
    """
    GET_COLUMNS_SQL = """
        SELECT a.attname AS column_name, t.typname AS data_type,
            NOT a.attnotnull AS is_nullable,
            col_description(a.attrelid, a.attnum) AS column_comment,
            pg_get_expr(d.adbin, d.adrelid) AS default_value
        FROM pg_attribute a
        JOIN pg_type t ON t.oid = a.atttypid
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = (%s || '.' || %s)::regclass
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum;
    """
