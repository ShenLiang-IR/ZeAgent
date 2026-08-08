from loguru import logger
import asyncio
from typing import Optional, Any, Dict, List
from utils.config import get_config
from .tool_collector import collect_subagent_tools_async, collect_all_tools_async
from utils.planning.prompt_builder import build_execution_prompt as _build_execution_prompt
def build_execution_prompt(
    base_prompt: str,
    response_mode: Optional[str] = None,
    enable_quality: bool = True,
    enable_efficiency: bool = True,
    disable_thinking: bool = False,
    context_focus: Optional[str] = None
) -> str:
    return _build_execution_prompt(
        base_prompt=base_prompt,
        response_mode=response_mode,
        enable_quality=enable_quality,
        enable_efficiency=enable_efficiency,
        disable_thinking=disable_thinking,
        context_focus=context_focus,
        execution_context="agent"
    )
def _get_read_file_tool():
    try:
        from tools.skill_file_tool import read_file
        return read_file
    except (ImportError, ValueError) as e:
        logger.debug(f"[build_graph] read_file : {e}")
        return None
def _ensure_skill_file_reader_initialized():
    """初始化 SkillFileReader 单例（若尚未创建）。

    使用 create_skill_storages() 共享工厂消除重复存储层初始化代码，
    兼容 Windows 和 macOS 路径分隔符。
    """
    try:
        from tools.skill_file_tool import get_skill_file_reader, set_skill_file_reader
        reader = get_skill_file_reader()
        if reader is not None:
            return reader
        from domain.skill.skill_file_reader import SkillFileReader
        from domain.skill.storage import create_skill_storages, LocalSkillStorage, DatabaseSkillStorage

        storages = create_skill_storages(caller_file=__file__)
        # 从 storages 中分离 db 和 disk 引用
        db_storage = next((s for s in storages if isinstance(s, DatabaseSkillStorage)), None)
        disk_storage = next((s for s in storages if isinstance(s, LocalSkillStorage)), None)

        reader = SkillFileReader(disk_storage=disk_storage, db_storage=db_storage)
        reader.load_skills()
        set_skill_file_reader(reader)
        logger.info(f"[build_graph] SkillFileReader ")
        return reader
    except Exception as e:
        logger.warning(f"[build_graph] SkillFileReader : {e}")
        return None
async def build_graph(
    session_id: str = "default",
    tools: Optional[list] = None,
    system_prompt: Optional[str] = None,
    subagent_name: Optional[str] = None,
    chat_model: Optional[Any] = None,
    deep_thinking: bool = False,
    response_mode: Optional[str] = None,
    enable_skills_middleware: bool = True,
    skill_ids: Optional[List[str]] = None,
    subagent_config: Optional[Dict[str, Any]] = None
) -> Optional[Any]:
    logger.info(f"[build_graph]  | subagent={subagent_name}, deep_thinking={deep_thinking}, response_mode={response_mode}")
    try:
        from utils.config import get_config_db
        from .agent_factory import LangGraphAgentFactory, DeepAgentFactory
        if skill_ids is None:
            skill_ids = []
        if subagent_config is None and subagent_name:
            config_db = get_config_db()
            # P2-1: 同步 DB 查询卸载到线程池，避免阻塞事件循环（同 P2-10 模式）
            subagent_config = await asyncio.to_thread(config_db.subagents.get_by_name, subagent_name)
            if not subagent_config:
                logger.error(f"SubAgent {subagent_name} ")
                return None
        if tools is None or system_prompt is None:
            if subagent_config:
                if tools is None:
                    agent_pr_key_id = subagent_config.get('pr_key_id')
                    tools, skill_index_text, skill_ids = await collect_subagent_tools_async(
                        subagent_config, agent_pr_key_id, return_skill_ids=True
                    )
                else:
                    skill_index_text = ""
                if system_prompt is None:
                    system_prompt = subagent_config.get('system_prompt', '')
                    if not system_prompt:
                        system_prompt = f"You are a helpful assistant specialized in {subagent_config.get('description', '')}"
                if skill_index_text and not enable_skills_middleware:
                    system_prompt = f"{system_prompt}\n\n{skill_index_text}"
            else:
                if tools is None:
                    tools, skill_index_text, skill_ids = await collect_all_tools_async(return_skill_ids=True)
                else:
                    skill_index_text = ""
                if system_prompt is None:
                    config_db = get_config_db()
                    # P2-1: 同步 DB 查询卸载到线程池，避免阻塞事件循环
                    system_prompt = (await asyncio.to_thread(config_db.get_system_description)) or ""
                    if not system_prompt:
                        system_prompt = "You are a helpful AI assistant. Answer questions accurately and concisely."
                if skill_index_text and not enable_skills_middleware:
                    system_prompt = f"{system_prompt}\n\n{skill_index_text}"
        has_skills = bool(skill_ids)
        sandbox_enabled = False
        try:
            from infrastructure.sandbox import is_sandbox_enabled
            sandbox_enabled = is_sandbox_enabled()
        except Exception:
            pass
        if has_skills or sandbox_enabled:
            if has_skills:
                _ensure_skill_file_reader_initialized()
            try:
                from tools.skill_file_tool import set_current_session_id
                set_current_session_id(session_id)
            except Exception:
                pass
            read_tool = _get_read_file_tool()
            if read_tool and read_tool not in tools:
                tools = list(tools) + [read_tool]
                logger.info(f"[build_graph]  read_file  (skills={has_skills}, sandbox={sandbox_enabled}, session={session_id})")
        if '<quality_assurance>' in system_prompt and '<efficiency>' in system_prompt:
            logger.debug("[build_graph] system_prompt ")
        else:
            prompt_options = (subagent_config or {}).get('prompt_options', {})
            enable_quality = prompt_options.get('quality', True)
            enable_efficiency = prompt_options.get('efficiency', True)
            disable_thinking = False if deep_thinking else get_config('agent.react.disable_thinking', False)
            system_prompt = build_execution_prompt(
                base_prompt=system_prompt,
                response_mode=response_mode,
                enable_quality=enable_quality,
                enable_efficiency=enable_efficiency,
                disable_thinking=disable_thinking
            )
        if chat_model is None:
            from utils.llm import get_default_llm
            chat_model = get_default_llm()
        if subagent_config:
            from utils.llm.llm_factory import resolve_llm_by_model_id
            chat_model = resolve_llm_by_model_id(subagent_config, chat_model)
        middleware_list = []
        context_compression_enabled = get_config('context.compression_enabled', True)
        if context_compression_enabled:
            from core.middleware import create_context_editing_middleware
            middleware_list.append(create_context_editing_middleware(
                trigger=get_config('context.edit_trigger', 50000),
                keep=get_config('context.edit_keep', 3)
            ))
        from core.middleware import CleanThinkMiddleware
        middleware_list.append(CleanThinkMiddleware(
            subagent_name=subagent_name or "default",
            system_prompt=system_prompt or ""
        ))
        # checkpointer：单 agent 对话统一启用 checkpoint（step_monitor 控制）
        # 修复"普通 LangGraphAgentFactory 模式无 checkpointer"问题——
        # ReActExecutor 已传 thread_id（react_executor.py L34），可安全启用
        checkpointer = None
        step_monitor_enabled = get_config('agent.langgraph.step_monitor', True)
        if step_monitor_enabled:
            try:
                from langgraph.checkpoint.memory import MemorySaver
                checkpointer = MemorySaver()
            except ImportError:
                pass
        if deep_thinking:
            factory = DeepAgentFactory()
        else:
            factory = LangGraphAgentFactory()
        skill_prompt_generator = None
        if has_skills:
            try:
                from domain.skill.registry import get_skill_registry
                registry = await get_skill_registry()
                skill_prompt_generator = registry.get_prompt_generator()
            except Exception as e:
                logger.debug(f"[build_graph]  SkillPromptGenerator : {e}")
        if sandbox_enabled:
            try:
                from tools.sandbox_tools import get_sandbox_tools
                sandbox_tools = get_sandbox_tools()
                tools = list(tools) + sandbox_tools
                logger.debug(f"[build_graph] 注入 {len(sandbox_tools)} 个沙箱工具")
            except Exception as e:
                logger.debug(f"[build_graph] 沙箱工具注入失败: {e}")
        else:
            # 沙箱未启用：仍注入 write_file + list_dir（降级为直接本地操作）
            try:
                from tools.sandbox_tools import write_file, list_dir
                file_tools = [write_file, list_dir]
                tools = list(tools) + file_tools
                logger.debug(f"[build_graph] 注入 {len(file_tools)} 个文件工具（无沙箱模式）")
            except Exception as e:
                logger.debug(f"[build_graph] 文件工具注入失败: {e}")
        factory_kwargs = {
            'model': chat_model,
            'tools': tools,
            'system_prompt': system_prompt,
            'middleware': middleware_list,
        }
        if checkpointer:
            factory_kwargs['checkpointer'] = checkpointer
        if skill_prompt_generator:
            factory_kwargs['skill_prompt_generator'] = skill_prompt_generator
        compiled_graph = factory.create(**factory_kwargs)
        logger.info(f"[build_graph]  | subagent={subagent_name}, tools={len(tools)}, skills={len(skill_ids)}, deep_thinking={deep_thinking}")
        return compiled_graph
    except Exception as e:
        logger.error(f"[build_graph] : {str(e)}", exc_info=True)
        return None