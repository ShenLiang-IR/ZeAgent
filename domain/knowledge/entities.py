from typing import List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
class KnowledgeType(str, Enum):
    UNSTRUCTURED = "0"
    STRUCTURED = "1"
    @classmethod
    def from_string(cls, value: str) -> "KnowledgeType":
        try:
            return cls(value)
        except ValueError:
            return cls.UNSTRUCTURED
    @classmethod
    def to_display_name(cls, value: str) -> str:
        if value == cls.STRUCTURED.value:
            return ""
        return ""
@dataclass
class KnowledgeMetadata:
    knowledge_base_id: str
    knowledge_name: str
    knowledge_type: KnowledgeType = KnowledgeType.UNSTRUCTURED
    description: str = ""
    enabled: bool = True
    documents: List[Dict[str, Any]] = field(default_factory=list)
    sql_models: List[Dict[str, Any]] = field(default_factory=list)
    business_type: str = ""
    visible_scope: str = "1"
    tags: str = ""
    pr_key_id: str = ""
    database_type: str = ""
    database_table: str = ""
    embedding_model: str = ""
    chunk_size: int = 1000
    overlap_size: int = 200
    @classmethod
    def from_database(
        cls,
        db_record: Dict[str, Any],
        documents: List[Dict[str, Any]] = None,
        sql_models: List[Dict[str, Any]] = None
    ) -> "KnowledgeMetadata":
        kb_type = KnowledgeType.from_string(
            db_record.get("knowledge_type", "0")
        )
        enabled = db_record.get("enabled", False)
        if isinstance(enabled, str):
            enabled = enabled == "1" or enabled.lower() == "true"
        return cls(
            knowledge_base_id=db_record.get("knowledge_base_id", ""),
            knowledge_name=db_record.get("knowledge_name", ""),
            knowledge_type=kb_type,
            description=db_record.get("description", ""),
            enabled=enabled,
            documents=documents or [],
            sql_models=sql_models or [],
            business_type=db_record.get("business_type", ""),
            visible_scope=db_record.get("visible_scope", "1"),
            tags=db_record.get("tags", ""),
            pr_key_id=db_record.get("pr_key_id", ""),
            database_type=db_record.get("database_type", ""),
            database_table=db_record.get("database_table", ""),
            embedding_model=db_record.get("embedding_model", ""),
            chunk_size=db_record.get("chunk_size", 1000) or 1000,
            overlap_size=db_record.get("overlap_size", 200) or 200,
        )
    def build_brief_description(self, max_length: int = 80) -> str:
        type_name = KnowledgeType.to_display_name(self.knowledge_type.value)
        base = f"[{type_name}] {self.knowledge_name}"
        if self.description:
            desc = f"{base}: {self.description}"
        else:
            desc = base
        if len(desc) <= max_length:
            return desc
        return desc[:max_length-3] + "..."
    def build_structured_tool_description(self, knowledge_metadata_list: List["KnowledgeMetadata"]) -> str:
        lines = [
            "",
            "",
            "",
        ]
        for metadata in knowledge_metadata_list:
            if metadata.knowledge_type != KnowledgeType.STRUCTURED:
                continue
            if not metadata.enabled:
                continue
            lines.append(f"")
            lines.append(f">> {metadata.knowledge_name}")
            if metadata.description:
                lines.append(f"  : {metadata.description}")
            if metadata.sql_models:
                lines.append(f"  :")
                for model in metadata.sql_models:
                    model_name = model.get('sql_model_name', '')
                    model_desc = model.get('sql_model_description', '')
                    param_info = self._extract_param_info(model.get('sql_execution_config'))
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
        example = self._build_structured_example(knowledge_metadata_list)
        lines.extend(["", "", example])
        return "\n".join(lines)
    def build_unstructured_tool_description(self, knowledge_metadata_list: List["KnowledgeMetadata"]) -> str:
        lines = [
            "",
            "",
            "",
        ]
        for metadata in knowledge_metadata_list:
            if metadata.knowledge_type != KnowledgeType.UNSTRUCTURED:
                continue
            if not metadata.enabled:
                continue
            lines.append(f"")
            lines.append(f">> {metadata.knowledge_name}")
            if metadata.description:
                lines.append(f"   : {metadata.description}")
            if metadata.documents:
                lines.append(f"   :")
                for doc in metadata.documents[:10]:
                    doc_name = doc.get('document_name', '')
                    doc_desc = doc.get('description', '')
                    if doc_desc:
                        lines.append(f"     - {doc_name}: {doc_desc}")
                    else:
                        lines.append(f"     - {doc_name}")
                if len(metadata.documents) > 10:
                    lines.append(f"     ...  {len(metadata.documents)} ")
            else:
                lines.append(f"   ()")
        lines.extend([
            "",
            "",
            "- semantic: LLM ",
            "- metadata: ",
            "- global: ",
            "",
            "",
            "- knowledge_name:  ()",
            "- query:  ()",
            "- strategy:  semantic",
            "- top_k: 5"
        ])
        example = self._build_unstructured_example(knowledge_metadata_list)
        lines.extend(["", "", example])
        return "\n".join(lines)
    def _extract_param_info(self, sql_execution_config: str) -> str:
        import json
        if not sql_execution_config:
            return ""
        try:
            config = json.loads(sql_execution_config)
            parameters = config.get('parameters', [])
            if parameters:
                param_names = [p.get('name', '?') for p in parameters]
                return ", ".join(param_names)
        except Exception:
            pass
        return ""
    def _build_structured_example(self, knowledge_metadata_list: List["KnowledgeMetadata"]) -> str:
        for metadata in knowledge_metadata_list:
            if metadata.knowledge_type != KnowledgeType.STRUCTURED:
                continue
            if not metadata.enabled or not metadata.sql_models:
                continue
            model = metadata.sql_models[0]
            model_name = model.get('sql_model_name', '')
            kb_name = metadata.knowledge_name
            param_info = self._extract_param_info(model.get('sql_execution_config'))
            params_str = "{}"
            if param_info:
                param_names = [p.strip() for p in param_info.split(',')]
                params_dict = {name: f"<{name}>" for name in param_names if name}
                if params_dict:
                    import json
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
    def _build_unstructured_example(self, knowledge_metadata_list: List["KnowledgeMetadata"]) -> str:
        for metadata in knowledge_metadata_list:
            if metadata.knowledge_type != KnowledgeType.UNSTRUCTURED:
                continue
            if not metadata.enabled:
                continue
            kb_name = metadata.knowledge_name
            return (
                f"query_unstructured_knowledge(\n"
                f"    knowledge_name='{kb_name}',\n"
                f"    query='<>',\n"
                f"    strategy='semantic',\n"
                f"    top_k=5\n"
                f")"
            )
        return (
            "query_unstructured_knowledge(\n"
            "    knowledge_name='<>',\n"
            "    query='<>',\n"
            "    strategy='semantic',\n"
            "    top_k=5\n"
            ")"
        )
    def __repr__(self) -> str:
        return (
            f"KnowledgeMetadata(id={self.knowledge_base_id}, "
            f"name={self.knowledge_name}, "
            f"type={self.knowledge_type.value}, "
            f"enabled={self.enabled})"
        )