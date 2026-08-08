import importlib
import inspect
import json
import threading
from loguru import logger
from typing import Dict, List, Type, Optional, Any
from pathlib import Path
from .base import BaseTool
from utils.common.cache import TTLCacheMixin
def format_tool_description(
    description: str,
    parameter_descriptions: Optional[Dict[str, str]] = None,
    return_description: Optional[str] = None,
    examples: Optional[List[str]] = None,
    dependencies: Optional[List[str]] = None
) -> str:
    parts = [description]
    if parameter_descriptions:
        parts.append("\n\n:")
        for param_name, param_desc in parameter_descriptions.items():
            parts.append(f"- {param_name}: {param_desc}")
    if return_description:
        parts.append(f"\n: {return_description}")
    if examples:
        parts.append("\n:")
        for example in examples:
            parts.append(f"- {example}")
    if dependencies:
        parts.append("\n:")
        parts.append("")
        for dep in dependencies:
            parts.append(f"- {dep}")
    return "\n".join(parts)
class ToolRegistry(TTLCacheMixin):
    # 风险等级单例
    _risk_levels: Dict[str, str] = {}       # tool_name → risk_level
    _risk_descriptions: Dict[str, str] = {} # tool_name → risk_description

    def __init__(self):
        self._tools: Dict[str, Any] = {}
        self._tool_classes: Dict[str, Type[BaseTool]] = {}
        self._langchain_tools: List[Any] = []

    @property
    def _tool_risk_levels(self) -> Dict[str, str]:
        """兼容测试的属性访问 — 返回类级别 risk_levels。"""
        return ToolRegistry._risk_levels

    @_tool_risk_levels.setter
    def _tool_risk_levels(self, value: Dict[str, str]):
        ToolRegistry._risk_levels = value

    def _clear_cache(self) -> None:
        self._tools.clear()
        self._tool_classes.clear()
        self._langchain_tools.clear()

    def get_risk_level(self, tool_name: str) -> str:
        """获取工具风险等级，未知返回 read_only。"""
        return ToolRegistry._risk_levels.get(tool_name, "read_only")

    def get_risk_description(self, tool_name: str) -> str:
        """获取工具风险描述。"""
        return ToolRegistry._risk_descriptions.get(tool_name, "")

    def set_risk_level(self, tool_name: str, level: str, description: str = "") -> None:
        """设置工具风险等级和描述。"""
        valid = {"read_only", "write_safe", "destructive", "external", "always"}
        if level not in valid:
            level = "read_only"
        ToolRegistry._risk_levels[tool_name] = level
        if description:
            ToolRegistry._risk_descriptions[tool_name] = description
    def _ensure_loaded(self) -> None:
        if not self._tools:
            self.discover_tools()
    def register(self, tool: Any, name: Optional[str] = None):
        if name:
            tool_name = name
        elif hasattr(tool, 'name'):
            tool_name = tool.name
        elif hasattr(tool, '__name__'):
            tool_name = tool.__name__
        else:
            tool_name = str(tool)
        tool_description = None
        parameter_descriptions = None
        return_description = None
        examples = None
        agent_dir = Path(__file__).parent.parent
        tools_config_dir = agent_dir / "config" / "tools"
        tool_config_file = tools_config_dir / f"{tool_name}.json"
        if tool_config_file.exists():
            try:
                with open(tool_config_file, 'r', encoding='utf-8') as f:
                    tool_config = json.load(f)
                tool_description = tool_config.get('description')
                parameter_descriptions = tool_config.get('parameter_descriptions')
                return_description = tool_config.get('return_description')
                examples = tool_config.get('examples')
                if tool_description:
                    logger.info(f"JSON: {tool_name}")
            except Exception as e:
                logger.warning(f"JSON {tool_name}: {str(e)}")
        if tool_description:
            if parameter_descriptions or return_description or examples:
                formatted_description = format_tool_description(
                    description=tool_description,
                    parameter_descriptions=parameter_descriptions,
                    return_description=return_description,
                    examples=examples
                )
            else:
                formatted_description = tool_description
            if hasattr(tool, 'description'):
                tool.description = formatted_description
        self._tools[tool_name] = tool
        if hasattr(tool, 'name') and hasattr(tool, 'invoke'):
            if tool not in self._langchain_tools:
                self._langchain_tools.append(tool)
        logger.info(f"[] : {tool_name} (: {'LangChain Tool' if hasattr(tool, 'name') and hasattr(tool, 'invoke') else ''})")
    def get(self, name: str) -> Optional[Any]:
        self._invalidate_if_expired()
        self._ensure_loaded()
        return self._tools.get(name)
    def get_all(self) -> List[Any]:
        self._invalidate_if_expired()
        self._ensure_loaded()
        tools = list(self._tools.values())
        logger.debug(f"[] get_all()  {len(tools)} : {', '.join(self._tools.keys())}")
        return tools
    def reload(self):
        self._tools.clear()
        self._tool_classes.clear()
        self._langchain_tools.clear()
        self.discover_tools()
        logger.info("reload")
    def discover_tools(self, tools_dir: Optional[Path] = None, use_init_all: bool = True):
        if tools_dir is None:
            tools_dir = Path(__file__).parent
        if use_init_all:
            try:
                tools_module = importlib.import_module('tools')
                if hasattr(tools_module, '__all__'):
                    tool_names = tools_module.__all__
                else:
                    use_init_all = False
                    tool_names = []
                for tool_name in tool_names:
                    if hasattr(tools_module, tool_name):
                        tool = getattr(tools_module, tool_name)
                        if (hasattr(tool, 'name') and hasattr(tool, 'invoke')):
                            self.register(tool)
                        elif callable(tool) and (hasattr(tool, '__name__')):
                            self.register(tool)
            except Exception as e:
                logger.warning(f"tools/__init__.py: {str(e)}")
                use_init_all = False
        if not use_init_all:
            for file_path in tools_dir.glob("*.py"):
                if file_path.name.startswith("_") or file_path.name in ["base.py", "registry.py", "external_tool.py"]:
                    continue
                module_name = f"tools.{file_path.stem}"
                try:
                    module = importlib.import_module(module_name)
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if (issubclass(obj, BaseTool) and 
                            obj != BaseTool and 
                            obj.__module__ == module_name):
                            try:
                                tool_instance = obj()
                                self.register(tool_instance)
                            except Exception as e:
                                logger.warning(f"实例化工具类 {name} 失败: {e}")
                    for name, obj in inspect.getmembers(module):
                        if (hasattr(obj, 'name') and hasattr(obj, 'invoke') and
                            obj.__module__ == module_name):
                            self.register(obj)
                        elif (inspect.isfunction(obj) and 
                              hasattr(obj, '__name__') and
                              obj.__module__ == module_name):
                            self.register(obj)
                except Exception as e:
                    logger.warning(f"加载工具模块 {module_name} 失败: {e}")
        self.discover_external_tools()
        self._mark_loaded()
    def discover_external_tools(self):
        try:
            from .external_tool import load_all_external_tools
            logger.info("[] ...")
            external_tools = load_all_external_tools()
            if not external_tools:
                logger.warning("[] ")
                return
            logger.info(f"[]  {len(external_tools)} ...")
            registered_count = 0
            for tool_name, tool_instance in external_tools.items():
                try:
                    if tool_instance.name != tool_name:
                        logger.warning(f"[] : key={tool_name}, name={tool_instance.name}, key")
                    langchain_tool = tool_instance.to_langchain_tool()
                    if langchain_tool.name != tool_name:
                        logger.warning(f"[] LangChain: ={tool_name}, name={langchain_tool.name}, ")
                        langchain_tool.name = tool_name
                    self.register(langchain_tool, name=tool_name)
                    registered_count += 1
                    logger.info(f"[] : {tool_name}")
                except Exception as e:
                    logger.error(f"[]  {tool_name}: {str(e)}", exc_info=True)
            logger.info(f"[]  {registered_count}/{len(external_tools)} ")
        except Exception as e:
            logger.error(f"[] : {str(e)}", exc_info=True)
_tool_registry: Optional[ToolRegistry] = None
_tool_registry_lock = threading.Lock()
def get_tool_registry() -> ToolRegistry:
    global _tool_registry
    if _tool_registry is None:
        with _tool_registry_lock:
            if _tool_registry is None:
                _tool_registry = ToolRegistry()
                _tool_registry.discover_tools()
    return _tool_registry