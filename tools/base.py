from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from langchain_core.tools import tool
class BaseTool(ABC):
    def __init__(self, name: str, description: str, config: Optional[Dict] = None):
        self.name = name
        self.description = description
        self.config = config or {}
    @abstractmethod
    def invoke(self, *args, **kwargs) -> Any:
        pass
    def to_langchain_tool(self):
        @tool
        def tool_func(*args, **kwargs):
            return self.invoke(*args, **kwargs)
        tool_func.name = self.name
        tool_func.description = self.description
        return tool_func