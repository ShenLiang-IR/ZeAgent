from .structured_knowledge_tool import StructuredKnowledgeTool
def create_structured_knowledge_tool() -> StructuredKnowledgeTool:
    from utils.config import get_config
    from loguru import logger
    api_base_url = "http://localhost:8001"
    api_headers = {}
    try:
        config = get_config()
        api_base_url = config.get('knowledge.api_base_url', 'http://localhost:8001')
        api_headers = config.get('knowledge.api_headers', {})
        logger.info(f"[StructuredKnowledge] API: {api_base_url}")
    except Exception as e:
        logger.warning(f"[StructuredKnowledge] API: {str(e)}")
    return StructuredKnowledgeTool(
        api_base_url=api_base_url,
        api_headers=api_headers
    )
__all__ = ['StructuredKnowledgeTool', 'create_structured_knowledge_tool']