from typing import Optional
from pydantic import BaseModel
from loguru import logger
from utils.common.auth_dependencies import verify_admin_token as verify_token  # noqa: F401  # re-export for admin routers
from core.subagent.registry import get_subagent_registry
class SubAgentConfig(BaseModel):
    name: str
    description: Optional[str] = ""
    display_name: Optional[str] = ""
    system_prompt: str
    tools: list[str] = []
    external_tools: list[str] = []
    model: Optional[str] = None
    mcp_tools: Optional[list[str]] = []
    visibility: Optional[str] = "private"  # 可见性 private/workspace/public（新建默认 private）
class AgentConfigNew(BaseModel):
    pr_key_id: str
    agent_name: str
    agent_description: str = ""
    model_id: Optional[str] = None
    system_prompt: str
    temperature: float = 0.7
    max_tokens: int = 2000
    response_timeout: int = 60
    visible_scope: str = "1"
    release_status: str = "1"
    version_no: str = "1.0.0"
    status: str = "1"
    tools: list[str] = []
    external_tools: list[str] = []
    mcp_tools: list[str] = []
class ToolConfigUpdate(BaseModel):
    display_name: Optional[str] = ""
    description: Optional[str] = ""
    parameter_descriptions: dict[str, str] = {}
    return_description: Optional[str] = ""
    examples: Optional[list[str]] = None
class ModeConfig(BaseModel):
    """模式配置（字段名与 ModeRepository.save_mode() 参数名一致）。

    字段映射到数据库列：
      mode_name        → dclr_ptn_name（模式名，主键标识）
      en_name           → en_name（英文名）
      mode_description  → thval_desc_desc（描述）
      system_prompt     → comprehe_sugg_content（追加到 system_prompt 的模式指引）
      recommended_agents→ rem_pers_name（推荐 Agent，逗号分隔字符串）
      priority_agent    → by_rem_pers_name（优先 Agent）
      enabled           → status（'1' 启用 / '0' 停用）
      mode_type         → mode_type（'Agent' 自定义 / '' 系统模式）
    """
    pr_key_id: Optional[str] = None
    mode_name: str
    en_name: str = ""
    mode_description: str = ""
    system_prompt: str
    recommended_agents: str = ""
    priority_agent: str = ""
    enabled: bool = True
    mode_type: str = "Agent"
def reload_config():
    """热重载所有运行时配置文件及关联缓存。

    覆盖的配置文件：
      - agent_config.json   — 主配置（LLM/Agent/Memory/RAG/Embedding/Database/Langfuse 等）
      - tools/*.json        — 工具描述配置

    调用链覆盖：
       1. ConfigLoader.reload()         — 重读 agent_config.json 到内存（含 database/langfuse 段）
       2. ToolRegistry.reload()         — 重载工具注册表（重读 tools/*.json）
       3. SubAgentRegistry.reload()     — 从 DB 重载子代理
       4. clear_query_cache()           — 清 LLM 实例缓存（使 api_key/temperature 等变更生效）
       5. reset_embedding_model()       — 重置 embedding 模型单例
       6. reset_memory_manager()        — 重置 MemoryManager 单例
       7. reset_langgraph_executor()    — 重置 LangGraph 执行器单例 + 编译图缓存
       8. LangfuseHandlerFactory.reset()— 重置 langfuse handler 单例
       9. load_langfuse_config_file(force_reload=True) — 强制重读 observability.langfuse 段
      10. load_db_config_file(force_reload=True)       — 强制重读 database 段
      11. reset_logging_cache()         — 重置 logging 配置缓存
      12. PermissionConfigLoader.reload_config()       — 重置权限缓存（兼容旧接口）
      13. reset_auth_provider()         — 重置认证 Provider
      14. reset_apollo_config()         — 重置 Apollo 配置 + 重建 client
      15. close_all_engines()           — 关闭并重建数据库引擎池
      16. reset_rag_system()            — 重置 RAGSystem 单例
      17. MysqlSaverFactory.reset()     — 重置 checkpoint saver 单例
      18. reset_textsql()               — 重置 TextSQL 单例
      19. clear_plan_cache()            — 清空 plan 缓存
       20. get_metadata_cache().clear_all() — 清空数据库元数据缓存
       21. reset_sandbox_provider()        — 重置 sandbox provider 单例
       22. 重启 memory 定时触发器          — memory.consolidation/decay/preference_summary 变更生效

    仍需重启的配置项：无（所有运行时配置项均已支持热重载）
    """
    try:
        from tools.registry import get_tool_registry
        get_tool_registry().reload()
        subagent_registry = get_subagent_registry()
        subagent_registry.reload()
        from utils.config import get_config_loader
        config_loader = get_config_loader()
        config_loader.reload()
        from utils.common.auth_providers import reset_auth_provider
        reset_auth_provider()
        logger.info("[Admin]  AuthProvider ")
        # 补全缓存刷新链路
        _reload_caches()
    except Exception as e:
        logger.error(f"[Admin] : {e}", exc_info=True)
        raise


def _reload_caches():
    """刷新所有在初始化时缓存了 agent_config 值的单例/模块级缓存。

    每项独立 try/except：单项失败不阻塞其余刷新。
    """
    # 1. 清 LLM 实例缓存（SimpleCache TTL=300s，否则改 api_key/temperature 不生效）
    try:
        from utils.common.cache import clear_query_cache
        clear_query_cache()
        logger.debug("[Admin] LLM  ")
    except Exception as e:
        logger.warning(f"[Admin] LLM  : {e}")

    # 2. 重置 embedding 模型单例
    try:
        from memory.embedding_factory import reset_embedding_model
        reset_embedding_model()
    except Exception as e:
        logger.warning(f"[Admin] embedding : {e}")

    # 3. 重置 MemoryManager 单例
    try:
        from memory.memory_manager import reset_memory_manager
        reset_memory_manager()
    except Exception as e:
        logger.warning(f"[Admin] MemoryManager : {e}")

    # 4. 重置 LangGraph 执行器单例 + 编译图缓存
    try:
        from executor.langgraph import reset_langgraph_executor
        reset_langgraph_executor()
    except Exception as e:
        logger.warning(f"[Admin] LangGraph : {e}")

    # 5. 重置 Langfuse handler 单例 + 强制重读 observability.langfuse 段
    try:
        from utils.observability.langfuse_handler import LangfuseHandlerFactory
        LangfuseHandlerFactory.reset()
        from utils.config.langfuse_config import load_langfuse_config_file
        load_langfuse_config_file(force_reload=True)
    except Exception as e:
        logger.warning(f"[Admin] Langfuse : {e}")

    # 6. 强制重读 database 段（原 db_config.json 已合并到 agent_config.json）
    try:
        from utils.config.db_config import load_db_config_file
        load_db_config_file(force_reload=True)
    except Exception as e:
        logger.warning(f"[Admin] db_config : {e}")

    # 7. 重置 logging 配置缓存
    try:
        from utils.common.logging_utils import reset_logging_cache
        reset_logging_cache()
    except Exception as e:
        logger.warning(f"[Admin] logging : {e}")

    # 8. 重置权限配置缓存（兼容旧接口，DB 模式无需缓存刷新）
    try:
        from utils.common.permissions import PermissionConfigLoader
        PermissionConfigLoader.reload_config()
    except Exception as e:
        logger.warning(f"[Admin] permissions : {e}")

    # 9. 重置 Apollo 配置缓存（apollo.* 段）
    try:
        from utils.config.apollo_config import reset_apollo_config
        reset_apollo_config()
    except Exception as e:
        logger.warning(f"[Admin] apollo : {e}")

    # 10. 关闭并重建数据库引擎池（database 段变更后连接串可能变化）
    try:
        from infrastructure.database.engines import close_all_engines
        close_all_engines()
    except Exception as e:
        logger.warning(f"[Admin] DB engines : {e}")

    # 11. 重置 RAGSystem 单例（rag.* 配置变更后重建）
    try:
        from api.rag.rag_routes import reset_rag_system
        reset_rag_system()
    except Exception as e:
        logger.warning(f"[Admin] RAGSystem : {e}")

    # 12. 重置 MySQL checkpoint saver 单例
    try:
        from utils.checkpoint.mysql_saver_factory import MysqlSaverFactory
        MysqlSaverFactory.reset()
    except Exception as e:
        logger.warning(f"[Admin] MysqlSaver : {e}")

    # 13. 重置 TextSQL 单例（database 段变更后重建）
    try:
        from db_skills.text2sql.factory import reset_textsql
        reset_textsql()
    except Exception as e:
        logger.warning(f"[Admin] TextSQL : {e}")

    # 14. 清空 plan 缓存（LLM/planner 配置变更后旧 plan 可能不适用）
    try:
        from utils.planning.generator import clear_plan_cache
        clear_plan_cache()
    except Exception as e:
        logger.warning(f"[Admin] plan cache : {e}")

    # 15. 清空数据库元数据缓存（database 段变更后表结构可能变化）
    try:
        from infrastructure.database.metadata.metadata_cache import get_metadata_cache
        get_metadata_cache().clear_all()
    except Exception as e:
        logger.warning(f"[Admin] metadata cache : {e}")

    # 16. 重置 sandbox provider 单例（sandbox.* 变更后重建）
    try:
        from infrastructure.sandbox.sandbox_provider import reset_sandbox_provider
        reset_sandbox_provider()
    except Exception as e:
        logger.warning(f"[Admin] sandbox provider : {e}")

    # 17. 重启 memory 定时触发器（memory.consolidation/decay/preference_summary 变更后生效）
    try:
        from services.trigger.memory_decay_trigger import MemoryDecayTrigger
        from services.trigger.memory_consolidation_trigger import MemoryConsolidationTrigger
        from services.trigger.memory_preference_summary_trigger import MemoryPreferenceSummaryTrigger
        # start() 内部 replace_existing=True，会替换旧的 APScheduler job
        import asyncio as _aio
        _aio.get_event_loop().create_task(MemoryDecayTrigger().start())
        _aio.get_event_loop().create_task(MemoryConsolidationTrigger().start())
        _aio.get_event_loop().create_task(MemoryPreferenceSummaryTrigger().start())
    except Exception as e:
        logger.warning(f"[Admin] memory triggers : {e}")