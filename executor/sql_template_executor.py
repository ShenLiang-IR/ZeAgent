import re
import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from loguru import logger
from utils.common.cache import TTLCacheMixin
from infrastructure.database.repositories.knowledge_repository import (
    KnowledgeBaseSqlModelRepository,
    KnowledgeBaseRepository
)
from infrastructure.database.sql_executor import SqlExecutor, SqlExecutionResult
from utils.config.apollo_config import get_db_config
@dataclass
class SqlTemplateResult:
    success: bool
    data: List[Dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    column_names: List[str] = field(default_factory=list)
    sql: str = ""
    error: str = ""
    @classmethod
    def from_execution_result(cls, result: SqlExecutionResult, sql: str) -> 'SqlTemplateResult':
        return cls(
            success=result.success,
            data=result.data,
            row_count=result.row_count,
            column_names=result.column_names,
            sql=sql,
            error=result.error
        )
    def to_text(self, max_rows: int = None) -> str:
        if not self.success:
            return f"错误: {self.error}"
        if self.row_count == 0:
            return ""
        import pandas as pd
        data = self.data
        if max_rows and len(data) > max_rows:
            data = data[:max_rows]
        df = pd.DataFrame(data)
        return f" {len(data)} \n\n{df.to_string(index=False, max_cols=None)}"
class SqlTemplateExecutor(TTLCacheMixin):
    PARAM_PATTERN = re.compile(r'\{\{(\w+)\}\}|\{(\w+)\}')
    def __init__(self):
        self.sql_model_repo = KnowledgeBaseSqlModelRepository()
        self.knowledge_base_repo = KnowledgeBaseRepository()
        self._db_config_cache: Dict[str, Dict[str, Any]] = {}
        self._kb_cache: Dict[str, Dict[str, Any]] = {}
        self._ttl_seconds = 300  # 缓存 5 分钟
        self._last_loaded = time.time()
        self._is_refreshing = False
    def _clear_cache(self) -> None:
        """TTL 过期时清空配置缓存（防配置变更后不刷新）。"""
        self._db_config_cache.clear()
        self._kb_cache.clear()
    def get_sql_model_config(self, sql_model_id: str) -> Optional[Dict[str, Any]]:
        config = self.sql_model_repo.get_by_id(sql_model_id, return_dict=True)
        return config
    def parse_execution_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        sql_execution_config = config.get('sql_execution_config', '{}')
        try:
            parsed = json.loads(sql_execution_config)
        except json.JSONDecodeError as e:
            logger.error(f"[SqlTemplateExecutor]  sql_execution_config : {e}")
            parsed = {}
        return {
            'sql_statement': parsed.get('sqlStatement', ''),
            'database_type': parsed.get('databaseType', ''),
            'input_params': parsed.get('inputParam', []),
            'output_params': parsed.get('outputParam', {}),
            'default_limit': parsed.get('limit', 100),
            'database_tables': parsed.get('database', [])
        }
    def validate_params(
        self,
        input_param_defs: List[Dict[str, Any]],
        params: Dict[str, Any]
    ) -> tuple[bool, str]:
        missing_params = []
        for param_def in input_param_defs:
            param_name = param_def.get('paramName', '')
            required = param_def.get('required', False)
            if required and param_name not in params:
                missing_params.append(param_name)
        if missing_params:
            return False, f"缺少必填参数: {', '.join(missing_params)}"
        # 类型 + 长度校验（防 SQL 注入载荷：超长字符串 / 类型不匹配）
        _MAX_STRING_LEN = 5000
        _STRING_TYPES = {'string', 'varchar', 'text', 'str', 'char', 'date', 'datetime'}
        _NUMBER_TYPES = {'number', 'int', 'integer', 'float', 'decimal', 'numeric', 'double'}
        for param_def in input_param_defs:
            param_name = param_def.get('paramName', '')
            if param_name not in params:
                continue
            value = params[param_name]
            data_type = (param_def.get('dataType') or '').lower()
            if data_type in _STRING_TYPES:
                if not isinstance(value, str):
                    return False, f"参数 {param_name} 类型错误：期望字符串，实际 {type(value).__name__}"
                if len(value) > _MAX_STRING_LEN:
                    return False, f"参数 {param_name} 长度超限（>{_MAX_STRING_LEN} 字符），疑似注入载荷"
            elif data_type in _NUMBER_TYPES:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return False, f"参数 {param_name} 类型错误：期望数字，实际 {type(value).__name__}"
        return True, ""
    # 默认将 \ 作为转义符的方言（NO_BACKSLASH_ESCAPES 未开启时）。
    # 对这些方言，字符串值必须同时转义反斜杠与单引号，否则 `\'` 可令字符串提前闭合造成注入。
    _BACKSLASH_ESCAPE_DIALECTS = {"mysql", "mariadb", "oracle"}

    def render_sql(
        self,
        sql_template: str,
        params: Dict[str, Any],
        database_type: Optional[str] = None,
    ) -> tuple[str, dict]:
        """参数化渲染：{name} → :name 命名占位 + 收集 bound_params。

        根治 SQL 注入：driver 原生参数绑定，不再字符串拼接/引号转义。
        database_type 参数保留兼容（参数绑定无需方言转义）。
        """
        bound: Dict[str, Any] = {}

        def replace_param(match):
            param_name = match.group(1) or match.group(2)
            value = params.get(param_name)
            if value is None:
                logger.warning(f"[SqlTemplateExecutor] 参数 {param_name} 缺失，保留占位符")
                return match.group(0)
            # 参数化绑定：driver 原生绑定，无需转义；非标量类型拒绝
            if isinstance(value, bool):
                bound[param_name] = value
            elif isinstance(value, (int, float)):
                bound[param_name] = value
            elif isinstance(value, str):
                bound[param_name] = value
            else:
                raise ValueError(
                    f"参数 {param_name} 类型不支持参数化绑定: {type(value).__name__}"
                )
            return f":{param_name}"
        rendered = self.PARAM_PATTERN.sub(replace_param, sql_template)
        return rendered, bound
    def get_db_config_cached(self, db_type: str) -> Dict[str, Any]:
        self._invalidate_if_expired()
        if db_type not in self._db_config_cache:
            try:
                self._db_config_cache[db_type] = get_db_config(db_type)
            except ValueError as e:
                logger.error(f"[SqlTemplateExecutor] : {e}")
                raise
        return self._db_config_cache[db_type]
    def execute(
        self,
        sql_model_id: str,
        params: Dict[str, Any],
        limit: int = 100
    ) -> SqlTemplateResult:
        logger.info(f"[SqlTemplateExecutor]  SQL : {sql_model_id}, params={params}, limit={limit}")
        config = self.get_sql_model_config(sql_model_id)
        if not config:
            logger.error(f"[SqlTemplateExecutor] SQL : {sql_model_id}")
            return SqlTemplateResult(
                success=False,
                error=f"SQL : {sql_model_id}"
            )
        exec_config = self.parse_execution_config(config)
        sql_template = exec_config['sql_statement']
        input_params = exec_config['input_params']
        if not sql_template:
            return SqlTemplateResult(
                success=False,
                error="SQL  sqlStatement"
            )
        knowledge_base_id = config.get('knowledge_base_id', '')
        database_type = self._get_database_type_from_knowledge_base(knowledge_base_id)
        if not database_type:
            return SqlTemplateResult(
                success=False,
                error=f" {knowledge_base_id}  database_type"
            )
        is_valid, error_msg = self.validate_params(input_params, params)
        if not is_valid:
            return SqlTemplateResult(success=False, error=error_msg)
        rendered_sql, bound_params = self.render_sql(sql_template, params, database_type)
        logger.debug(f"[SqlTemplateExecutor] 参数化 SQL: {rendered_sql}, params={bound_params}")
        try:
            db_config = self.get_db_config_cached(database_type)
        except Exception as e:
            return SqlTemplateResult(
                success=False,
                error=f"数据库配置获取失败: {str(e)}"
            )
        executor = SqlExecutor(db_config)
        try:
            result = executor.execute(rendered_sql, limit, params=bound_params)
            return SqlTemplateResult.from_execution_result(result, rendered_sql)
        finally:
            executor.close()
    def _get_database_type_from_knowledge_base(self, knowledge_base_id: str) -> Optional[str]:
        if not knowledge_base_id:
            return None
        self._invalidate_if_expired()
        if knowledge_base_id in self._kb_cache:
            return self._kb_cache[knowledge_base_id].get('database_type')
        kb_config = self.knowledge_base_repo.get_by_id(knowledge_base_id, return_dict=True)
        if kb_config:
            self._kb_cache[knowledge_base_id] = kb_config
            database_type = kb_config.get('database_type', '')
            logger.debug(f"[SqlTemplateExecutor]  {knowledge_base_id}  database_type: {database_type}")
            return database_type
        return None
    async def execute_async(
        self,
        sql_model_id: str,
        params: Dict[str, Any],
        limit: int = 100
    ) -> SqlTemplateResult:
        """真正的异步执行：将同步 execute() 放入线程池以避免阻塞事件循环。"""
        import asyncio
        return await asyncio.to_thread(self.execute, sql_model_id, params, limit)
    def clear_cache(self):
        self._db_config_cache.clear()
        self._kb_cache.clear()
        logger.debug("[SqlTemplateExecutor] ")