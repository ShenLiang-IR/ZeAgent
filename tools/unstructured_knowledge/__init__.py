from .unstructured_knowledge_tool import (
    UnstructuredKnowledgeTool,
    UnstructuredKnowledgeInput
)
def create_unstructured_knowledge_tool(rag_config_path: str = None) -> UnstructuredKnowledgeTool:
    return UnstructuredKnowledgeTool(rag_config_path=rag_config_path)
__all__ = [
    "UnstructuredKnowledgeTool",
    "UnstructuredKnowledgeInput",
    "create_unstructured_knowledge_tool"
]