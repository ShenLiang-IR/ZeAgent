from typing import List, Dict, Optional, TYPE_CHECKING
from loguru import logger
from langchain_core.tools import StructuredTool
from .entities import KnowledgeMetadata, KnowledgeType
if TYPE_CHECKING:
    pass
class LazyKnowledgeProxy:
    STATE_NOT_LOADED = "not_loaded"
    STATE_LOADED = "loaded"
    STATE_FAILED = "failed"
    ENABLE_STRUCTURED_KNOWLEDGE_TOOL = False
    def __init__(self, metadata_list: List[KnowledgeMetadata]):
        self._metadata_list = metadata_list
        self._structured_tool = None
        self._unstructured_tool = None
        self._load_state = self.STATE_NOT_LOADED
    @property
    def metadata_list(self) -> List[KnowledgeMetadata]:
        return self._metadata_list
    @property
    def is_loaded(self) -> bool:
        return self._load_state == self.STATE_LOADED
    def get_structured_metadata(self) -> List[KnowledgeMetadata]:
        return [
            m for m in self._metadata_list
            if m.knowledge_type == KnowledgeType.STRUCTURED and m.enabled
        ]
    def get_unstructured_metadata(self) -> List[KnowledgeMetadata]:
        return [
            m for m in self._metadata_list
            if m.knowledge_type == KnowledgeType.UNSTRUCTURED and m.enabled
        ]
    def load_tools(self) -> bool:
        if self._load_state == self.STATE_LOADED:
            return True
        try:
            logger.debug(
                f"[LazyKnowledgeProxy]  {len(self._metadata_list)} "
            )
            structured_metadata = self.get_structured_metadata()
            if structured_metadata:
                self._structured_tool = self._create_structured_tool(structured_metadata)
                logger.info(
                    f"[LazyKnowledgeProxy]  {len(structured_metadata)} "
                )
            unstructured_metadata = self.get_unstructured_metadata()
            if unstructured_metadata:
                self._unstructured_tool = self._create_unstructured_tool(unstructured_metadata)
                logger.info(
                    f"[LazyKnowledgeProxy]  {len(unstructured_metadata)} "
                )
            self._load_state = self.STATE_LOADED
            return True
        except Exception as e:
            self._load_state = self.STATE_FAILED
            logger.error(
                f"[LazyKnowledgeProxy] : {e}",
                exc_info=True
            )
            return False
    def _create_structured_tool(self, metadata_list: List[KnowledgeMetadata]):
        from tools.structured_knowledge.structured_knowledge_tool import (
            StructuredKnowledgeInput
        )
        from typing import Dict, Any
        class FilteredStructuredKnowledgeTool:
            def __init__(self, filtered_metadata: List[KnowledgeMetadata]):
                self._metadata_list = filtered_metadata
                self._knowledge_cache: Dict[str, Dict] = {}
                self._sql_model_cache: Dict[str, Dict[str, Dict]] = {}
                self._load_from_metadata()
                self.tool_description = self._build_tool_description()
            def _load_from_metadata(self):
                for metadata in self._metadata_list:
                    kb_name = metadata.knowledge_name
                    kb_id = metadata.knowledge_base_id
                    self._knowledge_cache[kb_name] = {
                        'knowledge_base_id': kb_id,
                        'knowledge_name': kb_name,
                        'description': metadata.description,
                    }
                    self._sql_model_cache[kb_id] = {
                        model['sql_model_name']: model
                        for model in metadata.sql_models
                    }
            def _build_tool_description(self) -> str:
                if self._metadata_list:
                    return self._metadata_list[0].build_structured_tool_description(
                        self._metadata_list
                    )
                return ""
            def invoke(
                self,
                knowledge_name: str,
                sql_model_name: str,
                params: Optional[Dict[str, Any]] = None
            ) -> str:
                import json
                logger.info(
                    f"[FilteredStructuredKnowledgeTool] : ={knowledge_name}, "
                    f"={sql_model_name}, ={params}"
                )
                kb_info = self._knowledge_cache.get(knowledge_name)
                if not kb_info:
                    available = list(self._knowledge_cache.keys())
                    return json.dumps({
                        "success": False,
                        "error": f" '{knowledge_name}' ",
                        "hint": f": {', '.join(available) if available else ''}",
                        "data": None
                    }, ensure_ascii=False, indent=2)
                kb_id = kb_info['knowledge_base_id']
                sql_models = self._sql_model_cache.get(kb_id, {})
                model_info = sql_models.get(sql_model_name)
                if not model_info:
                    available = list(sql_models.keys())
                    return json.dumps({
                        "success": False,
                        "error": f" '{sql_model_name}'  '{knowledge_name}'",
                        "hint": f": {', '.join(available) if available else ''}",
                        "data": None
                    }, ensure_ascii=False, indent=2)
                try:
                    from tools.structured_knowledge.structured_knowledge_tool import StructuredKnowledgeTool
                    from utils.config import get_config
                    api_base_url = get_config('knowledge.api_base_url', 'http://localhost:8001')
                    api_headers = get_config('knowledge.api_headers', {})
                    original_tool = StructuredKnowledgeTool(
                        api_base_url=api_base_url,
                        api_headers=api_headers
                    )
                    return original_tool.invoke(knowledge_name, sql_model_name, params)
                except Exception as e:
                    logger.error(f"[FilteredStructuredKnowledgeTool] : {e}")
                    return json.dumps({
                        "success": False,
                        "error": f": {str(e)}",
                        "data": None
                    }, ensure_ascii=False, indent=2)
            def to_langchain_tool(self) -> StructuredTool:
                return StructuredTool.from_function(
                    func=self.invoke,
                    name="query_structured_knowledge",
                    description=self.tool_description,
                    args_schema=StructuredKnowledgeInput
                )
        return FilteredStructuredKnowledgeTool(metadata_list)
    def _create_unstructured_tool(self, metadata_list: List[KnowledgeMetadata]):
        from tools.unstructured_knowledge.unstructured_knowledge_tool import (
            UnstructuredKnowledgeInput
        )
        class FilteredUnstructuredKnowledgeTool:
            def __init__(self, filtered_metadata: List[KnowledgeMetadata]):
                self._metadata_list = filtered_metadata
                self._knowledge_cache: Dict[str, Dict] = {}
                self._load_from_metadata()
                self.tool_description = self._build_tool_description()
            def _load_from_metadata(self):
                for metadata in self._metadata_list:
                    kb_name = metadata.knowledge_name
                    self._knowledge_cache[kb_name] = {
                        'knowledge_base_id': metadata.knowledge_base_id,
                        'knowledge_name': kb_name,
                        'description': metadata.description,
                        '_documents': metadata.documents,
                    }
            def _build_tool_description(self) -> str:
                if self._metadata_list:
                    return self._metadata_list[0].build_unstructured_tool_description(
                        self._metadata_list
                    )
                return ""
            def invoke(
                self,
                knowledge_name: str,
                query: str,
                strategy: str = "semantic",
                top_k: int = 5
            ) -> str:
                import json
                logger.info(
                    f"[FilteredUnstructuredKnowledgeTool] : ={knowledge_name}, "
                    f"={query[:50]}..., ={strategy}"
                )
                kb_info = self._knowledge_cache.get(knowledge_name)
                if not kb_info:
                    available = list(self._knowledge_cache.keys())
                    return json.dumps({
                        "success": False,
                        "error": f" '{knowledge_name}' ",
                        "hint": f": {', '.join(available) if available else ''}",
                        "data": None
                    }, ensure_ascii=False, indent=2)
                kb_id = kb_info['knowledge_base_id']
                try:
                    from tools.unstructured_knowledge.unstructured_knowledge_tool import UnstructuredKnowledgeTool
                    original_tool = UnstructuredKnowledgeTool()
                    return original_tool.invoke(knowledge_name, query, strategy, top_k)
                except Exception as e:
                    logger.error(f"[FilteredUnstructuredKnowledgeTool] : {e}")
                    return json.dumps({
                        "success": False,
                        "error": f": {str(e)}",
                        "data": None
                    }, ensure_ascii=False, indent=2)
            def to_langchain_tool(self) -> StructuredTool:
                return StructuredTool.from_function(
                    func=self.invoke,
                    name="query_unstructured_knowledge",
                    description=self.tool_description,
                    args_schema=UnstructuredKnowledgeInput
                )
        return FilteredUnstructuredKnowledgeTool(metadata_list)
    def to_langchain_tools(self) -> List[StructuredTool]:
        if self._load_state == self.STATE_NOT_LOADED:
            self.load_tools()
        tools = []
        if self.ENABLE_STRUCTURED_KNOWLEDGE_TOOL and self._structured_tool:
            tools.append(self._structured_tool.to_langchain_tool())
            logger.info(f"[LLM-] query_structured_knowledge - ")
            logger.debug(f"[LLM-] query_structured_knowledge - :\n{self._structured_tool.tool_description[:500]}...")
        elif not self.ENABLE_STRUCTURED_KNOWLEDGE_TOOL and self.get_structured_metadata():
            logger.info(
                f"[LLM-] query_structured_knowledge - "
                f" execute_sql_template "
            )
            sql_models_info = []
            for metadata in self.get_structured_metadata():
                for model in metadata.sql_models:
                    input_params = []
                    config_str = model.get('sql_execution_config', '')
                    if config_str:
                        try:
                            import json
                            config = json.loads(config_str)
                            for p in config.get('inputParam', []):
                                input_params.append({
                                    'name': p.get('paramName', ''),
                                    'desc': p.get('paramDescription', ''),
                                })
                        except Exception:
                            pass
                    sql_models_info.append({
                        'sql_model_id': model.get('sql_model_id', ''),
                        'sql_model_name': model.get('sql_model_name', ''),
                        'sql_model_description': model.get('sql_model_description', ''),
                        'kb_name': metadata.knowledge_name,
                        'input_params': input_params,
                    })
            try:
                from tools.sql_template_tool import SqlTemplateTool
                sql_template_tool = SqlTemplateTool(
                    kb_ids=[m.knowledge_base_id for m in self.get_structured_metadata()],
                    sql_models_info=sql_models_info
                )
                langchain_tool = sql_template_tool.to_langchain_tool()
                tools.append(langchain_tool)
                logger.info(f"[LLM-] execute_sql_template -  {len(sql_models_info)} SQL")
            except Exception as e:
                logger.warning(f"[LLM-]  execute_sql_template : {e}")
        if self._unstructured_tool:
            tools.append(self._unstructured_tool.to_langchain_tool())
            logger.info(f"[LLM-] query_unstructured_knowledge - ")
            logger.debug(f"[LLM-] query_unstructured_knowledge - :\n{self._unstructured_tool.tool_description[:500]}...")
        return tools
    def __repr__(self) -> str:
        structured_count = len(self.get_structured_metadata())
        unstructured_count = len(self.get_unstructured_metadata())
        return (
            f"LazyKnowledgeProxy(total={len(self._metadata_list)}, "
            f"structured={structured_count}, "
            f"unstructured={unstructured_count}, "
            f"state={self._load_state})"
        )