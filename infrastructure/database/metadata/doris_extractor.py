from typing import List, Optional
from loguru import logger
import asyncio
from .base_extractor import (
    BaseMetadataExtractor,
    ColumnInfo,
    TableInfo,
)
class DorisMetadataExtractor(BaseMetadataExtractor):
    GET_TABLES_SQL = "SHOW TABLES FROM `{database}`"
    GET_TABLE_COMMENT_SQL = """
        SELECT TABLE_NAME, TABLE_COMMENT
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s
    """
    GET_COLUMNS_SQL = """
        SELECT
            COLUMN_NAME,
            DATA_TYPE,
            IS_NULLABLE,
            COLUMN_COMMENT,
            COLUMN_KEY,
            COLUMN_DEFAULT,
            CHARACTER_MAXIMUM_LENGTH,
            NUMERIC_PRECISION,
            NUMERIC_SCALE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """
    async def _extract_columns_method(self, conn, schema, table):
        try:
            import pymysql
            database = self.db_config.get('database')
            conn_params = {
                'host': self.db_config.get('host', 'localhost'),
                'port': self.db_config.get('port', 9030),
                'database': database,
                'user': self.db_config.get('username') or self.db_config.get('user'),
                'password': self.db_config.get('pwd') or self.db_config.get('password'),
                'charset': 'utf8mb4',
            }
            self._sync_conn = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: pymysql.connect(**conn_params)
            )
            logger.debug(f"[DorisMetadataExtractor] : {database}")
        except ImportError:
            raise ImportError(" pymysql: pip install pymysql")
        except Exception as e:
            logger.error(f"[DorisMetadataExtractor] : {e}")
            raise
    async def disconnect(self) -> None:
        if self._sync_conn:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._sync_conn.close
                )
            except Exception as e:
                logger.warning(f"[DorisMetadataExtractor] : {e}")
            finally:
                self._sync_conn = None
    async def get_all_tables(self) -> List[TableInfo]:
        if not self._sync_conn:
            await self.connect()
        database = self.get_database_name()
        def _execute():
            with self._sync_conn.cursor() as cur:
                cur.execute(self.GET_TABLES_SQL.format(database=database))
                tables_rows = cur.fetchall()
                cur.execute(self.GET_TABLE_COMMENT_SQL, (database,))
                comments_rows = cur.fetchall()
                return tables_rows, comments_rows
        try:
            tables_rows, comments_rows = await asyncio.get_event_loop().run_in_executor(None, _execute)
            comments_map = {row[0]: row[1] or "" for row in comments_rows}
            tables = []
            for row in tables_rows:
                table_name = row[0]
                tables.append(TableInfo(
                    table_name=table_name,
                    table_comment=comments_map.get(table_name, ""),
                    schema_name=database,
                    columns=[]
                ))
            logger.debug(f"[DorisMetadataExtractor]  {len(tables)} ")
            return tables
        except Exception as e:
            logger.error(f"[DorisMetadataExtractor] : {e}")
            raise
    async def get_table_columns(self, table_name: str) -> List[ColumnInfo]:
        if not self._sync_conn:
            await self.connect()
        database = self.get_database_name()
        if '.' in table_name:
            _, table_name = table_name.split('.', 1)
        def _execute():
            with self._sync_conn.cursor() as cur:
                cur.execute(self.GET_COLUMNS_INFO_SQL, (database, table_name))
                return cur.fetchall()
        try:
            rows = await asyncio.get_event_loop().run_in_executor(None, _execute)
            columns = []
            for row in rows:
                (column_name, data_type, is_nullable, column_comment,
                 column_key, default_value, char_length, num_precision, num_scale) = row
                full_data_type = self._build_data_type(
                    data_type, char_length, num_precision, num_scale
                )
                columns.append(ColumnInfo(
                    column_name=column_name,
                    data_type=full_data_type,
                    is_nullable=(is_nullable == 'YES'),
                    column_comment=column_comment or "",
                    is_primary_key=(column_key == 'PRI'),
                    default_value=default_value or ""
                ))
            logger.debug(f"[DorisMetadataExtractor]  {table_name}  {len(columns)} ")
            return columns
        except Exception as e:
            logger.error(f"[DorisMetadataExtractor] : {e}")
            raise
    async def get_table_full_info(self, table_name: str) -> TableInfo:
        if not self._sync_conn:
            await self.connect()
        database = self.get_database_name()
        if '.' in table_name:
            _, table_name = table_name.split('.', 1)
        def _execute():
            with self._sync_conn.cursor() as cur:
                cur.execute(
                    "SELECT TABLE_COMMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                    (database, table_name)
                )
                table_row = cur.fetchone()
                cur.execute(self.GET_COLUMNS_INFO_SQL, (database, table_name))
                columns_rows = cur.fetchall()
                return table_row, columns_rows
        try:
            table_row, columns_rows = await asyncio.get_event_loop().run_in_executor(None, _execute)
            table_comment = table_row[0] if table_row else ""
            columns = []
            for row in columns_rows:
                (column_name, data_type, is_nullable, column_comment,
                 column_key, default_value, char_length, num_precision, num_scale) = row
                full_data_type = self._build_data_type(
                    data_type, char_length, num_precision, num_scale
                )
                columns.append(ColumnInfo(
                    column_name=column_name,
                    data_type=full_data_type,
                    is_nullable=(is_nullable == 'YES'),
                    column_comment=column_comment or "",
                    is_primary_key=(column_key == 'PRI'),
                    default_value=default_value or ""
                ))
            return TableInfo(
                table_name=table_name,
                table_comment=table_comment,
                schema_name=database,
                columns=columns
            )
        except Exception as e:
            logger.error(f"[DorisMetadataExtractor] : {e}")
            raise
    def _build_data_type(
        self,
        data_type: str,
        char_length: Optional[int],
        num_precision: Optional[int],
        num_scale: Optional[int]
    ) -> str:
        data_type_lower = data_type.lower()
        if data_type_lower in ('varchar', 'char', 'text', 'string'):
            if char_length:
                return f"{data_type}({char_length})"
            return data_type
        if data_type_lower in ('decimal', 'numeric'):
            if num_precision:
                if num_scale:
                    return f"{data_type}({num_precision},{num_scale})"
                return f"{data_type}({num_precision})"
        return data_type