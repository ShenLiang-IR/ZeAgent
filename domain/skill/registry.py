from typing import List, Dict, Optional, Set, TYPE_CHECKING
from loguru import logger
from .entities import SkillMetadata, SkillCategory
from .lazy_skill import LazySkillProxy
from .prompt import SkillPromptGenerator
from utils.common.cache import TTLCacheMixin
if TYPE_CHECKING:
    from .loader import SkillLoader
class SkillRegistry(TTLCacheMixin):
    def __init__(self, repository, loader: "SkillLoader"):
        self._repository = repository
        self._loader = loader
        self._metadata: Dict[str, SkillMetadata] = {}
        self._proxies: Dict[str, LazySkillProxy] = {}
        self._by_category: Dict[SkillCategory, Set[str]] = {
            cat: set() for cat in SkillCategory
        }
        self._preload_list: List[str] = []
        self._initialized = False
        self._prompt_generator: Optional[SkillPromptGenerator] = None
    async def initialize(self) -> None:
        if self._initialized:
            logger.warning("[] ")
            return
        logger.info("[] ...")
        try:
            self._load_from_db()
            self._init_prompt_generator()
            if self._preload_list:
                await self._preload_high_priority_skills()
            self._initialized = True
        except Exception as e:
            logger.error(f"[] : {e}", exc_info=True)
            raise
    def _load_from_db(self) -> None:
        skills_data = self._repository.get_all(enabled_only=True)
        if not skills_data:
            logger.warning("[] ")
            return
        logger.info(f"[]  {len(skills_data)} ")
        loaded_skill_ids = []
        for skill_data in skills_data:
            skill_id = skill_data["skill_id"]
            skill_name = skill_data.get("skill_name", skill_id)
            try:
                metadata = SkillMetadata.from_database(skill_data)
                self._metadata[skill_id] = metadata
                self._proxies[skill_id] = LazySkillProxy(metadata, self._loader)
                self._by_category[metadata.category].add(skill_id)
                if metadata.preload_priority > 0:
                    self._preload_list.append((skill_id, metadata.preload_priority))
                loaded_skill_ids.append(skill_id)
                logger.info(f"[] : {skill_id} ({skill_name})")
            except Exception as e:
                logger.error(
                    f"[]  {skill_id} : {e}",
                    exc_info=True
                )
                continue
        self._preload_list.sort(key=lambda x: x[1], reverse=True)
        self._preload_list = [skill_id for skill_id, _ in self._preload_list]
        self._mark_loaded()
        logger.info(
            f"[]  {len(self._metadata)} : {', '.join(loaded_skill_ids)}"
        )
    def _init_prompt_generator(self) -> None:
        from .storage import create_skill_storages
        storages = create_skill_storages(caller_file=__file__, db_repository=self._repository)
        self._prompt_generator = SkillPromptGenerator(storages)
        self._prompt_generator.load_skills(enabled_only=True)
        disk_count = len(self._prompt_generator.get_disk_skills())
        db_count = len(self._prompt_generator.get_database_skills())
        logger.info(
            f"[] : "
            f"={disk_count}, ={db_count}"
        )
    def _clear_cache(self) -> None:
        self._metadata.clear()
        self._proxies.clear()
        self._by_category = {cat: set() for cat in SkillCategory}
        self._preload_list = []
        self._initialized = False
        self._prompt_generator = None
    def _ensure_loaded(self) -> None:
        if not self._initialized:
            self._load_from_db()
            self._init_prompt_generator()
            self._initialized = True
    async def _preload_high_priority_skills(self) -> None:
        logger.info(f"[SkillRegistry]  {len(self._preload_list)} ...")
        success_count = 0
        for skill_id in self._preload_list:
            proxy = self._proxies.get(skill_id)
            if proxy:
                try:
                    await proxy.preload()
                    success_count += 1
                except Exception as e:
                    logger.warning(
                        f"[SkillRegistry]  {skill_id} : {e}"
                    )
        logger.info(
            f"[SkillRegistry]  {success_count}/{len(self._preload_list)}"
        )
    def search_by_category(self, category: SkillCategory) -> List[SkillMetadata]:
        self._invalidate_if_expired()
        self._ensure_loaded()
        ids = self._by_category.get(category, set())
        return [self._metadata[sid] for sid in ids if sid in self._metadata]
    def get_by_id(self, skill_id: str) -> Optional[SkillMetadata]:
        self._invalidate_if_expired()
        self._ensure_loaded()
        return self._metadata.get(skill_id)
    def get_proxy(self, skill_id: str) -> Optional[LazySkillProxy]:
        self._invalidate_if_expired()
        self._ensure_loaded()
        return self._proxies.get(skill_id)
    def get_all_metadata(self) -> List[SkillMetadata]:
        self._invalidate_if_expired()
        self._ensure_loaded()
        return list(self._metadata.values())
    def get_all_langchain_tools(self) -> List:
        self._invalidate_if_expired()
        self._ensure_loaded()
        tools = []
        for proxy in self._proxies.values():
            try:
                tool = proxy.to_langchain_tool()
                tools.append(tool)
            except Exception as e:
                logger.warning(
                    f"[SkillRegistry]  {proxy.metadata.skill_id}  Tool : {e}"
                )
        return tools
    def get_agent_skills(self, agent_pr_key_id: str, agent_relation_repo) -> List:
        self._invalidate_if_expired()
        self._ensure_loaded()
        try:
            from infrastructure.database.repositories.skill_repository import SkillRepository
            pr_key_ids = agent_relation_repo.get_skill_ids(agent_pr_key_id)
            logger.info(f"[] Agent {agent_pr_key_id}  {len(pr_key_ids)}  (pr_key_ids: {pr_key_ids})")
            skill_repo = SkillRepository()
            pr_key_to_skill_id = {}
            for pr_key_id in pr_key_ids:
                skill_data = skill_repo.get_by_id(pr_key_id, return_dict=True)
                if skill_data:
                    pr_key_to_skill_id[pr_key_id] = skill_data.get('skill_id')
            mcp_ids = agent_relation_repo.get_mcp_ids(agent_pr_key_id)
            api_ids = agent_relation_repo.get_api_ids(agent_pr_key_id)
            kb_ids = agent_relation_repo.get_knowledge_base_ids(agent_pr_key_id)
            resource_context = {
                "mcp_ids": mcp_ids or [],
                "api_ids": api_ids or [],
                "kb_ids": kb_ids or [],
            }
            logger.info(
                f"[] Agent {agent_pr_key_id} : MCP={len(mcp_ids or [])} , API={len(api_ids or [])} , KB={len(kb_ids or [])} "
            )
            tools = []
            for pr_key_id, skill_id in pr_key_to_skill_id.items():
                proxy = self._proxies.get(skill_id)
                if proxy:
                    try:
                        tool = proxy.to_langchain_tool(
                            agent_id=agent_pr_key_id,
                            resource_context=resource_context
                        )
                        tools.append(tool)
                        logger.info(f"[] : {skill_id} (: {tool.name}, agent_pr_key_id: {agent_pr_key_id})")
                    except Exception as e:
                        logger.warning(
                            f"[]  Agent {agent_pr_key_id}  {skill_id} (pr_key_id={pr_key_id}) : {e}"
                        )
                else:
                    logger.warning(f"[]  {skill_id}  (pr_key_id={pr_key_id})")
            logger.info(f"[] Agent {agent_pr_key_id}  {len(tools)} ")
            return tools
        except Exception as e:
            logger.error(
                f"[]  Agent {agent_pr_key_id} : {e}",
                exc_info=True
            )
            return []
    def get_prompt_generator(self) -> Optional[SkillPromptGenerator]:
        return self._prompt_generator
    def generate_skill_prompt(self) -> str:
        if self._prompt_generator:
            return self._prompt_generator.generate_full_section()
        return ""
    def reload(self, skill_id: str = None) -> None:
        logger.info("[] ...")
        self._clear_cache()
        self._load_from_db()
        self._init_prompt_generator()
        self._initialized = True
        logger.info("[] ")
    @property
    def is_initialized(self) -> bool:
        return self._initialized
    @property
    def skill_count(self) -> int:
        return len(self._metadata)
_registry: Optional[SkillRegistry] = None
async def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        from infrastructure.database.repositories.skill_repository import SkillRepository
        from .loader import SkillLoader
        repository = SkillRepository()
        loader = SkillLoader()
        _registry = SkillRegistry(repository, loader)
        await _registry.initialize()
    return _registry
def reset_skill_registry() -> None:
    global _registry
    _registry = None