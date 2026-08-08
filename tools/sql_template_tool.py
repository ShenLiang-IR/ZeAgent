import json
from datetime import date, datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from loguru import logger
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(obj, date):
            return obj.strftime('%Y-%m-%d')
        return super().default(obj)
class SqlTemplateInput(BaseModel):
    sql_model_id: str = Field(
        ...,
        description="SQLIDtb_knowledge_base_sql_model"
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="SQL {'id': '12345', 'status': 1}"
    )
    limit: int = Field(
        default=100,
        description="100",
        ge=1,
        le=1000
    )
class SqlTemplateTool:
    def __init__(self, kb_ids: List[str] = None, sql_models_info: List[Dict[str, Any]] = None):
        from executor.sql_template_executor import SqlTemplateExecutor
        self.executor = SqlTemplateExecutor()
        self._kb_ids = kb_ids or []
        self._sql_models_info = sql_models_info or []
    def invoke(
        self,
        sql_model_id: str,
        params: Optional[Dict[str, Any]] = None,
        limit: int = 100
    ) -> str:
        import json
        logger.info(
            f"[SqlTemplateTool] SQL: sql_model_id={sql_model_id}, "
            f"params={params}, limit={limit}"
        )
        try:
            result = self.executor.execute(
                sql_model_id=sql_model_id,
                params=params or {},
                limit=limit
            )
            response = {
                "success": result.success,
                "data": result.data if result.success else [],
                "row_count": result.row_count,
                "column_names": result.column_names,
                "sql": result.sql,
                "error": result.error
            }
            if result.success:
                logger.info(f"[SqlTemplateTool] : {result.row_count} ")
            else:
                logger.warning(f"[SqlTemplateTool] : {result.error}")
            return json.dumps(response, ensure_ascii=False, indent=2, cls=DateTimeEncoder)
        except Exception as e:
            error_msg = f"SQL: {str(e)}"
            logger.error(f"[SqlTemplateTool] {error_msg}", exc_info=True)
            return json.dumps({
                "success": False,
                "data": [],
                "row_count": 0,
                "column_names": [],
                "sql": "",
                "error": error_msg
            }, ensure_ascii=False, indent=2, cls=DateTimeEncoder)
    def to_langchain_tool(self) -> StructuredTool:
        description = self._build_tool_description()
        logger.info(f"[LLM-SQL] execute_sql_template - : 3")
        logger.info(f"[LLM-SQL] execute_sql_template - : sql_model_id = SQLID ()")
        logger.info(f"[LLM-SQL] execute_sql_template - : params = SQL ()")
        logger.info(f"[LLM-SQL] execute_sql_template - : limit =  (100)")
        logger.debug(f"[LLM-SQL] execute_sql_template - :\n{description}")
        return StructuredTool.from_function(
            func=self.invoke,
            name="execute_sql_template",
            description=description,
            args_schema=SqlTemplateInput
        )
    def _build_tool_description(self) -> str:
        base_desc = "SQLSELECTSQL"
        if not self._sql_models_info:
            if self._kb_ids:
                return base_desc + f"\nID{', '.join(self._kb_ids)}"
            return base_desc
        kb_groups: Dict[str, List[Dict[str, Any]]] = {}
        for model in self._sql_models_info:
            kb_name = model.get('kb_name', '')
            kb_groups.setdefault(kb_name, []).append(model)
        lines = [base_desc, "", "SQL"]
        for kb_name, models in kb_groups.items():
            lines.append("")
            lines.append(f"▶ {kb_name}")
            for model in models:
                model_id = model.get('sql_model_id', '')
                model_name = model.get('sql_model_name', '')
                model_desc = model.get('sql_model_description', '')
                lines.append(f"  - {model_name}(ID:{model_id})")
                if model_desc:
                    lines.append(f"    {model_desc}")
                input_params = model.get('input_params', [])
                if input_params:
                    param_str = ", ".join(
                        f"{p['name']}({p['desc']})" for p in input_params if p.get('name')
                    )
                    if param_str:
                        lines.append(f"    {param_str}")
        return "\n".join(lines)
_sql_template_tool: Optional[SqlTemplateTool] = None
_langchain_tool: Optional[StructuredTool] = None
def get_sql_template_tool() -> SqlTemplateTool:
    global _sql_template_tool
    if _sql_template_tool is None:
        _sql_template_tool = SqlTemplateTool()
    return _sql_template_tool
def execute_sql_template(
    sql_model_id: str,
    params: Optional[Dict[str, Any]] = None,
    limit: int = 100
) -> str:
    tool = get_sql_template_tool()
    return tool.invoke(sql_model_id, params, limit)