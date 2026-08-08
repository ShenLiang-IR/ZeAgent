"""知识库工具基类，提供公共的生命周期管理和错误响应。"""
import json
from typing import Dict
from loguru import logger


class BaseKnowledgeTool:
    """结构化/非结构化知识库工具的公共基类。

    子类需实现：
    - _load_knowledge_bases(): 从数据库加载知识库数据到 _knowledge_cache
    - _build_tool_description(): 构建工具描述文本
    - invoke(...): 执行知识查询
    - to_langchain_tool(): 转换为 LangChain StructuredTool

    子类可在 _on_reload() 中清理额外缓存。
    """

    def __init__(self):
        """初始化公共缓存和工具描述。子类 __init__ 应先调 super().__init__()。"""
        self._knowledge_cache: Dict[str, Dict] = {}
        self.tool_description: str = ""

    def _error_response(self, error_msg: str, hint: str = "") -> str:
        """构建统一的错误响应 JSON。"""
        return json.dumps({
            "success": False,
            "error": error_msg,
            "hint": hint,
            "data": None
        }, ensure_ascii=False, indent=2)

    def reload(self):
        """重新加载知识库数据并重建工具描述。"""
        self._knowledge_cache.clear()
        self._on_reload()
        self._load_knowledge_bases()
        self.tool_description = self._build_tool_description()
        logger.info(f"[{self.__class__.__name__}] ")

    def _on_reload(self):
        """子类可覆盖：清理额外缓存（如 SQL 模型缓存）。"""
        pass
