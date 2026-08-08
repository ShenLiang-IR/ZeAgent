"""记忆管理器（MemoryManager）：三层记忆编排 + 混合检索 + 冲突检测 + 审计回滚。"""
import threading
from typing import Any, Dict, List, Optional
from loguru import logger
from .blocks import MemoryBlock
from .hybrid_search import HybridMemorySearch, HybridSearchConfig
from .tiers import ImmediateMemory, ShortTermMemory, LongTermMemory


class MemoryManager:
    _instance: Optional["MemoryManager"] = None
    _lock = threading.Lock()
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    def __init__(
        self,
        immediate_size: int = 100,
        short_term_size: int = 1000,
        long_term_size: int = 10000,
        short_term_ttl_hours: int = 24,
        auto_promote: bool = True,
        vector_backend: Optional[str] = None,
        vector_config: Optional[Dict[str, Any]] = None,
        use_hybrid_search: bool = True,
        hybrid_config: Optional[Dict[str, Any]] = None,
        sqlite_db_path: str = "data/memory.db",
        conflict_promote_threshold: Optional[float] = None
    ):
        if hasattr(self, '_initialized') and self._initialized:
            return
        from .storage import SQLiteStorage
        shared_storage = SQLiteStorage(db_path=sqlite_db_path)
        self._sqlite_storage = shared_storage
        self.immediate = ImmediateMemory(max_size=immediate_size, storage=shared_storage)
        self.short_term = ShortTermMemory(
            max_size=short_term_size,
            ttl_hours=short_term_ttl_hours,
            storage=shared_storage
        )
        self.long_term = LongTermMemory(
            max_size=long_term_size,
            vector_backend=vector_backend,
            vector_config=vector_config,
            storage=shared_storage
        )
        self._tiers_loaded = False
        self.auto_promote = auto_promote
        # recall 效果统计（进程级累计，供 admin 可观测）
        self._recall_stats = {"total": 0, "hits": 0, "fallback": 0,
                              "by_tier": {"immediate": 0, "short_term": 0, "long_term": 0}}
        # 冲突检测门槛：默认 0.8，可配下沉覆盖中重要度重复去重
        from utils.config import get_config as _get_cfg
        if conflict_promote_threshold is not None:
            self._conflict_promote_threshold = float(conflict_promote_threshold)
        else:
            self._conflict_promote_threshold = float(
                _get_cfg("memory.conflict_resolution.promote_threshold", 0.8) or 0.8)
        self._use_hybrid_search = use_hybrid_search
        self._hybrid_searchers: Dict[str, HybridMemorySearch] = {}
        self._hybrid_config = HybridSearchConfig.from_dict(hybrid_config or {})
        from utils.config import get_config
        cr_cfg = get_config("memory.conflict_resolution", {}) or {}
        self._conflict_resolution_enabled = bool(cr_cfg.get("enabled", True))
        if self._conflict_resolution_enabled:
            from .conflict_resolver import ConflictResolver
            self._conflict_resolver = ConflictResolver(
                similarity_threshold=float(cr_cfg.get("similarity_threshold", 0.6)),
                max_candidates=int(cr_cfg.get("max_candidates", 5)),
            )
        else:
            self._conflict_resolver = None
        self._initialized = True
        logger.info(
            f"[MemoryManager]  | "
            f"immediate={immediate_size}, short_term={short_term_size}, "
            f"long_term={long_term_size}, vector_backend={vector_backend}, "
            f"hybrid_search={use_hybrid_search}, "
            f"conflict_resolution={self._conflict_resolution_enabled}"
        )
    async def remember(
        self,
        content: str,
        type: str = "note",
        importance: float = 0.5,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        source_session_id: Optional[str] = None,
        source_message_id: Optional[str] = None
    ) -> MemoryBlock:
        from .blocks import create_memory_block
        logger.debug(
            f"[MemoryManager] remember() : type={type}, "
            f"importance={importance:.2f}, content_len={len(content)}, "
            f"source_message_id={source_message_id}"
        )
        memory = create_memory_block(
            content=content,
            type=type,
            importance=importance,
            session_id=session_id,
            user_id=user_id,
            workspace_id=workspace_id,
            tags=tags,
            metadata=metadata,
            source_session_id=source_session_id,
            source_message_id=source_message_id,
        )
        target_long_term = importance >= self._conflict_promote_threshold
        if (self._conflict_resolution_enabled and self._conflict_resolver is not None
                and target_long_term):
            applied = await self._apply_conflict_resolution(memory, user_id)
            if applied:
                # 冲突 UPDATE/MERGE 改了 target 内容，long_term searcher 需重建
                self.invalidate_search_index("long_term")
                return memory
        if importance >= self._conflict_promote_threshold:
            await self.long_term.add(memory)
            written_tier = "long_term"
            logger.debug(f"[MemoryManager] : {content[:50]}...")
        elif importance >= 0.5:
            # 短期层去重：同 user 同 content 已存则跳过（防 LLM 重复提取膨胀）
            dup = await self._find_duplicate_short_term(memory)
            if dup:
                logger.debug(f"[MemoryManager] 短期层去重，跳过: {content[:50]}...")
                self._incremental_index_update("short_term", dup)
                return dup
            await self.short_term.add(memory)
            written_tier = "short_term"
            logger.debug(f"[MemoryManager] : {content[:50]}...")
        else:
            await self.immediate.add(memory)
            written_tier = "immediate"
            logger.debug(f"[MemoryManager] : {content[:50]}...")
        # 增量更新受影响 searcher（替代全清重建）
        await self._incremental_index_update(written_tier, memory)
        return memory
    async def recall(
        self,
        query: str,
        limit: int = 10,
        tiers: Optional[List[str]] = None,
        use_hybrid: Optional[bool] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None
    ) -> List[MemoryBlock]:
        tiers = tiers or ["immediate", "short_term", "long_term"]
        use_hybrid = use_hybrid if use_hybrid is not None else self._use_hybrid_search
        from utils.config import get_config
        cross_session = get_config('memory.cross_session_recall', True)
        logger.debug(
            f"[MemoryManager] recall() : query='{query[:30]}...', "
            f"limit={limit}, tiers={tiers}, session_id={session_id}, user_id={user_id}, workspace_id={workspace_id}, cross_session={cross_session}"
        )
        all_results: List[MemoryBlock] = []
        seen_ids = set()
        self._recall_stats["total"] += 1
        for tier_name in tiers:
            if tier_name == "long_term" and user_id and cross_session:
                # 跨 session：走 user 专属 hybrid searcher（BM25 jieba 分词 + 向量 RRF），
                # 索引层预过滤该 user/workspace，避免 global searcher 多 user 时召回率下降
                if use_hybrid:
                    try:
                        searcher = await self._get_hybrid_searcher(
                            "long_term", None, user_id=user_id, workspace_id=workspace_id)
                        tier_results = await searcher.search(
                            query, top_k=limit,
                            use_reranking=self._hybrid_config.reranking_enabled)
                    except Exception as e:
                        logger.warning(f"[MemoryManager] cross_session hybrid 失败，回退 long_term.search: {e}")
                        tier_results = await self.long_term.search(query, limit, user_id=user_id, workspace_id=workspace_id)
                else:
                    tier_results = await self.long_term.search(query, limit, user_id=user_id, workspace_id=workspace_id)
            elif use_hybrid:
                try:
                    searcher = await self._get_hybrid_searcher(tier_name, session_id)
                    tier_results = await searcher.search(
                        query,
                        top_k=limit,
                        use_reranking=self._hybrid_config.reranking_enabled
                    )
                except Exception as e:
                    logger.warning(f"[MemoryManager] : {e}")
                    tier_results = await self._fallback_search(tier_name, query, limit, session_id)
            else:
                tier_results = await self._fallback_search(tier_name, query, limit, session_id)
            for memory in tier_results:
                if memory.id not in seen_ids:
                    all_results.append(memory)
                    seen_ids.add(memory.id)
            if tier_results:
                logger.debug(f"[MemoryManager] {tier_name}  {len(tier_results)} ")
                self._recall_stats["by_tier"][tier_name] = self._recall_stats["by_tier"].get(tier_name, 0) + len(tier_results)
        recency_weight = float(get_config("memory.recency_weight", 0.15) or 0.15)
        all_results.sort(
            key=lambda m: m.get_final_recall_score(recency_weight),
            reverse=True
        )
        # 时间 fallback：语义/关键词无命中时（元查询如"最近讨论了哪些话题"），
        # 按时间倒序召回近期 event/fact，不依赖穷举关键词识别元查询
        fallback_threshold = int(get_config("memory.recall_fallback_threshold", 0) or 0)
        if len(all_results) <= fallback_threshold and user_id:
            try:
                recent = await self._recall_recent(
                    user_id=user_id, workspace_id=workspace_id, limit=limit)
                for m in recent:
                    if m.id not in seen_ids:
                        all_results.append(m)
                        seen_ids.add(m.id)
                if recent:
                    self._recall_stats["fallback"] += 1
                    logger.info(
                        f"[MemoryManager] recall fallback 命中 0，"
                        f"按时间召回近期 {len(recent)} 条"
                    )
                    all_results.sort(
                        key=lambda m: m.get_final_recall_score(recency_weight),
                        reverse=True
                    )
            except Exception as e:
                logger.warning(f"[MemoryManager] recall fallback 失败: {e}")
        if all_results:
            self._recall_stats["hits"] += 1
        logger.debug(
            f"[MemoryManager] recall() 召回: 共 {len(all_results)} 条, "
            f"返回 {min(limit, len(all_results))} 条"
        )
        return all_results[:limit]
    def get_recall_stats(self) -> Dict[str, Any]:
        """recall 效果统计（total/hits/fallback/by_tier），供 admin 可观测召回质量。"""
        return dict(self._recall_stats)
    async def _recall_recent(self, user_id: str,
                             workspace_id: Optional[str] = None,
                             limit: int = 5,
                             types: Optional[List[str]] = None) -> List[MemoryBlock]:
        """按时间倒序召回近期 long_term 记忆（默认 event/fact），按 user/workspace 过滤。

        用 list_recent_by_user（SQL 层预过滤+分页），避免 get_all 全量加载大库 OOM。
        """
        types = types or ["event", "fact", "task"]
        try:
            # 优先用 SQL 预过滤+分页（避免全量加载）
            if hasattr(self._sqlite_storage, "list_recent_by_user"):
                recent_all = await self._sqlite_storage.list_recent_by_user(
                    "long_term", user_id=user_id, workspace_id=workspace_id,
                    limit=max(limit * 3, 30))
            else:
                recent_all = await self.long_term.get_all()
                if user_id:
                    recent_all = [m for m in recent_all if m.user_id == user_id]
                if workspace_id:
                    recent_all = [m for m in recent_all if m.workspace_id == workspace_id]
            filtered = []
            for m in recent_all:
                mtype = m.type.value if hasattr(m.type, "value") else str(m.type)
                if mtype in types:
                    filtered.append(m)
            filtered.sort(key=lambda m: m.created_at, reverse=True)
            return filtered[:limit]
        except Exception as e:
            logger.warning(f"[MemoryManager] _recall_recent 失败: {e}")
            return []
    async def _find_duplicate_short_term(self, memory: MemoryBlock) -> Optional[MemoryBlock]:
        """短期层去重：查同 user 同 content 是否已存（精确匹配，跨 session 用户级去重）。

        防止 _store 的 LLM 重复提取同内容导致短期层膨胀。
        命中则返回已存记忆（调用方跳过新增 + touch 已存）。
        """
        try:
            all_m = await self.short_term.get_all()
        except Exception as e:
            logger.warning(f"[MemoryManager] 短期层去重查询失败: {e}")
            return None
        for m in all_m:
            if memory.user_id and m.user_id != memory.user_id:
                continue
            if m.content == memory.content:
                m.touch()
                return m
        return None
    async def forget(self, memory_id: str) -> bool:
        deleted = False
        deleted = await self.immediate.delete(memory_id) or deleted
        deleted = await self.short_term.delete(memory_id) or deleted
        deleted = await self.long_term.delete(memory_id) or deleted
        if deleted:
            logger.debug(f"[MemoryManager] : {memory_id}")
            # 增量从 searcher 移除（替代全清重建）
            self._incremental_index_remove(memory_id)
        return deleted
    async def _apply_conflict_resolution(self, memory: MemoryBlock, user_id: Optional[str]) -> bool:
        """对 long_term-bound 记忆做冲突检测。返回 True 表示已处理（UPDATE/MERGE/NONE），False 表示未命中候选应走原 ADD。"""
        try:
            candidates = await self.recall(
                query=memory.content,
                limit=self._conflict_resolver.max_candidates,
                user_id=user_id,
                tiers=["long_term"],
            )
        except Exception as e:
            logger.warning(f"[MemoryManager] 冲突候选召回失败，走 ADD: {e}")
            return False
        thr = self._conflict_resolver.similarity_threshold
        filtered = [c for c in candidates
                    if c.id != memory.id
                    and float(c.metadata.get("hybrid_score",
                              c.metadata.get("similarity", 0.0))) >= thr]
        if not filtered:
            return False
        decision = await self._conflict_resolver.resolve(memory, filtered)
        action = decision.get("action", "ADD")
        if action == "ADD":
            return False
        target_id = decision.get("target_id")
        target = next((c for c in filtered if c.id == target_id), None)
        if action in ("UPDATE", "MERGE") and target is not None:
            target_before = target.content
            if action == "UPDATE":
                target.content = memory.content
            else:
                target.content = decision.get("merged_content") or target.content
            target.importance = min(1.0, max(target.importance, memory.importance) + 0.1)
            target.touch()
            # 冲突决策可观测：存活记忆记录 decision/来源/时间，供管理 API 查询
            from datetime import datetime as _dt
            target.metadata["conflict_decision"] = action
            target.metadata["conflict_merged_from"] = memory.id
            target.metadata["conflict_merged_at"] = _dt.now().isoformat()
            await self.long_term.update(target)
            # 审计：UPDATE/MERGE 前记录 target 原内容 + 新记忆快照，供回滚
            await self._record_audit(
                op_type=f"conflict_{action.lower()}",
                workspace_id=memory.workspace_id, user_id=memory.user_id,
                kept_id=target.id, kept_content_before=target_before,
                deleted_snapshot=memory.to_dict(),
                merged_content=target.content, reason=decision.get("reason"))
            logger.info(f"[MemoryManager] 冲突 {action}: target={target.id} <- {memory.id}")
            return True
        if action == "NONE":
            logger.info(f"[MemoryManager] 冲突 NONE: 丢弃重复记忆 {memory.id}")
            return True
        return False
    async def _get_hybrid_searcher(
        self,
        tier: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None
    ) -> HybridMemorySearch:
        # user_id 指定时建 user 专属 searcher（索引预过滤该 user），避免 global searcher
        # 在多 user 大库时 top_k 全是别的 user → post-filter 召回率下降
        if user_id:
            cache_key = f"user:{user_id}:{workspace_id or ''}:{tier}"
        else:
            cache_key = f"{session_id or 'global'}:{tier}"
        if cache_key not in self._hybrid_searchers:
            searcher = HybridMemorySearch(
                bm25_weight=self._hybrid_config.bm25_weight,
                vector_weight=self._hybrid_config.vector_weight,
                rrf_k=self._hybrid_config.rrf_k,
                similarity_threshold=self._hybrid_config.similarity_threshold
            )
            if tier == "immediate":
                memories = await self.immediate.get_all(session_id)
            elif tier == "short_term":
                memories = await self.short_term.get_all(session_id)
            else:
                memories = await self.long_term.get_all(session_id)
            # user/workspace 预过滤（索引层隔离）
            if user_id:
                memories = [m for m in memories if m.user_id == user_id]
            if workspace_id:
                memories = [m for m in memories if m.workspace_id == workspace_id]
            if memories:
                await searcher.index(memories)
            self._hybrid_searchers[cache_key] = searcher
            logger.debug(
                f"[MemoryManager]  | tier={tier}, session={session_id}, "
                f"user={user_id}, memories={len(memories)}"
            )
        return self._hybrid_searchers[cache_key]
    async def _fallback_search(
        self,
        tier_name: str,
        query: str,
        limit: int,
        session_id: Optional[str] = None
    ) -> List[MemoryBlock]:
        if tier_name == "immediate":
            return await self.immediate.search(query, limit, session_id)
        elif tier_name == "short_term":
            return await self.short_term.search(query, limit, session_id)
        else:
            return await self.long_term.search(query, limit, session_id)
    def invalidate_search_index(self, tier: Optional[str] = None) -> None:
        if tier:
            self._hybrid_searchers.pop(tier, None)
        else:
            self._hybrid_searchers.clear()
    def is_hybrid_search_enabled(self) -> bool:
        return self._use_hybrid_search
    def set_hybrid_search_enabled(self, enabled: bool) -> None:
        self._use_hybrid_search = enabled
        if not enabled:
            self.invalidate_search_index()
    def get_hybrid_search_config(self) -> HybridSearchConfig:
        return self._hybrid_config
    def set_hybrid_search_config(self, config: HybridSearchConfig) -> None:
        self._hybrid_config = config
        self.invalidate_search_index()
    async def initialize(self) -> None:
        """幂等：从 SQLite 回灌即时/短期记忆到内存，重建活跃缓存。

        long_term 本就读 SQLite，无需回灌。进程启动后调用一次即可。
        同时后台预热 embedding 模型（不阻塞）。
        """
        if self._tiers_loaded:
            return
        self._tiers_loaded = True
        try:
            n_imm = await self.immediate.load_from_storage()
            n_st = await self.short_term.load_from_storage()
            logger.info(f"[MemoryManager] initialize 回灌: immediate={n_imm}, short_term={n_st}")
        except Exception as e:
            logger.warning(f"[MemoryManager] initialize 回灌失败: {e}")
        # 后台预热 embedding 模型，避免首次检索冷启动阻塞
        try:
            import asyncio
            from .embedding_factory import warmup_embedding
            asyncio.create_task(warmup_embedding())
        except Exception as e:
            logger.debug(f"[MemoryManager] embedding warmup 调度失败: {e}")
    async def _incremental_index_update(self, tier: str, memory: MemoryBlock) -> None:
        """增量更新受影响的 hybrid searcher（匹配 tier 且 user/session 兼容）。

        替代 invalidate_search_index() 全清重建：高频写入下避免每次 recall 全量 index。
        - global/session searcher：包含该 tier 全部或该 session，增量加新记忆
        - user 专属 searcher：仅当新记忆 user_id（+workspace_id）匹配时增量加
        """
        mem_session = memory.session_id or "default"
        for key in list(self._hybrid_searchers.keys()):
            if not key.endswith(f":{tier}"):
                continue
            if key.startswith("user:"):
                # user 专属 searcher：cache_key = "user:{uid}:{ws}:{tier}"
                parts = key.split(":")  # ["user", uid, ws, tier]
                if len(parts) < 4:
                    continue
                uid, ws = parts[1], parts[2]
                if memory.user_id != uid:
                    continue
                if ws and memory.workspace_id != ws:
                    continue
            else:
                sid_part = key[:-(len(tier) + 1)]
                if sid_part != "global" and sid_part != mem_session:
                    continue
            searcher = self._hybrid_searchers.get(key)
            if searcher is None:
                continue
            try:
                await searcher.add_memory_async(memory)
            except Exception as e:
                logger.warning(f"[MemoryManager] 增量索引失败 {key}: {e}")
                self._hybrid_searchers.pop(key, None)
    def _incremental_index_remove(self, memory_id: str) -> None:
        """增量从所有 hybrid searcher 移除记忆（forget 时），替代全清重建。"""
        for key, searcher in list(self._hybrid_searchers.items()):
            try:
                searcher.remove_memory(memory_id)
            except Exception as e:
                logger.warning(f"[MemoryManager] 增量移除失败 {key}: {e}")
                self._hybrid_searchers.pop(key, None)
    async def _record_audit(self, op_type: str, workspace_id: Optional[str],
                            user_id: Optional[str], kept_id: Optional[str],
                            kept_content_before: Optional[str],
                            deleted_snapshot: Optional[Dict[str, Any]],
                            merged_content: Optional[str],
                            reason: Optional[str] = None) -> Optional[str]:
        """记录破坏性合并审计（consolidation/conflict UPDATE/MERGE）。

        deleted_snapshot 为被删记忆的完整 to_dict()，供回滚重建。
        """
        try:
            if not hasattr(self._sqlite_storage, "save_audit"):
                return None
            from datetime import datetime as _dt
            import uuid as _uuid
            op_id = str(_uuid.uuid4())
            await self._sqlite_storage.save_audit({
                "op_id": op_id, "op_type": op_type,
                "workspace_id": workspace_id, "user_id": user_id,
                "kept_id": kept_id, "kept_content_before": kept_content_before,
                "deleted_snapshot": deleted_snapshot,
                "merged_content": merged_content, "reason": reason,
                "created_at": _dt.now().isoformat(),
            })
            logger.info(f"[MemoryManager] 审计记录 {op_type}: op={op_id}, kept={kept_id}")
            return op_id
        except Exception as e:
            logger.warning(f"[MemoryManager] 审计记录失败: {e}")
            return None
    async def rollback_audit(self, op_id: str) -> dict:
        """回滚一次破坏性合并：恢复保留方原内容 + 重建被删方。

        - 恢复 kept_content_before → kept 记忆 content
        - 用 deleted_snapshot 重建被删记忆（save 到 long_term + 重嵌）
        """
        try:
            audit = await self._sqlite_storage.get_audit(op_id)
            if not audit:
                return {"ok": False, "reason": "审计记录不存在"}
            restored = 0
            # 恢复保留方原内容
            if audit.get("kept_id") and audit.get("kept_content_before") is not None:
                kept = await self.long_term.get(audit["kept_id"])
                if kept:
                    kept.content = audit["kept_content_before"]
                    kept.metadata.pop("conflict_decision", None)
                    kept.metadata.pop("conflict_merged_from", None)
                    await self.long_term.update(kept)
                    restored += 1
            # 重建被删方
            snap = audit.get("deleted_snapshot")
            if snap:
                from .blocks import MemoryBlock
                m = MemoryBlock.from_dict(snap)
                await self.long_term.add(m)
                restored += 1
            self.invalidate_search_index("long_term")
            logger.info(f"[MemoryManager] 回滚 {op_id}: 恢复 {restored} 条")
            return {"ok": True, "restored": restored, "op_id": op_id}
        except Exception as e:
            logger.warning(f"[MemoryManager] 回滚失败 {op_id}: {e}")
            return {"ok": False, "reason": str(e)}
    async def get_context_memories(
        self,
        session_id: str,
        limit: int = 5
    ) -> List[MemoryBlock]:
        logger.debug(
            f"[MemoryManager] get_context_memories() : "
            f"session_id={session_id}, limit={limit}"
        )
        results = []
        for tier in [self.immediate, self.short_term, self.long_term]:
            memories = await tier.get_all()
            tier_count = 0
            for memory in memories:
                if memory.session_id == session_id:
                    results.append(memory)
                    tier_count += 1
            if tier_count > 0:
                logger.debug(f"[MemoryManager] {tier.name}  {tier_count} ")
        results.sort(key=lambda m: m.importance, reverse=True)
        logger.debug(
            f"[MemoryManager] get_context_memories() 召回: "
            f"共 {len(results)} 条, 返回 {min(limit, len(results))} 条"
        )
        return results[:limit]
    async def promote_memory(self, memory_id: str) -> bool:
        memory = await self.immediate.get(memory_id)
        source_tier = "immediate"
        target_tier = self.short_term
        if not memory:
            memory = await self.short_term.get(memory_id)
            source_tier = "short_term"
            target_tier = self.long_term
        if not memory:
            return False
        memory.importance = min(1.0, memory.importance + 0.2)
        await target_tier.add(memory)
        if source_tier == "immediate":
            await self.immediate.delete(memory_id)
        else:
            await self.short_term.delete(memory_id)
        logger.debug(
            f"[MemoryManager] 记忆迁移: id={memory_id}, "
            f"{source_tier} -> {target_tier.name}"
        )
        return True
    async def decay_memories(self, factor: float = 0.95) -> None:
        for tier in [self.immediate, self.short_term, self.long_term]:
            memories = await tier.get_all()
            for memory in memories:
                memory.decay_importance(factor)
        logger.debug(f"[MemoryManager] : {factor}")
    async def clear_all(self) -> None:
        await self.immediate.clear()
        await self.short_term.clear()
        await self.long_term.clear()
        logger.info("[MemoryManager] ")
    async def clear_session_memories(self, session_id: str) -> int:
        deleted_count = 0
        normalized_session_id = session_id.replace('-', '') if session_id else ''
        memories = await self.immediate.get_all()
        for memory in memories:
            memory_session = (memory.session_id or '').replace('-', '')
            if memory_session == normalized_session_id:
                await self.immediate.delete(memory.id)
                deleted_count += 1
        logger.debug(f"[MemoryManager] : {deleted_count} ")
        short_term_count = 0
        memories = await self.short_term.get_all()
        for memory in memories:
            memory_session = (memory.session_id or '').replace('-', '')
            if memory_session == normalized_session_id:
                await self.short_term.delete(memory.id)
                short_term_count += 1
        deleted_count += short_term_count
        logger.debug(f"[MemoryManager] : {short_term_count} ")
        long_term_count = await self.long_term.delete_by_session(session_id)
        deleted_count += long_term_count
        logger.debug(f"[MemoryManager] : {long_term_count} ")
        self.invalidate_search_index()
        logger.info(
            f"[MemoryManager]  {session_id}  {deleted_count} "
        )
        return deleted_count
    async def clear_user_memories(self, user_id: str) -> int:
        deleted_count = 0
        memories = await self.immediate.get_all()
        for memory in memories:
            if memory.user_id == user_id:
                await self.immediate.delete(memory.id)
                deleted_count += 1
        memories = await self.short_term.get_all()
        for memory in memories:
            if memory.user_id == user_id:
                await self.short_term.delete(memory.id)
                deleted_count += 1
        long_term_count = await self.long_term.delete_by_user(user_id)
        deleted_count += long_term_count
        self.invalidate_search_index()
        logger.info(f"[MemoryManager]  {user_id}  {deleted_count} ")
        return deleted_count
    async def get_stats(self) -> Dict[str, Any]:
        immediate_count = len(await self.immediate.get_all())
        short_term_count = len(await self.short_term.get_all())
        long_term_count = len(await self.long_term.get_all())
        long_term_stats = {
            "count": long_term_count,
            "max_size": self.long_term.max_size,
        }
        if hasattr(self.long_term, 'get_stats'):
            try:
                detailed_stats = await self.long_term.get_stats()
                long_term_stats["storage_backend"] = detailed_stats.get("storage_backend")
                long_term_stats["vector_backend"] = detailed_stats.get("vector_backend")
                if "vector_stats" in detailed_stats:
                    long_term_stats["vector_stats"] = detailed_stats["vector_stats"]
            except Exception:
                pass
        return {
            "immediate": {
                "count": immediate_count,
                "max_size": self.immediate.max_size
            },
            "short_term": {
                "count": short_term_count,
                "max_size": self.short_term.max_size,
                "ttl_hours": self.short_term._ttl_hours
            },
            "long_term": long_term_stats,
            "total": immediate_count + short_term_count + long_term_count
        }


_memory_manager_instance: Optional[MemoryManager] = None


def reset_memory_manager() -> None:
    """重置 MemoryManager 单例（热重载时调用）。

    清空模块级 _memory_manager_instance 和类级 _instance / _initialized，
    下次 get_memory_manager() 会按最新 config 重建实例。
    """
    global _memory_manager_instance
    _memory_manager_instance = None
    MemoryManager._instance = None
    # 注意：_initialized 是实例属性，_instance=None 后旧实例被 GC，
    # 新实例 __init__ 时 hasattr(self, '_initialized') 返回 False → 正常初始化
    logger.debug("[MemoryManager] 单例已重置，下次调用将重建实例")


def get_memory_manager(
    vector_backend: Optional[str] = None,
    vector_config: Optional[Dict[str, Any]] = None,
    use_hybrid_search: bool = True,
    hybrid_config: Optional[Dict[str, Any]] = None,
    sqlite_db_path: str = "data/memory.db"
) -> MemoryManager:
    global _memory_manager_instance
    if _memory_manager_instance is None:
        # 修复：工厂默认从 config 读 memory.vector_backend / vector_config，
        # 使任意调用方（如 admin memory stats 接口不传参）首次触发单例时也带正确配置，
        # 避免向量后端显示"无"（仅当调用方未显式传时取 config 兜底）
        from utils.config import get_config as _get_cfg
        if vector_backend is None:
            vector_backend = _get_cfg("memory.vector_backend", None)
        if vector_config is None:
            vector_config = _get_cfg("memory.vector_config", None)
        _memory_manager_instance = MemoryManager(
            vector_backend=vector_backend,
            vector_config=vector_config,
            use_hybrid_search=use_hybrid_search,
            hybrid_config=hybrid_config,
            sqlite_db_path=sqlite_db_path
        )
    return _memory_manager_instance
