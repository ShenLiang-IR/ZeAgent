from utils.common.json_utils import parse_json_field
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger
class SkillCategory(str, Enum):
    GENERAL = "general"
    CODING = "coding"
    SEARCH = "search"
    ANALYSIS = "analysis"
    WRITING = "writing"
    DATA = "data"
    AUTOMATION = "automation"
    COMMUNICATION = "communication"
    UTILITY = "utility"
    # 行业领域
    LEGAL = "legal"
    FINANCE = "finance"
    MEDICAL = "medical"
    MEDIA = "media"
    EDUCATION = "education"
    ECOMMERCE = "ecommerce"
    @classmethod
    def from_string(cls, value: str) -> "SkillCategory":
        try:
            return cls(value.lower())
        except ValueError:
            return cls.GENERAL
class SkillSource(str, Enum):
    DISK = "disk"
    DATABASE = "database"
@dataclass
class SkillParameter:
    param_name: str
    param_type: str
    param_desc: str = ""
    required: bool = False
    default_value: Any = None
    def to_langchain_field(self) -> tuple:
        from pydantic import Field
        from typing import Any, Optional
        type_map = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        py_type = type_map.get(self.param_type, Any)
        if self.required:
            return (py_type, Field(..., description=self.param_desc))
        else:
            return (Optional[py_type], Field(self.default_value, description=self.param_desc))
@dataclass
class SkillTriggerHint:
    keywords: List[str] = field(default_factory=list)
    scenarios: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    anti_patterns: List[str] = field(default_factory=list)
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SkillTriggerHint":
        if not data:
            return cls()
        return cls(
            keywords=data.get("keywords", []),
            scenarios=data.get("scenarios", []),
            examples=data.get("examples", []),
            anti_patterns=data.get("anti_patterns", [])
        )
    def format_for_llm(self) -> str:
        parts = []
        if self.keywords:
            parts.append(f": {', '.join(self.keywords)}")
        if self.scenarios:
            parts.append(f": {'; '.join(self.scenarios)}")
        if self.examples:
            parts.append(":")
            for ex in self.examples:
                parts.append(f"  - {ex}")
        if self.anti_patterns:
            parts.append(f": {'; '.join(self.anti_patterns)}")
        return "\n".join(parts)
@dataclass
class SkillResource:
    resource_type: str
    resource_path: str
    description: str = ""
    language: str = ""
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillResource":
        return cls(
            resource_type=data.get("type", "reference"),
            resource_path=data.get("path", ""),
            description=data.get("description", ""),
            language=data.get("language", "")
        )
    def format_for_llm(self) -> str:
        lang_suffix = f" ({self.language})" if self.language else ""
        return f"- [{self.resource_type}]{lang_suffix}: {self.resource_path} - {self.description}"
@dataclass
class SkillMetadata:
    skill_id: str
    skill_name: str
    skill_desc: str = ""
    category: SkillCategory = SkillCategory.GENERAL
    enabled: bool = True
    module_path: str = ""
    class_name: str = ""
    function_name: str = ""
    parameters: List[SkillParameter] = field(default_factory=list)
    trigger_hint: SkillTriggerHint = field(default_factory=SkillTriggerHint)
    resources: List[SkillResource] = field(default_factory=list)
    skill_directory: str = ""
    table_restrictions: Dict[str, Dict[str, str]] = field(default_factory=dict)
    lazy_load: bool = True
    preload_priority: int = 0
    db_configs: List[str] = field(default_factory=list)
    _config_dict: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    @classmethod
    def from_database(
        cls,
        db_record: Dict[str, Any]
    ) -> "SkillMetadata":
        config_param = {}
        config_param_str = db_record.get("config_param", "")
        if config_param_str:
            try:
                if isinstance(config_param_str, str):
                    config_param = json.loads(config_param_str)
                elif isinstance(config_param_str, dict):
                    config_param = config_param_str
            except (json.JSONDecodeError, TypeError):
                config_param = {}
        parameters = []
        input_json_param = db_record.get("input_json_param", "")
        if input_json_param:
            try:
                params_list = parse_json_field(input_json_param)
                for p in params_list:
                    parameters.append(SkillParameter(
                        param_name=p.get("paramName", ""),
                        param_type=p.get("paramType", "string"),
                        param_desc=p.get("paramDesc", ""),
                        required=p.get("isRequire", "0") == "1"
                    ))
            except (json.JSONDecodeError, TypeError):
                pass
        trigger_hint = SkillTriggerHint.from_dict(config_param.get("trigger_hint"))
        resources = []
        for res_data in config_param.get("resources", []):
            resources.append(SkillResource.from_dict(res_data))
        module_path = config_param.get("module_path", "") or ""
        class_name = config_param.get("class_name", "") or ""
        function_name = config_param.get("function_name", "") or ""
        skill_desc = db_record.get("skill_desc", "") or ""
        if not skill_desc and module_path and (class_name or function_name):
            logger.debug(
                f"[SkillMetadata]  skill_desc : "
                f"module={module_path}, class={class_name}, function={function_name}"
            )
            skill_desc = cls._load_default_prompt_from_code(module_path, class_name, function_name)
            if skill_desc:
                logger.info(f"[SkillMetadata] : {len(skill_desc)} ")
            else:
                logger.warning(f"[SkillMetadata] ")
        db_configs = []
        db_configs_data = config_param.get("db_configs")
        if db_configs_data is not None:
            if isinstance(db_configs_data, list):
                db_configs = db_configs_data
            elif isinstance(db_configs_data, str):
                db_configs = [db_configs_data]
        table_restrictions = {}
        restrictions_data = config_param.get("table_restrictions")
        if restrictions_data and isinstance(restrictions_data, dict):
            table_restrictions = restrictions_data
        return cls(
            skill_id=db_record["skill_id"],
            skill_name=db_record["skill_name"],
            skill_desc=skill_desc,
            category=SkillCategory.from_string(config_param.get("skill_type") or db_record.get("skill_type", "general")),
            enabled=db_record.get("enable_status", "1") == "1",
            module_path=module_path,
            class_name=class_name,
            function_name=function_name,
            parameters=parameters,
            trigger_hint=trigger_hint,
            resources=resources,
            skill_directory=config_param.get("skill_directory", ""),
            lazy_load=config_param.get("lazy_load", True),
            preload_priority=config_param.get("preload_priority", 0),
            db_configs=db_configs,
            table_restrictions=table_restrictions,
            _config_dict=config_param,
        )
    @classmethod
    def _load_default_prompt_from_code(
        cls,
        module_path: str,
        class_name: str = "",
        function_name: str = ""
    ) -> str:
        try:
            import importlib
            import sys
            from pathlib import Path
            original_module_path = module_path
            if module_path.startswith("app."):
                module_path = module_path[4:]
            logger.debug(f"[SkillMetadata] : {module_path} (: {original_module_path})")
            current_file = Path(__file__).resolve()
            app_dir = current_file.parent.parent.parent
            app_dir_str = str(app_dir)
            if app_dir_str not in sys.path:
                sys.path.insert(0, app_dir_str)
                logger.debug(f"[SkillMetadata]  Python : {app_dir_str}")
            module = importlib.import_module(module_path)
            if class_name:
                cls_obj = getattr(module, class_name, None)
                if cls_obj:
                    if hasattr(cls_obj, 'DEFAULT_SKILL_DESC'):
                        default_desc = getattr(cls_obj, 'DEFAULT_SKILL_DESC')
                        if default_desc:
                            logger.debug(f"[SkillMetadata]  DEFAULT_SKILL_DESC : {class_name}")
                            return default_desc
                    if cls_obj.__doc__:
                        doc_desc = cls_obj.__doc__.strip()
                        if doc_desc and doc_desc != class_name:
                            logger.debug(f"[SkillMetadata] : {class_name}")
                            return doc_desc
            elif function_name:
                func = getattr(module, function_name, None)
                if func:
                    if hasattr(func, 'DEFAULT_SKILL_DESC'):
                        default_desc = getattr(func, 'DEFAULT_SKILL_DESC')
                        if default_desc:
                            logger.debug(f"[SkillMetadata]  DEFAULT_SKILL_DESC : {function_name}")
                            return default_desc
                    if func.__doc__:
                        doc_desc = func.__doc__.strip()
                        if doc_desc:
                            logger.debug(f"[SkillMetadata] : {function_name}")
                            return doc_desc
        except ImportError as e:
            logger.warning(f"[SkillMetadata] : {module_path} - {e}")
        except AttributeError as e:
            logger.warning(f"[SkillMetadata] : {e}")
        except Exception as e:
            logger.warning(f"[SkillMetadata] : {e}")
        return ""
    def build_brief_description(self, max_length: int = 80) -> str:
        if not self.skill_desc:
            return ""
        if len(self.skill_desc) <= max_length:
            return self.skill_desc
        return self.skill_desc[:max_length-3] + "..."
    def build_tool_description(self) -> str:
        return self.skill_desc
    def build_full_content(self) -> str:
        parts = [
            f"# {self.skill_name}",
            f"**ID**: {self.skill_id}",
        ]
        if self.skill_desc:
            parts.append(f"\n{self.skill_desc}")
        if self.parameters:
            parts.append("\n## ")
            for param in self.parameters:
                req = "" if param.required else ""
                default = f" (: {param.default_value})" if param.default_value is not None else ""
                parts.append(
                    f"- **{param.param_name}** ({param.param_type}, {req}){default}: "
                    f"{param.param_desc}"
                )
        if self.trigger_hint.keywords or self.trigger_hint.scenarios or self.trigger_hint.examples:
            parts.append("\n## ")
            parts.append(self.trigger_hint.format_for_llm())
        if self.resources:
            parts.append("\n## ")
            parts.append(" read_skill_resource :")
            for res in self.resources:
                parts.append(res.format_for_llm())
        return "\n".join(parts)
@dataclass
class SkillExecutionResult:
    success: bool
    output: str = ""
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
@dataclass
class Skill:
    name: str
    description: str
    category: SkillCategory = SkillCategory.GENERAL
    source: SkillSource = SkillSource.DISK
    skill_dir: Optional[str] = None
    db_pr_key_id: Optional[str] = None
    skill_file: Optional[str] = None
    cached_content: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    enabled: bool = True
    metadata: Optional[SkillMetadata] = None
    def get_container_file_path(self, base_path: str = "/mnt/skills") -> str:
        category = "custom" if self.source == SkillSource.DATABASE else "public"
        return f"{base_path}/{category}/{self.name}/SKILL.md"
    def format_metadata_xml(self, base_path: str = "/mnt/skills") -> str:
        category = "custom" if self.source == SkillSource.DATABASE else "public"
        location = f"{base_path}/{category}/{self.name}/SKILL.md"
        label = "[custom]" if self.source == SkillSource.DATABASE else "[built-in]"
        return (
            f'<skill>\n'
            f'  <name>{self.name}</name>\n'
            f'  <description>{self.description} {label}</description>\n'
            f'  <location>{location}</location>\n'
            f'</skill>'
        )