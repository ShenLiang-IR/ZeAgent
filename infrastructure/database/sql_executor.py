import re
import json
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field
from loguru import logger
import pandas as pd
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
@dataclass
class SqlExecutionResult:
    success: bool
    data: List[Dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    column_names: List[str] = field(default_factory=list)
    column_comments: Dict[str, str] = field(default_factory=dict)
    error: str = ""
    def to_text(self, max_rows: int = None, max_columns: int = None, max_chars: int = 15000) -> str:
        if not self.success:
            return f"SQL 执行错误: {self.error}"
        if self.row_count == 0:
            return ""
        data = self.data
        if max_rows and len(data) > max_rows:
            data = data[:max_rows]
        df = pd.DataFrame(data)
        if max_columns and len(df.columns) > max_columns:
            df = df.iloc[:, :max_columns]
        comments_info = ""
        if self.column_comments:
            comment_lines = []
            display_cols = df.columns.tolist()
            for col_name in display_cols:
                comment = self.column_comments.get(col_name, "")
                if comment:
                    comment_lines.append(f"  {col_name}: {comment}")
            if comment_lines:
                comments_info = "\n:\n" + "\n".join(comment_lines) + "\n"
        total_rows = len(data)
        total_cols = len(self.column_names)
        result_text = f"共 {self.row_count} 行{comments_info}\n{df.to_string(index=False)}"
        if len(result_text) > max_chars:
            result_text = result_text[:max_chars] + f"\n...(: {total_rows}: {total_cols})"
        return result_text
class SqlExecutor:
    DANGEROUS_KEYWORDS = [
        'DROP', 'DELETE', 'TRUNCATE', 'INSERT', 'UPDATE',
        'ALTER', 'CREATE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE'
    ]
    ES_SQL_KEYWORDS = [
        'SELECT', 'FROM', 'WHERE', 'GROUP BY', 'ORDER BY',
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE',
        'ALTER', 'TRUNCATE', 'MERGE', 'REINDEX'
    ]
    ES_DSL_LEGAL_TOP_KEYS = {'index', 'query', 'aggs', 'sort', 'from', 'size', '_source', 'highlight', 'collapse'}
    def __init__(self, db_config: Dict[str, Any]):
        self.db_config = db_config
        self.db_type = self._normalize_db_type(db_config.get('type') or db_config.get('dbtype', 'postgresql'))
        from db_skills.implementations.text2sql.config import ES_QUERY_MODE
        self.es_query_mode = ES_QUERY_MODE
        self._engine = None
    def _normalize_db_type(self, db_type: str) -> str:
        db_type = db_type.lower()
        if db_type in ('postgresql', 'postgres'):
            return 'postgresql'
        if db_type in ('doris', 'mysql'):
            return 'doris'
        if db_type in ('elasticsearch', 'es', 'elastic'):
            return 'elasticsearch'
        return db_type
    def _build_connection_url(self) -> str:
        user = self.db_config.get('user') or self.db_config.get('username', '')
        password = self.db_config.get('password') or self.db_config.get('pwd', '')
        host = self.db_config['host']
        port = self.db_config.get('port', 5432)
        database = self.db_config['database']
        encoded_user = quote_plus(user)
        encoded_password = quote_plus(password)
        if self.db_type == 'postgresql':
            return f"postgresql+psycopg2://{encoded_user}:{encoded_password}@{host}:{port}/{database}"
        elif self.db_type == 'doris':
            return f"mysql+pymysql://{encoded_user}:{encoded_password}@{host}:{port}/{database}"
        else:
            return f"{self.db_type}://{encoded_user}:{encoded_password}@{host}:{port}/{database}"
    def _get_connect_args(self) -> Dict[str, Any]:
        connect_args = {}
        if self.db_type == 'postgresql':
            schema = self.db_config.get('schema', 'public')
            if schema and schema != 'public':
                connect_args['options'] = f'-csearch_path={schema},public'
            connect_args['client_encoding'] = 'utf8'
        elif self.db_type == 'doris':
            connect_args['ssl_disabled'] = True
        return connect_args
    def _get_engine(self):
        if self._engine is None:
            url = self._build_connection_url()
            connect_args = self._get_connect_args()
            host = self.db_config.get('host', 'unknown')
            port = self.db_config.get('port', 5432)
            database = self.db_config.get('database', 'unknown')
            user = self.db_config.get('user') or self.db_config.get('username', 'unknown')
            logger.info(f"[SqlExecutor] : type={self.db_type}, host={host}, port={port}, database={database}, user={user}")
            if connect_args:
                self._engine = create_engine(url, connect_args=connect_args)
                logger.debug(f"[SqlExecutor] connect_args: {connect_args}")
            else:
                self._engine = create_engine(url)
        return self._engine
    def is_safe_sql(self, sql: str) -> Tuple[bool, str]:
        sql_upper = sql.upper().strip()
        for keyword in self.DANGEROUS_KEYWORDS:
            if re.search(rf'\b{keyword}\b', sql_upper):
                return False, f"SQL : {keyword}"
        if self.db_type in ('elasticsearch', 'es', 'elastic'):
            if self.es_query_mode == 'sql':
                return self._is_safe_es_sql(sql)
            else:
                return self._is_safe_es_dsl(sql)
        if not sql_upper.startswith('SELECT'):
            return False, " SELECT "
        return True, ""
    def _is_safe_es_sql(self, sql: str) -> Tuple[bool, str]:
        sql_upper = sql.upper().strip()
        es_sql_dangerous = [
            'DELETE', 'DROP', 'INSERT', 'UPDATE',
            'CREATE', 'ALTER', 'TRUNCATE', 'MERGE', 'REINDEX'
        ]
        for keyword in es_sql_dangerous:
            if re.search(rf'\b{keyword}\b', sql_upper):
                return False, f"ES SQL : {keyword}"
        if not sql_upper.startswith('SELECT'):
            return False, "ES SQL  SELECT "
        return True, ""
    def _is_safe_es_dsl(self, dsl_text: str) -> Tuple[bool, str]:
        try:
            dsl = json.loads(dsl_text)
        except json.JSONDecodeError as e:
            return False, f"ES DSL  JSON: {str(e)}"
        if not isinstance(dsl, dict):
            return False, "ES DSL  JSON "
        forbidden_top_keys = {'delete', 'update', 'create', 'bulk'}
        root_keys = {k.lower() for k in dsl.keys()}
        dangerous = root_keys & forbidden_top_keys
        if dangerous:
            return False, f"ES DSL : {dangerous}"
        if 'query' not in root_keys and 'aggs' not in root_keys:
            return False, "ES DSL  query  aggs "
        def deep_check(obj, path=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    key_lower = key.lower()
                    if key_lower == 'script' and isinstance(value, dict):
                        source = value.get('source', '')
                        if isinstance(source, str):
                            source_lower = source.lower()
                            if any(kw in source_lower for kw in ['delete', 'drop', 'remove', 'update', 'create']):
                                return False, "ES DSL script "
                    if isinstance(value, str):
                        value_upper = value.upper().strip()
                        sql_patterns = [
                            ('SELECT', 'FROM'),
                            ('INSERT', 'INTO'),
                            ('UPDATE', 'SET'),
                            ('DELETE', 'FROM'),
                            ('DROP', 'TABLE'),
                            ('CREATE', 'TABLE'),
                        ]
                        for kw1, kw2 in sql_patterns:
                            if kw1 in value_upper and kw2 in value_upper:
                                return False, f"ES DSL  SQL : {kw1} {kw2}"
                    safe, msg = deep_check(value, f"{path}.{key}")
                    if not safe:
                        return safe, msg
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    safe, msg = deep_check(item, f"{path}[{i}]")
                    if not safe:
                        return safe, msg
            return True, ""
        safe, msg = deep_check(dsl)
        if not safe:
            return False, msg
        return True, ""
    def execute(
        self,
        sql: str,
        limit: int = 100,
        skip_safety_check: bool = False,
        column_comments: Dict[str, str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> SqlExecutionResult:
        logger.debug(f"[SqlExecutor]  SQL, limit={limit}")
        logger.debug(f"[SqlExecutor] SQL: {sql}")
        if not skip_safety_check:
            is_safe, error_msg = self.is_safe_sql(sql)
            if not is_safe:
                logger.warning(f"[SqlExecutor] SQL : {error_msg}")
                return SqlExecutionResult(success=False, error=error_msg)
        if self.db_type in ('elasticsearch', 'es', 'elastic'):
            try:
                if self.es_query_mode == 'sql':
                    return self._execute_es_sql(sql, limit)
                else:
                    return self._execute_es_dsl(sql, limit)
            except Exception as e:
                error_msg = f"ES : {str(e)}"
                logger.error(f"[SqlExecutor] {error_msg}")
                return SqlExecutionResult(success=False, error=error_msg)
        try:
            engine = self._get_engine()
            df = pd.read_sql_query(text(sql), engine, params=params)
            logger.debug(f"[SqlExecutor] SQL ,  {len(df)} ")
            if len(df) == 0:
                return SqlExecutionResult(success=True, data=[], row_count=0)
            if len(df) > limit:
                df = df.head(limit)
                logger.debug(f"[SqlExecutor]  {limit} ")
            data = df.to_dict(orient='records')
            column_names = list(df.columns)
            return SqlExecutionResult(
                success=True,
                data=data,
                row_count=len(data),
                column_names=column_names,
                column_comments=column_comments or {}
            )
        except Exception as e:
            error_msg = f"SQL: {str(e)}"
            logger.error(f"[SqlExecutor] {error_msg}")
            return SqlExecutionResult(success=False, error=error_msg)
    def _execute_es_sql(self, sql: str, limit: int = 100) -> SqlExecutionResult:
        client = self._build_es_client()
        try:
            response = client.sql.query(
                body={
                    "query": sql,
                    "fetch_size": limit
                }
            )
            columns = [col['name'] for col in response.get('columns', [])]
            rows = response.get('rows', [])
            data = []
            for row in rows:
                data.append({col: val for col, val in zip(columns, row)})
            return SqlExecutionResult(
                success=True,
                data=data,
                row_count=len(data),
                column_names=columns,
                column_comments={}
            )
        except Exception as e:
            return SqlExecutionResult(success=False, error=f"ES SQL : {str(e)}")
        finally:
            client.close()
    def _build_es_client(self):
        from elasticsearch import Elasticsearch
        import elastic_transport
        elastic_transport._verified_elasticsearch = True
        hosts = self.db_config.get('host', 'localhost').split(',')
        port = self.db_config.get('port', 9200)
        use_ssl = self.db_config.get('use_ssl', False)
        verify_certs = self.db_config.get('verify_certs', True)
        es_hosts = [f"{'https' if use_ssl else 'http'}://{h.strip()}:{port}" for h in hosts]
        client_kwargs = {
            'hosts': es_hosts,
            'verify_certs': verify_certs,
        }
        if self.db_config.get('api_key'):
            client_kwargs['api_key'] = self.db_config['api_key']
        elif self.db_config.get('username') and self.db_config.get('password'):
            client_kwargs['http_auth'] = (
                self.db_config['username'],
                self.db_config['password']
            )
        elif self.db_config.get('username') and self.db_config.get('pwd'):
            client_kwargs['http_auth'] = (
                self.db_config['username'],
                self.db_config['pwd']
            )
        elif self.db_config.get('user') and self.db_config.get('password'):
            client_kwargs['http_auth'] = (
                self.db_config['user'],
                self.db_config['password']
            )
        elif self.db_config.get('user') and self.db_config.get('pwd'):
            client_kwargs['http_auth'] = (
                self.db_config['user'],
                self.db_config['pwd']
            )
        if self.db_config.get('ca_certs'):
            client_kwargs['ca_certs'] = self.db_config['ca_certs']
        return Elasticsearch(**client_kwargs)
    def _execute_es_dsl(self, dsl_text: str, limit: int = 100) -> SqlExecutionResult:
        import json
        client = self._build_es_client()
        try:
            dsl = json.loads(dsl_text)
            index = dsl.pop('index', '_all')
            if isinstance(index, list):
                index = ','.join(index)
            if 'size' not in dsl:
                dsl['size'] = limit
            else:
                dsl['size'] = min(dsl['size'], limit)
            search_params = {}
            for key, value in dsl.items():
                if key == 'from':
                    search_params['from_'] = value
                else:
                    search_params[key] = value
            response = client.search(index=index, **search_params)
            hits = response.get('hits', {}).get('hits', [])
            data = []
            for hit in hits:
                doc = hit.get('_source', {})
                doc['_id'] = hit.get('_id')
                doc['_score'] = hit.get('_score')
                data.append(doc)
            column_names = list(data[0].keys()) if data else []
            aggs = response.get('aggregations', {})
            if aggs:
                agg_data = self._flatten_aggregations(aggs)
                if agg_data:
                    data = agg_data
                    column_names = list(data[0].keys()) if data else []
            return SqlExecutionResult(
                success=True,
                data=data,
                row_count=len(data),
                column_names=column_names,
                column_comments={}
            )
        except json.JSONDecodeError as e:
            error_msg = f"ES DSL : {str(e)}"
            logger.error(f"[SqlExecutor] {error_msg}")
            return SqlExecutionResult(success=False, error=error_msg)
        except Exception as e:
            error_msg = f"ES DSL : {str(e)}"
            logger.error(f"[SqlExecutor] {error_msg}")
            return SqlExecutionResult(success=False, error=error_msg)
        finally:
            client.close()
    def _flatten_aggregations(self, aggs: Dict[str, Any]) -> List[Dict[str, Any]]:
        result = []
        def extract_buckets(obj, prefix=""):
            if not isinstance(obj, dict):
                return
            for key, value in obj.items():
                if isinstance(value, dict):
                    if 'buckets' in value:
                        for bucket in value['buckets']:
                            row = {}
                            if 'key' in bucket:
                                row[f"{prefix}{key}_key"] = bucket['key']
                            if 'key_as_string' in bucket:
                                row[f"{prefix}{key}_key_string"] = bucket['key_as_string']
                            if 'doc_count' in bucket:
                                row[f"{prefix}{key}_count"] = bucket['doc_count']
                            for sub_key, sub_value in bucket.items():
                                if sub_key not in ('key', 'key_as_string', 'doc_count'):
                                    if isinstance(sub_value, dict):
                                        if 'value' in sub_value:
                                            row[f"{prefix}{sub_key}"] = sub_value['value']
                                        elif 'buckets' in sub_value:
                                            nested = extract_buckets({sub_key: sub_value}, f"{prefix}{sub_key}_")
                                            if nested:
                                                for nr in nested:
                                                    merged = {**row, **nr}
                                                    result.append(merged)
                                                row = {}
                            if row:
                                result.append(row)
                    elif 'value' in value:
                        result.append({f"{prefix}{key}": value['value']})
        extract_buckets(aggs)
        return result
    def close(self):
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
async def execute_readonly_sql(
    db_config: Dict[str, Any],
    sql: str,
    limit: int = 100
) -> SqlExecutionResult:
    executor = SqlExecutor(db_config)
    try:
        return executor.execute(sql, limit)
    finally:
        executor.close()