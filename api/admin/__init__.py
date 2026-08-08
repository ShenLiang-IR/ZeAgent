from fastapi import APIRouter
from .subagent import router as subagent_router
from .tools import router as tools_router
from .config import router as config_router
from .external_tools import router as external_tools_router
from .mode import router as mode_router
from .skill import router as skill_router
from .agent_manage import router as agent_manage_router
from .node_manage import router as node_manage_router
from .api_manage import router as api_manage_router
from .menu import router as menu_router
from .model_resource import router as model_resource_router
from .dict import router as dict_router
from .rls_rule import router as rls_rule_router
from .smart_agent_adapter import router as smart_agent_router
from .mcp import router as mcp_router
from .observability import router as observability_router
from .trigger import router as trigger_router, webhook_router as trigger_webhook_router
from .audit import router as audit_router
from .usage import router as usage_router, quota_router as usage_quota_router
from .eval import router as eval_router
from .agent_version import router as agent_version_router
from .prompt_template import router as prompt_template_router
from .kb_version import router as kb_version_router
from .agent_team import router as agent_team_router, mailbox_router
from .event_subscription import router as event_subscription_router
from .memory import router as memory_router
from .dashboard import router as dashboard_router
from .plugin_marketplace import router as plugin_router
from .security_routes import router as security_router

admin_router = APIRouter(prefix="/api/admin", tags=["admin"])
admin_router.include_router(subagent_router)
admin_router.include_router(tools_router)
admin_router.include_router(config_router)
admin_router.include_router(external_tools_router)
admin_router.include_router(mode_router)
admin_router.include_router(skill_router)
admin_router.include_router(agent_manage_router)
admin_router.include_router(node_manage_router)
admin_router.include_router(api_manage_router)
admin_router.include_router(menu_router)
admin_router.include_router(model_resource_router)
admin_router.include_router(dict_router)
admin_router.include_router(rls_rule_router)
admin_router.include_router(smart_agent_router)
admin_router.include_router(mcp_router)
admin_router.include_router(observability_router)
admin_router.include_router(trigger_router)
admin_router.include_router(trigger_webhook_router)
admin_router.include_router(audit_router)
admin_router.include_router(usage_router)
admin_router.include_router(usage_quota_router)
admin_router.include_router(eval_router)
admin_router.include_router(agent_version_router)
admin_router.include_router(prompt_template_router)
admin_router.include_router(kb_version_router)
admin_router.include_router(agent_team_router)
admin_router.include_router(mailbox_router)
admin_router.include_router(event_subscription_router)
admin_router.include_router(memory_router)
admin_router.include_router(dashboard_router)
admin_router.include_router(plugin_router)
admin_router.include_router(security_router)

from .common import (
    verify_token,
    reload_config,
    SubAgentConfig,
    ToolConfigUpdate,
    ModeConfig
)
__all__ = [
    'admin_router',
    'verify_token',
    'reload_config',
    'SubAgentConfig',
    'ToolConfigUpdate',
    'ModeConfig'
]
