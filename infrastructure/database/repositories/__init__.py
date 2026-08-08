from .base_repository import BaseRepository
from .user_repository import UserRepository
from .system_config_repository import SystemConfigRepository
from .chat_repository import ChatRepository
from .agent_repository import AgentRepository
from .agent_relation_repository import AgentRelationRepository
from .api_repository import ApiRepository
from .mcp_repository import McpRepository
from .skill_repository import SkillRepository
from .mode_repository import ModeRepository
from .knowledge_repository import KnowledgeBaseRepository
from .sys_model_res_mgmt_repository import SysModelResMgmtRepository
from .smart_writing_repository import (
    WritingTemplateRepository,
    WritingDocumentRepository,
    template_repository,
    document_repository,
)
__all__ = [
    'BaseRepository',
    'UserRepository',
    'SystemConfigRepository',
    'ChatRepository',
    'AgentRepository',
    'AgentRelationRepository',
    'ApiRepository',
    'McpRepository',
    'SkillRepository',
    'ModeRepository',
    'KnowledgeBaseRepository',
    'SysModelResMgmtRepository',
    'WritingTemplateRepository',
    'WritingDocumentRepository',
    'template_repository',
    'document_repository',
]
SubAgentRepository = AgentRepository
HttpConfigRepository = ApiRepository
ExternalToolRepository = ApiRepository