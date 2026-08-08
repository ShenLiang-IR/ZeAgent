from typing import Dict, Any, Optional
from loguru import logger
import httpx
import json
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from infrastructure.database.repositories.knowledge_repository import (
    KnowledgeBaseRepository,
    KnowledgeBaseSqlModelRepository
)
from tools.knowledge_base_tool import BaseKnowledgeTool
class StructuredKnowledgeInput(BaseModel):
    knowledge_name: str = Field(
        ...,
        description=""
    )
    sql_model_name: str = Field(
        ...,
        description="/SQL"
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description=""
    )
class StructuredKnowledgeTool(BaseKnowledgeTool):
    def __init__(self, api_base_url: str = "", api_headers: Dict[str, str] = None):
        super().__init__()
        self.api_base_url = api_base_url
        self.api_headers = api_headers or {}
        self.kb_repo = KnowledgeBaseRepository()
        self.sql_model_repo = KnowledgeBaseSqlModelRepository()
        self._sql_model_cache: Dict[str, Dict[str, Dict]] = {}
        self._load_knowledge_bases()
        self.tool_description = self._build_tool_description()
    def _load_knowledge_bases(self):
        try:
            structured_kbs = self.kb_repo.get_structured(enabled_only=True)
            logger.info(f"[StructuredKnowledgeTool]  {len(structured_kbs)} ")
            for kb in structured_kbs:
                kb_name = kb['knowledge_name']
                kb_id = kb['knowledge_base_id']
                self._knowledge_cache[kb_name] = kb
                sql_models = self.sql_model_repo.get_by_kb(kb_id)
                self._sql_model_cache[kb_id] = {
                    model['sql_model_name']: model
                    for model in sql_models
                }
                logger.info(
                    f"[StructuredKnowledgeTool]  '{kb_name}' "
                    f" {len(sql_models)} SQL"
                )
        except Exception as e:
            logger.error(f"[StructuredKnowledgeTool] : {str(e)}", exc_info=True)
    def _build_tool_description(self) -> str:
        lines = [
            "",
            "",
            "",
        ]
        for kb_name, kb_info in self._knowledge_cache.items():
            kb_desc = kb_info.get('description', '')
            lines.append(f"")
            lines.append(f">> {kb_name}")
            if kb_desc:
                lines.append(f"  : {kb_desc}")
            kb_id = kb_info['knowledge_base_id']
            sql_models = self._sql_model_cache.get(kb_id, {})
            if sql_models:
                lines.append(f"  :")
                for model_name, model_info in sql_models.items():
                    model_desc = model_info.get('sql_model_description', '')
                    param_info = self._extract_param_info(model_info.get('sql_execution_config'))
                    lines.append(f"    - {model_name}: {model_desc}")
                    if param_info:
                        lines.append(f"      : {param_info}")
            else:
                lines.append(f"  ()")
        lines.extend([
            "",
            "",
            "- knowledge_name:  ()",
            "- sql_model_name:  ()",
            "- params:  ()"
        ])
        example = self._build_example()
        lines.extend(["", "", example])
        return "\n".join(lines)
    def _build_example(self) -> str:
        for kb_name, kb_info in self._knowledge_cache.items():
            kb_id = kb_info['knowledge_base_id']
            sql_models = self._sql_model_cache.get(kb_id, {})
            if not sql_models:
                continue
            model_name = list(sql_models.keys())[0]
            model_info = sql_models[model_name]
            param_info = self._extract_param_info(model_info.get('sql_execution_config'))
            params_str = "{}"
            if param_info:
                param_names = [p.strip() for p in param_info.split(',')]
                params_dict = {name: f"<{name}>" for name in param_names if name}
                if params_dict:
                    params_str = json.dumps(params_dict, ensure_ascii=False)
            return (
                f"query_structured_knowledge(\n"
                f"    knowledge_name='{kb_name}',\n"
                f"    sql_model_name='{model_name}',\n"
                f"    params={params_str}\n"
                f")"
            )
        return (
            "query_structured_knowledge(\n"
            "    knowledge_name='<>',\n"
            "    sql_model_name='<>',\n"
            "    params={'<>': '<>'}\n"
            ")"
        )
    def _extract_param_info(self, sql_execution_config: str) -> str:
        if not sql_execution_config:
            return ""
        try:
            config = json.loads(sql_execution_config)
            parameters = config.get('inputParam', [])
            if parameters:
                param_names = [p.get('paramName', '?') for p in parameters]
                return ", ".join(param_names)
        except Exception:
            pass
        return ""
    def invoke(
        self,
        knowledge_name: str,
        sql_model_name: str,
        params: Optional[Dict[str, Any]] = None
    ) -> str:
        logger.info(
            f"[StructuredKnowledgeTool] : ={knowledge_name}, "
            f"={sql_model_name}, ={params}"
        )
        kb_info = self._knowledge_cache.get(knowledge_name)
        if not kb_info:
            available = list(self._knowledge_cache.keys())
            return self._error_response(
                f" '{knowledge_name}' ",
                f": {', '.join(available)}"
            )
        kb_id = kb_info['knowledge_base_id']
        sql_models = self._sql_model_cache.get(kb_id, {})
        model_info = sql_models.get(sql_model_name)
        if not model_info:
            available = list(sql_models.keys())
            return self._error_response(
                f" '{sql_model_name}'  '{knowledge_name}'",
                f": {', '.join(available) if available else ''}"
            )
        try:
            result = self._call_external_api(
                kb_info=kb_info,
                model_info=model_info,
                params=params or {}
            )
            return result
        except Exception as e:
            logger.error(f"[StructuredKnowledgeTool] API: {str(e)}", exc_info=True)
            return self._error_response(f": {str(e)}")
    def _call_external_api(
        self,
        kb_info: Dict,
        model_info: Dict,
        params: Dict[str, Any]
    ) -> str:
        sql_config = model_info.get('sql_execution_config', '{}')
        try:
            config = json.loads(sql_config)
            api_endpoint = config.get('api_endpoint', '')
        except Exception:
            api_endpoint = ''
        if api_endpoint:
            url = f"{self.api_base_url.rstrip('/')}/{api_endpoint.lstrip('/')}"
        else:
            kb_id = kb_info['knowledge_base_id']
            sql_model_id = model_info['sql_model_id']
            url = f"{self.api_base_url.rstrip('/')}/api/knowledge/{kb_id}/query/{sql_model_id}"
        request_body = {
            "knowledge_base_id": kb_info['knowledge_base_id'],
            "knowledge_name": kb_info['knowledge_name'],
            "sql_model_id": model_info['sql_model_id'],
            "sql_model_name": model_info['sql_model_name'],
            "params": params
        }
        headers = {
            "Content-Type": "application/json",
            **self.api_headers
        }
        logger.debug(f"[StructuredKnowledgeTool] API: {url}")
        logger.debug(f"[StructuredKnowledgeTool] : {request_body}")
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=request_body, headers=headers)
            response.raise_for_status()
            result = response.json()
        logger.info(f"[StructuredKnowledgeTool] API")
        return json.dumps(result, ensure_ascii=False, indent=2)
    def to_langchain_tool(self) -> StructuredTool:
        logger.info(f"[LLM-] query_structured_knowledge - : 3")
        logger.info(f"[LLM-] query_structured_knowledge - : knowledge_name =  ()")
        logger.info(f"[LLM-] query_structured_knowledge - : sql_model_name = /SQL ()")
        logger.info(f"[LLM-] query_structured_knowledge - : params =  ()")
        logger.debug(f"[LLM-] query_structured_knowledge - :\n{self.tool_description}")
        return StructuredTool.from_function(
            func=self.invoke,
            name="query_structured_knowledge",
            description=self.tool_description,
            args_schema=StructuredKnowledgeInput
        )
    def _on_reload(self):
        """清理 SQL 模型缓存（由 BaseKnowledgeTool.reload 调用）。"""
        self._sql_model_cache.clear()