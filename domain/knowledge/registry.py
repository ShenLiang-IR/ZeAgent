from typing import List, Dict, Optional, Set
from loguru import logger
from .entities import KnowledgeMetadata, KnowledgeType
from .lazy_knowledge import LazyKnowledgeProxy
from utils.common.cache import TTLCacheMixin
class KnowledgeRegistry(TTLCacheMixin):
    def __init__(self, repository, doc_repository, sql_model_repository):
        self._repository = repository
        self._doc_repository = doc_repository
        self._sql_model_repository = sql_model_repository
        self._metadata: Dict[str, KnowledgeMetadata] = {}
        self._by_type: Dict[KnowledgeType, Set[str]] = {
            KnowledgeType.UNSTRUCTURED: set(),
            KnowledgeType.STRUCTURED: set(),
        }
        self._proxy_cache: Dict[str, LazyKnowledgeProxy] = {}
        self._initialized = False
    async def initialize(self) -> None:
        if self._initialized:
            logger.warning("[] ")
            return
        logger.info("[] ...")
        try:
            self._load_from_db()
            self._initialized = True
        except Exception as e:
            logger.error(f"[] : {e}", exc_info=True)
            raise
    def _load_from_db(self) -> None:
        knowledge_bases = self._repository.get_all(enabled_only=True)
        if not knowledge_bases:
            logger.warning("[] ")
            return
        logger.info(f"[]  {len(knowledge_bases)} ")
        loaded_kb_ids = []
        for kb_data in knowledge_bases:
            kb_id = kb_data.get("knowledge_base_id")
            kb_name = kb_data.get("knowledge_name", kb_id)
            kb_type = kb_data.get("knowledge_type", "0")
            try:
                documents = []
                sql_models = []
                if kb_type == KnowledgeType.UNSTRUCTURED.value:
                    documents = self._doc_repository.get_by_kb(kb_id, status='completed')
                elif kb_type == KnowledgeType.STRUCTURED.value:
                    sql_models = self._sql_model_repository.get_by_kb(kb_id)
                metadata = KnowledgeMetadata.from_database(
                    kb_data,
                    documents=documents,
                    sql_models=sql_models
                )
                self._metadata[kb_id] = metadata
                self._by_type[metadata.knowledge_type].add(kb_id)
                loaded_kb_ids.append(kb_id)
                logger.info(
                    f"[] : {kb_id} ({kb_name}), "
                    f"={KnowledgeType.to_display_name(kb_type)}, "
                    f"={len(documents)}, SQL={len(sql_models)}"
                )
            except Exception as e:
                logger.error(
                    f"[]  {kb_id} : {e}",
                    exc_info=True
                )
                continue
        self._mark_loaded()
        logger.info(
            f"[]  {len(self._metadata)} : "
            f"{', '.join(loaded_kb_ids)}"
        )
    def _clear_cache(self) -> None:
        self._metadata.clear()
        self._by_type = {
            KnowledgeType.UNSTRUCTURED: set(),
            KnowledgeType.STRUCTURED: set(),
        }
        self._proxy_cache.clear()
        self._initialized = False
    def _ensure_loaded(self) -> None:
        if not self._initialized:
            self._load_from_db()
            self._initialized = True
    def search_by_type(self, knowledge_type: KnowledgeType) -> List[KnowledgeMetadata]:
        self._invalidate_if_expired()
        self._ensure_loaded()
        ids = self._by_type.get(knowledge_type, set())
        return [self._metadata[kid] for kid in ids if kid in self._metadata]
    def get_by_id(self, knowledge_base_id: str) -> Optional[KnowledgeMetadata]:
        self._invalidate_if_expired()
        self._ensure_loaded()
        return self._metadata.get(knowledge_base_id)
    def get_by_name(self, knowledge_name: str) -> Optional[KnowledgeMetadata]:
        self._invalidate_if_expired()
        self._ensure_loaded()
        for metadata in self._metadata.values():
            if metadata.knowledge_name == knowledge_name:
                return metadata
        return None
    def get_all_metadata(self) -> List[KnowledgeMetadata]:
        self._invalidate_if_expired()
        self._ensure_loaded()
        return list(self._metadata.values())
    def get_agent_knowledge_tools(
        self,
        agent_pr_key_id: str,
        agent_relation_repo
    ) -> List:
        self._invalidate_if_expired()
        self._ensure_loaded()
        try:
            kb_pr_key_ids = agent_relation_repo.get_knowledge_base_ids(agent_pr_key_id)
            logger.info(
                f"[] Agent {agent_pr_key_id}  {len(kb_pr_key_ids)}  "
                f"(pr_key_ids: {kb_pr_key_ids})"
            )
            if not kb_pr_key_ids:
                return []
            bound_metadata_list = []
            for pr_key_id in kb_pr_key_ids:
                for metadata in self._metadata.values():
                    if metadata.pr_key_id == pr_key_id:
                        bound_metadata_list.append(metadata)
                        break
            if not bound_metadata_list:
                logger.warning(
                    f"[] Agent {agent_pr_key_id} "
                )
                return []
            cache_key = ",".join(sorted([m.knowledge_base_id for m in bound_metadata_list]))
            if cache_key in self._proxy_cache:
                proxy = self._proxy_cache[cache_key]
            else:
                proxy = LazyKnowledgeProxy(bound_metadata_list)
                self._proxy_cache[cache_key] = proxy
            tools = proxy.to_langchain_tools()
            logger.info(
                f"[] Agent {agent_pr_key_id}  {len(tools)} "
            )
            return tools
        except Exception as e:
            logger.error(
                f"[]  Agent {agent_pr_key_id} : {e}",
                exc_info=True
            )
            return []
    def get_bound_metadata(self, agent_pr_key_id: str) -> list:
        self._invalidate_if_expired()
        self._ensure_loaded()
        try:
            from infrastructure.database.repositories.agent_relation_repository import AgentRelationRepository
            repo = AgentRelationRepository()
            kb_pr_key_ids = repo.get_knowledge_base_ids(agent_pr_key_id)
            return [
                m for m in self._metadata.values()
                if m.pr_key_id in kb_pr_key_ids
            ]
        except Exception:
            return []
    def get_all_langchain_tools(self) -> List:
        self._invalidate_if_expired()
        self._ensure_loaded()
        if not self._metadata:
            return []
        proxy = LazyKnowledgeProxy(list(self._metadata.values()))
        return proxy.to_langchain_tools()
    def reload(self) -> None:
        logger.info("[] ...")
        self._clear_cache()
        self._load_from_db()
        self._initialized = True
        logger.info("[] ")
    def clear_proxy_cache(self) -> None:
        self._proxy_cache.clear()
        logger.info("[] ")
    @property
    def is_initialized(self) -> bool:
        return self._initialized
    @property
    def knowledge_count(self) -> int:
        return len(self._metadata)
    @property
    def structured_count(self) -> int:
        return len(self._by_type[KnowledgeType.STRUCTURED])
    @property
    def unstructured_count(self) -> int:
        return len(self._by_type[KnowledgeType.UNSTRUCTURED])
_registry: Optional[KnowledgeRegistry] = None
async def get_knowledge_registry() -> KnowledgeRegistry:
    global _registry
    if _registry is None:
        from infrastructure.database.repositories.knowledge_repository import (
            KnowledgeBaseRepository,
            KnowledgeBaseDocumentRepository,
            KnowledgeBaseSqlModelRepository
        )
        repository = KnowledgeBaseRepository()
        doc_repository = KnowledgeBaseDocumentRepository()
        sql_model_repository = KnowledgeBaseSqlModelRepository()
        _registry = KnowledgeRegistry(
            repository,
            doc_repository,
            sql_model_repository
        )
        await _registry.initialize()
    return _registry
def reset_knowledge_registry() -> None:
    global _registry
    _registry = None