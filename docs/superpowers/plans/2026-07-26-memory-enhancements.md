# 记忆系统增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有三层记忆系统增加冲突检测/合并、recall recency 加权、provenance、consolidation 定时合并、Letta 式自主记忆工具五项能力。

**Architecture:** 在 `memory/` 层加 `ConflictResolver`（LLM 判 ADD/UPDATE/MERGE/NONE，相似门控+降级 ADD）；`MemoryManager.remember()` 在写 long_term 前接入；`recall()` 排序引入 recency 因子；`remember()` 加 provenance 元数据参数；`services/trigger/` 照现有 decay/preference_summary 模式加 `MemoryConsolidationTrigger`；`tools/` 加三个 LangChain `@tool`（search/insert/update），通过 `utils/common/memory_context.py` 的 ContextVar 在 chat 入口自动捕获 user/session。

**Tech Stack:** Python 3.13、FastAPI、LangChain（`@tool`）、APScheduler（现有 cron 单例）、ContextVar、loguru；LLM 走 `utils/llm/llm_caller.py` 的 `LLMCaller.call_with_prompt(parse_json=True)`；pytest（asyncio_mode=auto）。

## Global Constraints

- 后端分层：resolver 属 `memory/`、trigger 属 `services/trigger/`、tools 属 `tools/`、context 属 `utils/common/`；repo 只管数据，路由薄。
- Surgical Changes：只动必要行，匹配既有风格，不顺手重构。
- 日志 `from loguru import logger`，关键操作 info，异常 warning/error 带 exc_info。
- 代码标识符英文，注释/日志可中文。
- LLM 依赖特性在 LLM 未配置时安全降级（conflict→ADD，consolidation 跳过，工具返回 error 字符串不抛）。
- 测试不依赖真实 LLM：ConflictResolver 注入式 `llm_caller`，trigger/tools 用 stub。
- 记忆存储隔离：单元测试用 `InMemoryStorage`（`LongTermMemory(storage_backend="memory")` 或替换 `_storage`），不碰真实 SQLite/Chroma。
- 配置统一写 `config/agent_config.json` 与 `config/agent_config.json.example`（新 key 两处同步）。

## File Structure

**新增**：
- `memory/conflict_resolver.py` — `ConflictResolver` + `ConflictDecision`；LLM 判定 + 降级；`resolve()` 与 `consolidate_pair()`。
- `services/trigger/memory_consolidation_trigger.py` — 定时合并相似长期记忆（复用 decay/preference_summary 模式）。
- `tools/memory_tool.py` — 三个 LangChain `@tool`（memory_search/insert/update）；懒 import memory 包避免 jieba/chromadb 拖累工具发现。
- `utils/common/memory_context.py` — `MemoryContext` + ContextVar + `set/get_memory_context`。
- `test/test_memory_conflict.py`、`test/test_memory_recency.py`、`test/test_memory_provenance.py`、`test/test_memory_consolidation.py`、`test/test_memory_tools.py`。

**修改**：
- `memory/blocks.py` — `create_memory_block()` 加 provenance 参数；`MemoryBlock.get_final_recall_score()`。
- `memory/memory_manager.py` — `remember()` 接 provenance+冲突检测；`recall()` recency 排序；`LongTermMemory.update()`；构造 ConflictResolver。
- `services/trigger/memory_preference_summary_trigger.py` — 去重改调 ConflictResolver。
- `tools/__init__.py` — 注册三个 memory 工具。
- `config/agent_config.json` + `.example` — `memory.conflict_resolution`/`memory.recency_weight`/`memory.consolidation`。
- `server.py` — lifespan 注册 MemoryConsolidationTrigger。
- `api/chat/chat_routes.py` — 两个端点 `_resolve_session_id` 后 `set_memory_context`。

---

## Task 1: 记忆 provenance（Feature 3）

**Files:**
- Modify: `memory/blocks.py`（`create_memory_block` 签名）
- Modify: `memory/memory_manager.py`（`remember` 签名 + 透传 metadata）
- Test: `test/test_memory_provenance.py`

**Interfaces:**
- Produces: `create_memory_block(..., source_session_id=None, source_message_id=None)`、`MemoryManager.remember(..., source_session_id=None, source_message_id=None)`；非空时写入 `metadata["source_session_id"]`/`metadata["source_message_id"]`。后续 Task 3/4/7 依赖 remember 透传 metadata。

- [ ] **Step 1: 写失败测试**

```python
# test/test_memory_provenance.py
import asyncio
from memory import MemoryManager
from memory.blocks import create_memory_block


async def test_remember_records_provenance_in_metadata():
    mm = MemoryManager(vector_backend=None, use_hybrid_search=False)
    m = await mm.remember(
        "用户偏好简洁回答",
        type="preference",
        importance=0.9,
        user_id="u1",
        session_id="s1",
        source_session_id="s1",
        source_message_id="msg-42",
    )
    assert m.metadata.get("source_session_id") == "s1"
    assert m.metadata.get("source_message_id") == "msg-42"


async def test_remember_without_provenance_omits_keys():
    mm = MemoryManager(vector_backend=None, use_hybrid_search=False)
    m = await mm.remember("临时笔记", importance=0.3, user_id="u1")
    assert "source_session_id" not in m.metadata
    assert "source_message_id" not in m.metadata


async def test_create_memory_block_provenance():
    m = create_memory_block(
        content="x",
        source_session_id="s2",
        source_message_id="m9",
    )
    assert m.metadata["source_session_id"] == "s2"
    assert m.metadata["source_message_id"] == "m9"


if __name__ == "__main__":
    asyncio.run(test_remember_records_provenance_in_metadata())
    asyncio.run(test_remember_without_provenance_omits_keys())
    asyncio.run(test_create_memory_block_provenance())
    print("provenance ok")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test/test_memory_provenance.py`
Expected: `TypeError: remember() got an unexpected keyword argument 'source_session_id'`

- [ ] **Step 3: 改 create_memory_block 签名**

`memory/blocks.py` 末尾函数改为：
```python
def create_memory_block(
    content: str,
    type: str = "note",
    importance: float = 0.5,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    source_session_id: Optional[str] = None,
    source_message_id: Optional[str] = None,
) -> MemoryBlock:
    memory_type = MemoryType(type) if isinstance(type, str) else type
    meta = dict(metadata or {})
    if source_session_id is not None:
        meta["source_session_id"] = source_session_id
    if source_message_id is not None:
        meta["source_message_id"] = source_message_id
    return MemoryBlock(
        content=content,
        type=memory_type,
        importance=importance,
        session_id=session_id,
        user_id=user_id,
        tags=tags or [],
        metadata=meta,
    )
```

- [ ] **Step 4: 改 remember 签名透传**

`memory/memory_manager.py` 的 `remember` 方法签名与调用改为：
```python
    async def remember(
        self,
        content: str,
        type: str = "note",
        importance: float = 0.5,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        source_session_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
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
            tags=tags,
            metadata=metadata,
            source_session_id=source_session_id,
            source_message_id=source_message_id,
        )
```
（后续 `if importance >= 0.8:` 分层逻辑保持不变，本任务不动。）

- [ ] **Step 5: 跑测试确认通过**

Run: `python test/test_memory_provenance.py`
Expected: `provenance ok`

- [ ] **Step 6: 提交**

```bash
git add memory/blocks.py memory/memory_manager.py test/test_memory_provenance.py
git commit -m "feat(memory): remember 写入 source_session_id/source_message_id provenance 元数据"
```

---

## Task 2: LongTermMemory.update（Feature 1/5 共用基础设施）

**Files:**
- Modify: `memory/memory_manager.py`（`LongTermMemory.update`）
- Test: `test/test_memory_conflict.py`（本任务的 update 用例）

**Interfaces:**
- Produces: `LongTermMemory.update(memory: MemoryBlock) -> bool`：SQLite `INSERT OR REPLACE` by id + 向量层 delete-then-add 重嵌。Task 3（UPDATE/MERGE 写回）、Task 7（memory_update 工具）依赖此方法。

- [ ] **Step 1: 写失败测试**

追加到 `test/test_memory_conflict.py`（文件在 Task 3 创建；本任务先建文件放 update 用例）：
```python
# test/test_memory_conflict.py  （Task 2 部分）
import asyncio
from datetime import datetime
from memory import MemoryManager
from memory.blocks import MemoryBlock, MemoryType


def _fresh_long_term():
    """独立 LongTermMemory + InMemoryStorage，隔离测试"""
    from memory.memory_manager import LongTermMemory
    lt = LongTermMemory(max_size=1000, storage_backend="memory", vector_backend=None)
    return lt


async def test_long_term_update_rewrites_content_and_persists():
    lt = _fresh_long_term()
    m = MemoryBlock(content="偏好意大利菜", type=MemoryType.PREFERENCE,
                    importance=0.9, user_id="u1")
    await lt.add(m)
    m.content = "偏好墨西哥菜"
    ok = await lt.update(m)
    assert ok
    loaded = await lt.get(m.id)
    assert loaded.content == "偏好墨西哥菜"
    assert loaded.importance == 0.9


if __name__ == "__main__":
    asyncio.run(test_long_term_update_rewrites_content_and_persists())
    print("update ok")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test/test_memory_conflict.py`
Expected: `AttributeError: 'LongTermMemory' object has no attribute 'update'`

- [ ] **Step 3: 实现 LongTermMemory.update**

在 `memory/memory_manager.py` 的 `LongTermMemory` 类中，`delete` 方法之后插入：
```python
    async def update(self, memory: MemoryBlock) -> bool:
        """更新已有记忆内容并重嵌（SQLite INSERT OR REPLACE + 向量层 delete-then-add）。"""
        result = await self._storage.save(memory)
        if result and self._vector_backend:
            vector_storage = await self._ensure_vector_storage()
            if vector_storage:
                try:
                    await vector_storage.delete(memory.id)
                    await vector_storage.save(memory)
                    logger.debug(f"[LongTermMemory] update 重嵌: {memory.id}")
                except Exception as e:
                    logger.warning(f"[LongTermMemory] update 向量重嵌失败: {e}")
        return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python test/test_memory_conflict.py`
Expected: `update ok`

- [ ] **Step 5: 提交**

```bash
git add memory/memory_manager.py test/test_memory_conflict.py
git commit -m "feat(memory): LongTermMemory.update 改写内容+重嵌，供冲突合并与记忆工具复用"
```

---

## Task 3: ConflictResolver 核心（Feature 1）

**Files:**
- Create: `memory/conflict_resolver.py`
- Modify: `test/test_memory_conflict.py`（追加 resolve 用例）
- Modify: `memory/__init__.py`（导出 ConflictResolver）

**Interfaces:**
- Produces: `ConflictResolver(llm_caller=None, similarity_threshold=0.6, max_candidates=5)`；`async resolve(new, candidates) -> ConflictDecision`；`async consolidate_pair(a, b) -> Optional[str]`。`llm_caller` 签名 `Callable[[str, str], Awaitable[Optional[dict]]]`（system, user → 解析后 dict 或 None），默认走 `LLMCaller.call_with_prompt(parse_json=True)`。Task 4/6/7 依赖。

- [ ] **Step 1: 写失败测试（注入假 llm_caller 覆盖 4 种 action + 降级）**

追加到 `test/test_memory_conflict.py`：
```python
from memory.blocks import MemoryBlock, MemoryType
from memory.conflict_resolver import ConflictResolver


def _blk(content, mid="m1", mtype=MemoryType.PREFERENCE, uid="u1"):
    return MemoryBlock(id=mid, content=content, type=mtype, importance=0.9, user_id=uid)


async def _fake_caller_factory(decision: dict):
    async def _caller(system_prompt: str, user_prompt: str):
        return dict(decision)
    return _caller


async def test_resolve_add_when_no_candidates():
    r = ConflictResolver()
    new = _blk("新事实")
    dec = await r.resolve(new, [])
    assert dec["action"] == "ADD"


async def test_resolve_update_overwrites_candidate():
    caller = await _fake_caller_factory({"action": "UPDATE", "target_id": "c1"})
    r = ConflictResolver(llm_caller=caller)
    new = _blk("喜欢墨西哥菜", mid="new1")
    cands = [_blk("喜欢意大利菜", mid="c1")]
    dec = await r.resolve(new, cands)
    assert dec["action"] == "UPDATE"
    assert dec["target_id"] == "c1"


async def test_resolve_merge_returns_merged_content():
    caller = await _fake_caller_factory({"action": "MERGE", "target_id": "c1",
                                          "merged_content": "用户偏好墨西哥菜和意大利菜"})
    r = ConflictResolver(llm_caller=caller)
    dec = await r.resolve(_blk("喜欢意大利菜", mid="new1"), [_blk("喜欢墨西哥菜", mid="c1")])
    assert dec["action"] == "MERGE"
    assert dec["merged_content"].startswith("用户偏好")


async def test_resolve_none_for_duplicate():
    caller = await _fake_caller_factory({"action": "NONE", "target_id": "c1"})
    r = ConflictResolver(llm_caller=caller)
    dec = await r.resolve(_blk("喜欢意大利菜", mid="new1"), [_blk("喜欢意大利菜", mid="c1")])
    assert dec["action"] == "NONE"


async def test_resolve_degrades_to_add_on_llm_failure():
    async def _bad(system, user):
        return None
    r = ConflictResolver(llm_caller=_bad)
    dec = await r.resolve(_blk("x", mid="new1"), [_blk("y", mid="c1")])
    assert dec["action"] == "ADD"


async def test_resolve_degrades_to_add_on_invalid_action():
    async def _weird(system, user):
        return {"action": "WAT"}
    r = ConflictResolver(llm_caller=_weird)
    dec = await r.resolve(_blk("x", mid="new1"), [_blk("y", mid="c1")])
    assert dec["action"] == "ADD"


async def test_consolidate_pair_returns_merged():
    async def _caller(system, user):
        return {"merge": True, "merged_content": "合并后：用户偏好辣食"}
    r = ConflictResolver(llm_caller=_caller)
    merged = await r.consolidate_pair(_blk("偏好辣", mid="a"), _blk("喜欢辣", mid="b"))
    assert merged and "辣" in merged


async def test_consolidate_pair_returns_none_when_not_mergeable():
    async def _caller(system, user):
        return {"merge": False}
    r = ConflictResolver(llm_caller=_caller)
    merged = await r.consolidate_pair(_blk("偏好辣", mid="a"), _blk("讨论了天气", mid="b"))
    assert merged is None
```
更新 `__main__`：
```python
if __name__ == "__main__":
    asyncio.run(test_long_term_update_rewrites_content_and_persists())
    for fn in [test_resolve_add_when_no_candidates, test_resolve_update_overwrites_candidate,
               test_resolve_merge_returns_merged_content, test_resolve_none_for_duplicate,
               test_resolve_degrades_to_add_on_llm_failure,
               test_resolve_degrades_to_add_on_invalid_action,
               test_consolidate_pair_returns_merged,
               test_consolidate_pair_returns_none_when_not_mergeable]:
        asyncio.run(fn())
    print("conflict ok")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test/test_memory_conflict.py`
Expected: `ModuleNotFoundError: No module named 'memory.conflict_resolver'`

- [ ] **Step 3: 实现 ConflictResolver**

`memory/conflict_resolver.py`：
```python
"""冲突检测/合并 — Mem0 式 LLM 判 ADD/UPDATE/MERGE/NONE。

- 仅当存在相似候选才调 LLM（相似门控由调用方负责过滤候选）。
- LLM 不可用/解析失败/非法 action → 降级 ADD（兼容现状）。
- llm_caller 可注入：签名 (system_prompt, user_prompt) -> Awaitable[Optional[dict]]，
  返回已解析的 dict；默认走 LLMCaller.call_with_prompt(parse_json=True)。
"""
from __future__ import annotations
from typing import Any, Awaitable, Callable, List, Optional, TypedDict
from loguru import logger
from .blocks import MemoryBlock

Literal_action = str  # "ADD"|"UPDATE"|"MERGE"|"NONE"


class ConflictDecision(TypedDict, total=False):
    action: str
    target_id: Optional[str]
    merged_content: Optional[str]
    reason: Optional[str]


class ConflictResolver:
    def __init__(
        self,
        llm_caller: Optional[Callable[[str, str], Awaitable[Optional[dict]]]] = None,
        similarity_threshold: float = 0.6,
        max_candidates: int = 5,
    ):
        self._llm_call = llm_caller or self._default_llm_call
        self.similarity_threshold = similarity_threshold
        self.max_candidates = max_candidates

    async def _default_llm_call(self, system_prompt: str, user_prompt: str) -> Optional[dict]:
        try:
            from utils.llm.llm_caller import LLMCaller
            r = await LLMCaller.call_with_prompt(system_prompt, user_prompt, parse_json=True)
            if r.success and r.parsed:
                return r.parsed
        except Exception as e:
            logger.warning(f"[ConflictResolver] LLM 调用失败，降级 ADD: {e}")
        return None

    async def resolve(self, new: MemoryBlock, candidates: List[MemoryBlock]) -> ConflictDecision:
        if not candidates:
            return {"action": "ADD", "target_id": None, "merged_content": None, "reason": "no candidates"}
        parsed = await self._llm_call(self._system_prompt(), self._user_prompt(new, candidates))
        action = (parsed or {}).get("action", "").upper() if parsed else ""
        if action not in ("ADD", "UPDATE", "MERGE", "NONE"):
            logger.warning(f"[ConflictResolver] 非法/缺失 action={action!r}，降级 ADD")
            return {"action": "ADD", "target_id": None, "merged_content": None, "reason": "degraded"}
        return {
            "action": action,
            "target_id": parsed.get("target_id"),
            "merged_content": parsed.get("merged_content"),
            "reason": parsed.get("reason"),
        }

    async def consolidate_pair(self, a: MemoryBlock, b: MemoryBlock) -> Optional[str]:
        parsed = await self._llm_call(self._merge_system_prompt(), self._merge_user_prompt(a, b))
        if not parsed:
            return None
        if not parsed.get("merge", False):
            return None
        merged = (parsed.get("merged_content") or "").strip()
        return merged or None

    def _system_prompt(self) -> str:
        return (
            "你是记忆冲突判定器。给定【新记忆】与【候选记忆列表】，判断新记忆与候选的关系，"
            "只输出 JSON：{\"action\":\"ADD|UPDATE|MERGE|NONE\","
            "\"target_id\":\"候选id\",\"merged_content\":\"合并后内容\",\"reason\":\"简述\"}。\n"
            "- ADD：新事实，与候选无关。\n"
            "- UPDATE：新记忆取代/纠正候选（如偏好变更），target_id 指向被取代的候选。\n"
            "- MERGE：互补，合并为一条更完整记忆，给出 merged_content，target_id 指向保留的候选。\n"
            "- NONE：重复，丢弃新记忆，target_id 指向重复的候选。\n"
            "只输出 JSON，不要解释。"
        )

    def _user_prompt(self, new: MemoryBlock, candidates: List[MemoryBlock]) -> str:
        import json as _json
        cands = [{"id": c.id, "type": getattr(c.type, "value", str(c.type)), "content": c.content}
                 for c in candidates]
        return _json.dumps({
            "new": {"id": new.id, "type": getattr(new.type, "value", str(new.type)),
                    "content": new.content},
            "candidates": cands,
        }, ensure_ascii=False)

    def _merge_system_prompt(self) -> str:
        return (
            "你是记忆合并器。判断两条已有记忆是否可合并为一条更完整、不丢信息的记忆。"
            "只输出 JSON：{\"merge\":true|false,\"merged_content\":\"合并后内容\"}。\n"
            "merge=true 时 merged_content 须保留两者关键信息、消除冗余；"
            "内容主题无关则 merge=false。只输出 JSON。"
        )

    def _merge_user_prompt(self, a: MemoryBlock, b: MemoryBlock) -> str:
        import json as _json
        return _json.dumps({
            "memory_a": {"id": a.id, "content": a.content},
            "memory_b": {"id": b.id, "content": b.content},
        }, ensure_ascii=False)
```

- [ ] **Step 4: 导出**

`memory/__init__.py` 在 `from .blocks import (...)` 之后加：
```python
from .conflict_resolver import ConflictResolver, ConflictDecision
```
`__all__` 列表追加 `"ConflictResolver"`, `"ConflictDecision"`。

- [ ] **Step 5: 跑测试确认通过**

Run: `python test/test_memory_conflict.py`
Expected: `conflict ok`

- [ ] **Step 6: 提交**

```bash
git add memory/conflict_resolver.py memory/__init__.py test/test_memory_conflict.py
git commit -m "feat(memory): ConflictResolver LLM 判 ADD/UPDATE/MERGE/NONE + 降级 ADD + consolidate_pair"
```

---

## Task 4: 接入 remember() 冲突检测 + 配置 + preference_summary 复用（Feature 1 集成）

**Files:**
- Modify: `memory/memory_manager.py`（`MemoryManager.__init__` 构造 resolver、`remember` 接入）
- Modify: `config/agent_config.json`、`config/agent_config.json.example`（`memory.conflict_resolution`）
- Modify: `services/trigger/memory_preference_summary_trigger.py`（去重改调 ConflictResolver）
- Test: `test/test_memory_conflict.py`（追加 remember 集成用例）

**Interfaces:**
- Produces: `MemoryManager._conflict_resolver`（可被测试替换）；`remember()` 对 long_term-bound（importance≥0.8）记忆先按内容召回同 user 候选，命中候选才调 resolver，按 action 写回。preference_summary 写入前改用 resolver 判定。

- [ ] **Step 1: 写失败测试（remember 接 UPDATE/MERGE/NONE/ADD + 降级）**

追加到 `test/test_memory_conflict.py`：
```python
class _FakeResolver:
    """记录调用、返回预设 action 的假 resolver"""
    def __init__(self, action, target_id="c1", merged_content=None):
        self.action = action
        self.target_id = target_id
        self.merged_content = merged_content
        self.called = False
    async def resolve(self, new, candidates):
        self.called = True
        return {"action": self.action, "target_id": self.target_id,
                "merged_content": self.merged_content, "reason": "fake"}


def _mm_with_resolver(resolver):
    mm = MemoryManager(vector_backend=None, use_hybrid_search=False)
    # 隔离：long_term 走内存存储
    from memory.storage import InMemoryStorage
    mm.long_term._storage = InMemoryStorage()
    mm._conflict_resolver = resolver
    return mm


async def test_remember_update_overwrites_existing_long_term():
    fr = _FakeResolver("UPDATE", target_id="c1")
    mm = _mm_with_resolver(fr)
    existing = MemoryBlock(id="c1", content="喜欢意大利菜",
                           type=MemoryType.PREFERENCE, importance=0.9, user_id="u1")
    await mm.long_term.add(existing)
    await mm.remember("喜欢墨西哥菜", type="preference", importance=0.9, user_id="u1")
    assert fr.called
    loaded = await mm.long_term.get("c1")
    assert loaded.content == "喜欢墨西哥菜"
    # 新记忆未被单独存储
    assert len(await mm.long_term.get_all()) == 1


async def test_remember_merge_consolidates_into_target():
    fr = _FakeResolver("MERGE", target_id="c1", merged_content="偏好墨西哥菜和意大利菜")
    mm = _mm_with_resolver(fr)
    await mm.long_term.add(MemoryBlock(id="c1", content="喜欢意大利菜",
                                       type=MemoryType.PREFERENCE, importance=0.9, user_id="u1"))
    await mm.remember("喜欢墨西哥菜", type="preference", importance=0.9, user_id="u1")
    assert (await mm.long_term.get("c1")).content == "偏好墨西哥菜和意大利菜"


async def test_remember_none_skips_storing_new():
    fr = _FakeResolver("NONE", target_id="c1")
    mm = _mm_with_resolver(fr)
    await mm.long_term.add(MemoryBlock(id="c1", content="喜欢意大利菜",
                                       type=MemoryType.PREFERENCE, importance=0.9, user_id="u1"))
    await mm.remember("喜欢意大利菜", type="preference", importance=0.9, user_id="u1")
    assert len(await mm.long_term.get_all()) == 1


async def test_remember_add_stores_new_when_no_conflict():
    # 无候选 → resolver 不必被调（门控），直接 ADD
    class _Probe:
        called = False
        async def resolve(self, new, candidates):
            _Probe.called = True
            return {"action": "ADD"}
    mm = MemoryManager(vector_backend=None, use_hybrid_search=False)
    from memory.storage import InMemoryStorage
    mm.long_term._storage = InMemoryStorage()
    mm._conflict_resolver = _Probe()
    await mm.remember("全新偏好", type="preference", importance=0.9, user_id="u1")
    # 无候选：门控不调 resolver
    assert _Probe.called is False
    assert len(await mm.long_term.get_all()) == 1


async def test_remember_low_importance_skips_conflict_check():
    # importance<0.8 → 非 long_term，不走冲突检测
    class _Probe:
        called = False
        async def resolve(self, new, candidates):
            _Probe.called = True
            return {"action": "ADD"}
    mm = MemoryManager(vector_backend=None, use_hybrid_search=False)
    mm._conflict_resolver = _Probe()
    await mm.remember("临时", importance=0.3, user_id="u1")
    assert _Probe.called is False
```
更新 `__main__` 追加这 5 个用例的 asyncio.run。

- [ ] **Step 2: 跑测试确认失败**

Run: `python test/test_memory_conflict.py`
Expected: `AttributeError: 'MemoryManager' object has no attribute '_conflict_resolver'`（或 candidate 门控逻辑未实现导致 Probe 被调）

- [ ] **Step 3: 配置项**

`config/agent_config.json` 的 `memory` 对象内追加：
```json
        "conflict_resolution": {
            "enabled": true,
            "similarity_threshold": 0.6,
            "max_candidates": 5,
            "_comment": "写入 long_term 前做 LLM 冲突检测；仅命中相似候选才调 LLM；LLM 不可用降级 ADD"
        },
```
`config/agent_config.json.example` 同步追加同样片段。

- [ ] **Step 4: MemoryManager 构造 resolver**

`memory/memory_manager.py` `MemoryManager.__init__` 末尾（`self._initialized = True` 之前）加：
```python
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
        logger.info(f"[MemoryManager] conflict_resolution={self._conflict_resolution_enabled}")
```

- [ ] **Step 5: remember 接入冲突检测**

在 `remember` 方法内，`memory = create_memory_block(...)` 之后、原 `if importance >= 0.8:` 之前插入冲突检测分支，并把 long_term 写入路径替换为冲突感知版本：
```python
        target_long_term = importance >= 0.8
        if (self._conflict_resolution_enabled and self._conflict_resolver is not None
                and target_long_term):
            applied = await self._apply_conflict_resolution(memory, user_id)
            if applied:
                self.invalidate_search_index()
                return memory

        if importance >= 0.8:
            await self.long_term.add(memory)
            logger.debug(f"[MemoryManager] : {content[:50]}...")
        elif importance >= 0.5:
            await self.short_term.add(memory)
            logger.debug(f"[MemoryManager] : {content[:50]}...")
        else:
            await self.immediate.add(memory)
            logger.debug(f"[MemoryManager] : {content[:50]}...")
        self.invalidate_search_index()
        return memory
```
并在 `MemoryManager` 类中新增辅助方法（放在 `forget` 之后）：
```python
    async def _apply_conflict_resolution(self, memory: MemoryBlock, user_id: Optional[str]) -> bool:
        """对 long_term-bound 记忆做冲突检测。返回 True 表示已处理（UPDATE/MERGE/NONE），False 表示未命中候选应走原 ADD。"""
        try:
            from .blocks import MemoryType  # noqa
            candidates = await self.recall(
                query=memory.content,
                limit=self._conflict_resolver.max_candidates,
                user_id=user_id,
                tiers=["long_term"],
            )
        except Exception as e:
            logger.warning(f"[MemoryManager] 冲突候选召回失败，走 ADD: {e}")
            return False
        # 相似门控：取 hybrid_score/similarity >= 阈值
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
            return False  # 交还原路径存储
        target_id = decision.get("target_id")
        target = next((c for c in filtered if c.id == target_id), None)
        if action in ("UPDATE", "MERGE") and target is not None:
            if action == "UPDATE":
                target.content = memory.content
            else:
                target.content = decision.get("merged_content") or target.content
            target.importance = min(1.0, max(target.importance, memory.importance) + 0.1)
            target.touch()
            await self.long_term.update(target)
            logger.info(f"[MemoryManager] 冲突 {action}: target={target.id}")
            return True
        if action == "NONE":
            logger.info(f"[MemoryManager] 冲突 NONE: 丢弃重复记忆 {memory.id}")
            return True
        return False
```

- [ ] **Step 6: preference_summary 去重改调 ConflictResolver**

`services/trigger/memory_preference_summary_trigger.py` 中，把这段：
```python
                deduped = 0
                for it in items:
                    ...
                    # 查重：新 content 和已有 preference 相似（包含或相同）则跳过
                    if any(content in ec or ec in content for ec in existing_prefs):
                        deduped += 1
                        continue
```
改为调用 ConflictResolver（保留 fallback）：
```python
                from memory.conflict_resolver import ConflictResolver
                resolver = ConflictResolver()
                deduped = 0
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    content = str(it.get('content', '')).strip()
                    if not content or len(content) < 3:
                        continue
                    # 查重：构造候选 MemoryBlock，交 ConflictResolver 判定
                    from memory.blocks import MemoryBlock, MemoryType
                    cand_blocks = [MemoryBlock(id=f"ex{i}", content=ec,
                                               type=MemoryType.PREFERENCE, importance=0.9)
                                   for i, ec in enumerate(existing_prefs)]
                    try:
                        dec = await resolver.resolve(
                            MemoryBlock(id="new", content=content,
                                        type=MemoryType.PREFERENCE, importance=0.9),
                            cand_blocks)
                        action = dec.get("action", "ADD")
                    except Exception:
                        action = "ADD"  # fallback：包含匹配
                        if any(content in ec or ec in content for ec in existing_prefs):
                            action = "NONE"
                    if action == "NONE":
                        deduped += 1
                        continue
                    # UPDATE/MERGE：改写对应已有 preference（按 target_id 顺序映射）
                    if action in ("UPDATE", "MERGE") and dec.get("target_id"):
                        try:
                            idx = int(dec["target_id"].replace("ex", ""))
                            if 0 <= idx < len(existing_prefs):
                                # 直接 remember 覆盖（走冲突检测会再判一次，安全）
                                pass
                        except Exception:
                            pass
```
（注：preference_summary 原本就是批量写偏好；这里改为 NONE 跳过、ADD 写入；UPDATE/MERGE 简化为让后续 remember 走 Task 4 的统一冲突检测。最小改动且复用。）

- [ ] **Step 7: 跑测试确认通过**

Run: `python test/test_memory_conflict.py`
Expected: `conflict ok`（含 update/merge/none/add/low-importance 全绿）

- [ ] **Step 8: 提交**

```bash
git add memory/memory_manager.py config/agent_config.json config/agent_config.json.example services/trigger/memory_preference_summary_trigger.py test/test_memory_conflict.py
git commit -m "feat(memory): remember 接入 LLM 冲突检测(相似门控+降级ADD) + preference_summary 复用 resolver"
```

---

## Task 5: recall recency 加权（Feature 2）

**Files:**
- Modify: `memory/blocks.py`（`get_final_recall_score`）
- Modify: `memory/memory_manager.py`（`recall` 排序、`LongTermMemory.search` 排序）
- Modify: `config/agent_config.json` + `.example`（`memory.recency_weight`）
- Test: `test/test_memory_recency.py`

**Interfaces:**
- Produces: `MemoryBlock.get_final_recall_score(recency_weight) -> float` = `relevance*(1-rw)+recency*rw`，relevance 取 hybrid_score/similarity/combined_score 兜底；`recall()` 与 `LongTermMemory.search()` 统一用它排序。

- [ ] **Step 1: 写失败测试**

```python
# test/test_memory_recency.py
import asyncio
from datetime import datetime, timedelta
from memory.blocks import MemoryBlock, MemoryType


def _blk(content, created_days_ago=0, hybrid_score=None, importance=0.5):
    m = MemoryBlock(content=content, type=MemoryType.NOTE, importance=importance)
    m.created_at = datetime.now() - timedelta(days=created_days_ago)
    if hybrid_score is not None:
        m.metadata["hybrid_score"] = hybrid_score
    return m


async def test_final_score_blends_relevance_and_recency():
    old_high_rel = _blk("old relevant", created_days_ago=30, hybrid_score=0.9)
    new_low_rel = _blk("new less relevant", created_days_ago=0, hybrid_score=0.5)
    # recency_weight>0 时，新记忆的 recency 高；验证不是纯 hybrid 排序
    rw = 0.5
    assert old_high_rel.get_final_recall_score(rw) != old_high_rel.metadata["hybrid_score"]
    # 极端：recency_weight=0 应退化为纯 relevance
    assert abs(old_high_rel.get_final_recall_score(0.0) - 0.9) < 1e-9
    assert abs(new_low_rel.get_final_recall_score(0.0) - 0.5) < 1e-9


async def test_recall_sort_blends_recency_not_pure_hybrid():
    from memory import MemoryManager
    mm = MemoryManager(vector_backend=None, use_hybrid_search=False)
    from memory.storage import InMemoryStorage
    mm.long_term._storage = InMemoryStorage()
    old = _blk("偏好意大利菜", created_days_ago=30, hybrid_score=0.95, importance=0.9)
    new = _blk("偏好意大利菜", created_days_ago=0, hybrid_score=0.80, importance=0.9)
    await mm.long_term.add(old)
    await mm.long_term.add(new)
    # 关闭冲突检测避免污染
    mm._conflict_resolver = None
    mm._conflict_resolution_enabled = False
    results = await mm.recall("偏好意大利菜", limit=5, user_id="u1", tiers=["long_term"])
    # recency_weight 默认 0.15：new(0.80相关+高recency) 应排在 old(0.95相关+低recency) 之前
    assert results[0].id == new.id


async def test_recency_weight_zero_is_pure_relevance():
    from memory import MemoryManager
    from utils.config import get_config
    mm = MemoryManager(vector_backend=None, use_hybrid_search=False)
    from memory.storage import InMemoryStorage
    mm.long_term._storage = InMemoryStorage()
    mm._conflict_resolver = None
    mm._conflict_resolution_enabled = False
    old = _blk("old", created_days_ago=30, hybrid_score=0.9)
    new = _blk("new", created_days_ago=0, hybrid_score=0.5)
    await mm.long_term.add(old)
    await mm.long_term.add(new)
    # 临时把 recency_weight 设 0（通过 monkeypatch 配置读取）
    import memory.memory_manager as _mm
    _orig = _mm.get_config
    _mm.get_config = lambda k, d=None: 0.0 if k == "memory.recency_weight" else _orig(k, d)
    try:
        results = await mm.recall("old", limit=5, user_id="u1", tiers=["long_term"])
    finally:
        _mm.get_config = _orig
    assert results[0].id == old.id  # 纯相关：old(0.9) 胜


if __name__ == "__main__":
    asyncio.run(test_final_score_blends_relevance_and_recency())
    asyncio.run(test_recall_sort_blends_recency_not_pure_hybrid())
    asyncio.run(test_recency_weight_zero_is_pure_relevance())
    print("recency ok")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test/test_memory_recency.py`
Expected: `AttributeError: 'MemoryBlock' object has no attribute 'get_final_recall_score'`

- [ ] **Step 3: 配置项**

`config/agent_config.json` 的 `memory` 内追加：
```json
        "recency_weight": 0.15,
        "_comment_recency_weight": "recall 排序 recency 权重(0-1)：0=纯相关性，1=纯时间衰减",
```
`.example` 同步。

- [ ] **Step 4: 实现 get_final_recall_score**

`memory/blocks.py` `MemoryBlock` 类内（`get_combined_score` 之后）加：
```python
    def get_final_recall_score(self, recency_weight: float = 0.15) -> float:
        """recall 最终排序分：relevance*(1-rw) + recency*rw。

        relevance 取 hybrid_score / similarity / combined_score 兜底；
        recency 用一周半衰期的时间衰减。
        """
        relevance = self.metadata.get(
            "hybrid_score",
            self.metadata.get("similarity", self.get_combined_score()),
        )
        try:
            rel = float(relevance)
        except (TypeError, ValueError):
            rel = self.get_combined_score()
        recency = self.get_recency_score(half_life_hours=168.0)
        rw = max(0.0, min(1.0, float(recency_weight)))
        return rel * (1.0 - rw) + recency * rw
```

- [ ] **Step 5: recall/LongTermMemory 排序改用 final score**

`memory/memory_manager.py` `recall` 方法最终排序：
```python
        from utils.config import get_config
        recency_weight = float(get_config("memory.recency_weight", 0.15) or 0.15)
        all_results.sort(
            key=lambda m: m.get_final_recall_score(recency_weight),
            reverse=True
        )
```
（`from utils.config import get_config` 已在 recall 内存在，复用即可，勿重复 import。）

`LongTermMemory.search` 末尾排序：
```python
        results.sort(key=lambda m: m.get_final_recall_score(0.15), reverse=True)
        return results[:limit]
```
（层内用默认 0.15；最终 recall 排序用配置值，二者方向一致。）

- [ ] **Step 6: 跑测试确认通过**

Run: `python test/test_memory_recency.py`
Expected: `recency ok`

- [ ] **Step 7: 提交**

```bash
git add memory/blocks.py memory/memory_manager.py config/agent_config.json config/agent_config.json.example test/test_memory_recency.py
git commit -m "feat(memory): recall 排序引入 recency 加权，修复 hybrid_score 存在时忽略时间衰减"
```

---

## Task 6: memory consolidation trigger（Feature 4）

**Files:**
- Create: `services/trigger/memory_consolidation_trigger.py`
- Modify: `server.py`（lifespan 注册）
- Modify: `config/agent_config.json` + `.example`（`memory.consolidation`）
- Test: `test/test_memory_consolidation.py`

**Interfaces:**
- Consumes: `ConflictResolver.consolidate_pair(a, b)`（Task 3 产出）、`long_term.get_all()`/`update()`/`mm.forget()`。
- Produces: `MemoryConsolidationTrigger().handle() -> dict` 与 `.start()` 注册 APScheduler job `id="memory_consolidation"`。

- [ ] **Step 1: 写失败测试**

```python
# test/test_memory_consolidation.py
import asyncio
from memory import MemoryManager
from memory.blocks import MemoryBlock, MemoryType
from memory.conflict_resolver import ConflictResolver


class _PairResolver(ConflictResolver):
    """conolidate_pair 固定返回合并内容；resolve 不应被调"""
    def __init__(self, merged="合并后:辣食偏好"):
        super().__init__(llm_caller=None)
        self._merged = merged
        self.pair_calls = 0
    async def consolidate_pair(self, a, b):
        self.pair_calls += 1
        return self._merged
    async def resolve(self, new, candidates):
        raise AssertionError("consolidation 不应调 resolve")


def _mm_for_consolidation():
    mm = MemoryManager(vector_backend=None, use_hybrid_search=False)
    from memory.storage import InMemoryStorage
    mm.long_term._storage = InMemoryStorage()
    mm._conflict_resolver = None
    mm._conflict_resolution_enabled = False
    return mm


async def test_consolidation_merges_high_similarity_pair_and_deletes_other():
    from services.trigger.memory_consolidation_trigger import MemoryConsolidationTrigger
    mm = _mm_for_consolidation()
    a = MemoryBlock(id="a", content="用户偏好辣食", type=MemoryType.PREFERENCE,
                    importance=0.9, user_id="u1")
    b = MemoryBlock(id="b", content="用户喜欢辣的菜", type=MemoryType.PREFERENCE,
                    importance=0.9, user_id="u1")
    # 给相同 embedding 保证 cosine=1.0
    a.embedding = [1.0, 0.0, 0.0]
    b.embedding = [1.0, 0.0, 0.0]
    other = MemoryBlock(id="c", content="讨论了天气", type=MemoryType.NOTE,
                        importance=0.6, user_id="u1")
    other.embedding = [0.0, 0.0, 1.0]
    await mm.long_term.add(a)
    await mm.long_term.add(b)
    await mm.long_term.add(other)
    trig = MemoryConsolidationTrigger()
    trig.similarity_threshold = 0.85
    trig.max_pairs_per_user = 10
    trig._make_resolver = lambda: _PairResolver()
    stats = await trig.handle(mm=mm)
    assert stats["merged"] >= 1
    # b 被删，a 内容被合并
    assert await mm.long_term.get("b") is None
    assert "合并后" in (await mm.long_term.get("a")).content
    # other 不受影响
    assert await mm.long_term.get("c") is not None


async def test_consolidation_disabled_by_default():
    from services.trigger.memory_consolidation_trigger import MemoryConsolidationTrigger
    trig = MemoryConsolidationTrigger()
    # 默认 enabled=false（config 未配或 enabled=false）
    assert trig.enabled is False


async def test_consolidation_max_pairs_cap():
    from services.trigger.memory_consolidation_trigger import MemoryConsolidationTrigger
    mm = _mm_for_consolidation()
    # 3 条两两高相似（同 embedding），max_pairs=1 只合并 1 对
    for i, mid in enumerate(["a", "b", "c"]):
        m = MemoryBlock(id=mid, content=f"偏好辣{i}", type=MemoryType.PREFERENCE,
                        importance=0.9, user_id="u1")
        m.embedding = [1.0, 0.0]
        await mm.long_term.add(m)
    trig = MemoryConsolidationTrigger()
    trig.similarity_threshold = 0.85
    trig.max_pairs_per_user = 1
    trig._make_resolver = lambda: _PairResolver()
    stats = await trig.handle(mm=mm)
    assert stats["merged"] == 1


if __name__ == "__main__":
    asyncio.run(test_consolidation_merges_high_similarity_pair_and_deletes_other())
    asyncio.run(test_consolidation_disabled_by_default())
    asyncio.run(test_consolidation_max_pairs_cap())
    print("consolidation ok")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test/test_memory_consolidation.py`
Expected: `ModuleNotFoundError: No module named 'services.trigger.memory_consolidation_trigger'`

- [ ] **Step 3: 配置项**

`config/agent_config.json` 的 `memory` 内追加：
```json
        "consolidation": {
            "enabled": false,
            "cron": "0 5 * * *",
            "similarity_threshold": 0.85,
            "max_pairs_per_user": 10,
            "_comment": "每日 05:00 按 user 维度合并高相似长期记忆（embedding 相似度≥阈值）；破坏性，默认关闭"
        },
```
`.example` 同步。

- [ ] **Step 4: 实现 trigger**

`services/trigger/memory_consolidation_trigger.py`：
```python
"""MemoryConsolidationTrigger：定时按 user 维度合并高相似长期记忆。

与 MemoryDecayTrigger/MemoryPreferenceSummaryTrigger 同构：独立轻量定时任务，
用 CronTrigger.get_scheduler() 共享的 APScheduler 单例注册。

config: memory.consolidation = {enabled, cron, similarity_threshold, max_pairs_per_user}
- enabled: 默认 false（破坏性，保守 opt-in）
- cron: 默认 "0 5 * * *" 每日 05:00（避开 decay 03:00 / preference_summary 04:00）
- similarity_threshold: embedding 余弦相似度阈值（0.85）
- max_pairs_per_user: 每 user 每轮最多合并多少对（10，封顶）

合并复用 ConflictResolver.consolidate_pair：产出合并 content 写入保留方、删除被合并方。
"""
from __future__ import annotations
import math
from loguru import logger
from typing import Any, List, Optional, Tuple
from utils.config import get_config


class MemoryConsolidationTrigger:
    def __init__(self):
        cfg = get_config("memory.consolidation", {}) or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.cron = cfg.get("cron", "0 5 * * *")
        try:
            self.similarity_threshold = float(cfg.get("similarity_threshold", 0.85))
        except (TypeError, ValueError):
            self.similarity_threshold = 0.85
        try:
            self.max_pairs_per_user = int(cfg.get("max_pairs_per_user", 10))
        except (TypeError, ValueError):
            self.max_pairs_per_user = 10

    def _make_resolver(self):
        from memory.conflict_resolver import ConflictResolver
        return ConflictResolver()

    async def handle(self, mm=None) -> dict:
        """扫所有 user 的长期记忆，合并高相似对。"""
        from memory import get_memory_manager
        mm = mm or get_memory_manager()
        resolver = self._make_resolver()
        total_merged = 0
        total_pairs = 0
        try:
            all_m = await mm.long_term.get_all()
        except Exception as e:
            logger.warning(f"[Consolidation] get_all 失败: {e}")
            return {"users": 0, "pairs": 0, "merged": 0, "error": str(e)}
        # 按 user 分组
        by_user: dict[str, List] = {}
        for m in all_m:
            by_user.setdefault(m.user_id or "default", []).append(m)
        for uid, mems in by_user.items():
            pairs = self._top_similar_pairs(mems, self.max_pairs_per_user)
            for a, b in pairs:
                total_pairs += 1
                try:
                    merged = await resolver.consolidate_pair(a, b)
                    if not merged:
                        continue
                    a.content = merged
                    a.importance = min(1.0, max(a.importance, b.importance) + 0.05)
                    a.touch()
                    await mm.long_term.update(a)
                    await mm.forget(b.id)
                    total_merged += 1
                except Exception as e:
                    logger.warning(f"[Consolidation] 合并对失败 a={a.id} b={b.id}: {e}")
        mm.invalidate_search_index()
        logger.info(f"[Consolidation] users={len(by_user)}, pairs={total_pairs}, merged={total_merged}")
        return {"users": len(by_user), "pairs": total_pairs, "merged": total_merged}

    def _top_similar_pairs(self, mems: List, cap: int) -> List[Tuple]:
        scored: List[Tuple[float, Any, Any]] = []
        for i in range(len(mems)):
            ei = mems[i].embedding
            if not ei:
                continue
            for j in range(i + 1, len(mems)):
                ej = mems[j].embedding
                if not ej:
                    continue
                sim = self._cosine(ei, ej)
                if sim >= self.similarity_threshold:
                    scored.append((sim, mems[i], mems[j]))
        scored.sort(key=lambda x: x[0], reverse=True)
        used: set = set()
        out: List[Tuple] = []
        for sim, a, b in scored:
            if a.id in used or b.id in used:
                continue
            out.append((a, b))
            used.add(a.id)
            used.add(b.id)
            if len(out) >= cap:
                break
        return out

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("[Consolidation] disabled (memory.consolidation.enabled=false), skip")
            return
        try:
            from services.trigger.cron_trigger import CronTrigger
            from apscheduler.triggers.cron import CronTrigger as APSCronTrigger
            sched = CronTrigger.get_scheduler()
            trigger = APSCronTrigger.from_crontab(self.cron, timezone="Asia/Shanghai")
            sched.add_job(
                self.handle,
                trigger=trigger,
                id="memory_consolidation",
                coalesce=True,
                max_instances=1,
                misfire_grace_time=120,
                replace_existing=True,
            )
            logger.info(f"[Consolidation] registered cron='{self.cron}', "
                        f"thr={self.similarity_threshold}, max_pairs={self.max_pairs_per_user}")
        except Exception as e:
            logger.warning(f"[Consolidation] start failed: {e}")
```

- [ ] **Step 5: server.py lifespan 注册**

`server.py` 在 `MemoryPreferenceSummaryTrigger().start()` 块之后、`yield` 之前插入：
```python
    try:
        from services.trigger.memory_consolidation_trigger import MemoryConsolidationTrigger
        await MemoryConsolidationTrigger().start()
    except Exception as e:
        logger.error(f"[Lifespan] memory_consolidation_trigger start failed (non-fatal): {e}", exc_info=True)
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python test/test_memory_consolidation.py`
Expected: `consolidation ok`

- [ ] **Step 7: 提交**

```bash
git add services/trigger/memory_consolidation_trigger.py server.py config/agent_config.json config/agent_config.json.example test/test_memory_consolidation.py
git commit -m "feat(memory): MemoryConsolidationTrigger 定时按 user 合并高相似长期记忆(默认关闭)"
```

---

## Task 7: LLM 自主记忆工具 + ContextVar 上下文（Feature 5）

**Files:**
- Create: `utils/common/memory_context.py`
- Create: `tools/memory_tool.py`
- Modify: `tools/__init__.py`（注册）
- Modify: `api/chat/chat_routes.py`（`chat_stream`/`chat` 接 set_memory_context）
- Test: `test/test_memory_tools.py`

**Interfaces:**
- Produces: `set_memory_context(user_id, session_id)` / `get_memory_context() -> MemoryContext`；LangChain 工具 `memory_search(query, limit)` / `memory_insert(content, type, importance=0.8)` / `memory_update(memory_id, content)`，工具内懒 import memory 包，通过 context 自动取 user/session。

- [ ] **Step 1: 写失败测试**

```python
# test/test_memory_tools.py
import asyncio
import json
from utils.common.memory_context import set_memory_context, reset_memory_context
from memory import MemoryManager


def _mm_isolated():
    mm = MemoryManager(vector_backend=None, use_hybrid_search=False)
    from memory.storage import InMemoryStorage
    mm.long_term._storage = InMemoryStorage()
    mm._conflict_resolver = None
    mm._conflict_resolution_enabled = False
    # 让工具内 get_memory_manager 返回这个实例
    import tools.memory_tool as mt
    mt.get_memory_manager = lambda: mm
    return mm


async def test_memory_search_returns_user_memories():
    mm = _mm_isolated()
    await mm.remember("用户偏好辣食", type="preference", importance=0.9, user_id="u1")
    set_memory_context(user_id="u1", session_id="s1")
    from tools.memory_tool import memory_search
    result = await memory_search.ainvoke({"query": "偏好", "limit": 5})
    data = json.loads(result)
    assert any("辣" in d["content"] for d in data)
    reset_memory_context()


async def test_memory_search_isolates_by_user():
    mm = _mm_isolated()
    await mm.remember("A 的偏好", type="preference", importance=0.9, user_id="A")
    await mm.remember("B 的偏好", type="preference", importance=0.9, user_id="B")
    set_memory_context(user_id="A", session_id="s1")
    from tools.memory_tool import memory_search
    result = await memory_search.ainvoke({"query": "偏好", "limit": 5})
    data = json.loads(result)
    assert any("A" in d["content"] for d in data)
    assert not any("B" in d["content"] for d in data)
    reset_memory_context()


async def test_memory_insert_stores_and_returns_id():
    mm = _mm_isolated()
    set_memory_context(user_id="u1", session_id="s1")
    from tools.memory_tool import memory_insert
    result = await memory_insert.ainvoke({"content": "用户喜欢 python", "type": "preference"})
    assert "memory_id=" in result
    mems = await mm.long_term.get_all()
    assert any("python" in m.content for m in mems)
    reset_memory_context()


async def test_memory_update_rewrites_content():
    mm = _mm_isolated()
    m = await mm.remember("旧偏好", type="preference", importance=0.9, user_id="u1")
    set_memory_context(user_id="u1", session_id="s1")
    from tools.memory_tool import memory_update
    result = await memory_update.ainvoke({"memory_id": m.id, "content": "新偏好"})
    assert "updated" in result
    assert (await mm.long_term.get(m.id)).content == "新偏好"
    reset_memory_context()


async def test_memory_update_forbidden_across_users():
    mm = _mm_isolated()
    m = await mm.remember("A 的偏好", type="preference", importance=0.9, user_id="A")
    set_memory_context(user_id="B", session_id="s1")
    from tools.memory_tool import memory_update
    result = await memory_update.ainvoke({"memory_id": m.id, "content": "篡改"})
    assert "forbidden" in result
    reset_memory_context()


async def test_memory_update_not_found():
    mm = _mm_isolated()
    set_memory_context(user_id="u1", session_id="s1")
    from tools.memory_tool import memory_update
    result = await memory_update.ainvoke({"memory_id": "nope", "content": "x"})
    assert "not found" in result
    reset_memory_context()


if __name__ == "__main__":
    for fn in [test_memory_search_returns_user_memories,
               test_memory_search_isolates_by_user,
               test_memory_insert_stores_and_returns_id,
               test_memory_update_rewrites_content,
               test_memory_update_forbidden_across_users,
               test_memory_update_not_found]:
        asyncio.run(fn())
    print("tools ok")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python test/test_memory_tools.py`
Expected: `ModuleNotFoundError: No module named 'utils.common.memory_context'`

- [ ] **Step 3: 实现 memory_context**

`utils/common/memory_context.py`：
```python
"""记忆工具运行时上下文 — ContextVar 自动捕获当前 user_id/session_id。

chat 入口 set_memory_context(user_id, session_id)；记忆工具内 get_memory_context() 取值，
LLM 只传 query/content/memory_id。async 任务内 ContextVar 自动传播。
"""
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass
class MemoryContext:
    user_id: Optional[str]
    session_id: Optional[str]


_var: ContextVar[MemoryContext] = ContextVar(
    "memory_context", default=MemoryContext(None, None)
)


def set_memory_context(user_id: Optional[str], session_id: Optional[str]) -> None:
    _var.set(MemoryContext(user_id=user_id, session_id=session_id))


def get_memory_context() -> MemoryContext:
    return _var.get()


def reset_memory_context() -> None:
    _var.set(MemoryContext(None, None))
```

- [ ] **Step 4: 实现三个工具**

`tools/memory_tool.py`：
```python
"""Letta 式自主记忆工具：memory_search / memory_insert / memory_update。

user_id/session_id 由运行时 ContextVar 自动捕获；LLM 只传 query/content/memory_id。
模块顶部只 import 轻量依赖（langchain_core.tools/loguru），memory 包懒 import，
避免 jieba/chromadb 在工具发现阶段被拖入。
"""
import json
from typing import Optional
from loguru import logger
from langchain_core.tools import tool


@tool
async def memory_search(query: str, limit: int = 5) -> str:
    """搜索当前用户的长期记忆，返回相关记忆列表（id/content/type/importance）。"""
    try:
        from memory import get_memory_manager
        from utils.common.memory_context import get_memory_context
        ctx = get_memory_context()
        mm = get_memory_manager()
        results = await mm.recall(
            query=query, limit=limit,
            user_id=ctx.user_id, session_id=ctx.session_id,
            tiers=["long_term"],
        )
        return json.dumps([
            {"id": m.id, "content": m.content,
             "type": getattr(m.type, "value", str(m.type)),
             "importance": m.importance}
            for m in results
        ], ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[memory_search] failed: {e}")
        return json.dumps([])


@tool
async def memory_insert(content: str, type: str = "note", importance: float = 0.8) -> str:
    """写入一条持久记忆（importance 默认 0.8 落 long_term，自动触发冲突检测，必要时合并/更新）。"""
    try:
        from memory import get_memory_manager
        from utils.common.memory_context import get_memory_context
        ctx = get_memory_context()
        mm = get_memory_manager()
        m = await mm.remember(
            content=content, type=type, importance=importance,
            user_id=ctx.user_id, session_id=ctx.session_id,
            source_session_id=ctx.session_id,
        )
        return f"stored memory_id={m.id}"
    except Exception as e:
        logger.warning(f"[memory_insert] failed: {e}")
        return f"error: {e}"


@tool
async def memory_update(memory_id: str, content: str) -> str:
    """更新指定记忆内容（重嵌）；仅可改当前用户自己的记忆。"""
    try:
        from memory import get_memory_manager
        from utils.common.memory_context import get_memory_context
        ctx = get_memory_context()
        mm = get_memory_manager()
        m = await mm.long_term.get(memory_id)
        if m is None:
            return "not found"
        if m.user_id != ctx.user_id:
            return "forbidden"
        m.content = content
        m.touch()
        await mm.long_term.update(m)
        return "updated"
    except Exception as e:
        logger.warning(f"[memory_update] failed: {e}")
        return f"error: {e}"
```

- [ ] **Step 5: 注册工具**

`tools/__init__.py` 顶部 import 之后追加：
```python
from .memory_tool import memory_search, memory_insert, memory_update
```
`__all__` 列表追加 `"memory_search"`, `"memory_insert"`, `"memory_update"`。

- [ ] **Step 6: chat 入口接 context**

`api/chat/chat_routes.py` 顶部 import 区加：
```python
from utils.common.memory_context import set_memory_context
```
`chat_stream` 在 `session_id = _resolve_session_id(user_id, frontend_session_id)` 之后插入：
```python
        set_memory_context(user_id=user_id, session_id=session_id)
```
`chat` 端点同样在 `session_id = _resolve_session_id(...)` 之后插入同一行。

- [ ] **Step 7: 跑测试确认通过**

Run: `python test/test_memory_tools.py`
Expected: `tools ok`

- [ ] **Step 8: 提交**

```bash
git add utils/common/memory_context.py tools/memory_tool.py tools/__init__.py api/chat/chat_routes.py test/test_memory_tools.py
git commit -m "feat(memory): Letta 式自主记忆工具(search/insert/update)+ContextVar 上下文自动捕获"
```

---

## Task 8: 前后端聊天回归验证

**Files:**
- 无代码改动；运行验证。

- [ ] **Step 1: 全量 memory 单测**

Run: `python test/test_memory_provenance.py && python test/test_memory_conflict.py && python test/test_memory_recency.py && python test/test_memory_consolidation.py && python test/test_memory_tools.py`
Expected: 全部 `ok`。

- [ ] **Step 2: 既有 memory 测试回归**

Run: `python test/test_memory_manager.py`
Expected: `✅ Memory 模块功能验证通过`（确认三层记忆+混合搜索未受影响）。

- [ ] **Step 3: 工具发现回归**

Run: `python -c "from tools import get_tool_registry; r=get_tool_registry(); names={t.name for t in r.get_all() if hasattr(t,'name')}; print('memory_search' in names, 'memory_insert' in names, 'memory_update' in names)"`
Expected: `True True True`

- [ ] **Step 4: 启动后端**

Run: `python server.py`（后台运行）
Expected: 日志含 `conflict_resolution=True`、`[Consolidation] disabled ... skip`（默认关闭）、`triggers loaded`、无启动异常。

- [ ] **Step 5: 前端启动 + 聊天冒烟**

Run: 前端 `npm run dev`（或 `start_vite.bat`）
操作：打开 ChatView，发一条普通消息（如"你好"），确认流式回复正常、无 500。
Expected: 聊天链路正常，set_memory_context 接线未破坏请求。

- [ ] **Step 6: agent opt-in 记忆工具冒烟（可选）**

在前端 Agent 管理页给某 agent 的 `tools` 列表加入 `memory_search`/`memory_insert`，对该 agent 发"记住我喜欢简洁回答"，再发"你还记得我的偏好吗"。
Expected: 第二轮回复体现已写入记忆（agent 调 memory_search 命中）。

- [ ] **Step 7: 冲突检测冒烟（需 LLM 可用）**

Run: `python -c "import asyncio; from memory import get_memory_manager; from memory.blocks import MemoryType; 
async def t():
  mm=get_memory_manager()
  await mm.remember('用户偏好意大利菜', type='preference', importance=0.9, user_id='utest')
  await mm.remember('用户偏好墨西哥菜', type='preference', importance=0.9, user_id='utest')
  ms=await mm.long_term.get_all()
  print([(m.content,m.importance) for m in ms])
asyncio.run(t())"`
Expected: 第二条触发冲突检测后，长期记忆中偏好被合并/更新为一条（非两条矛盾共存）。LLM 不可用时降级为 ADD（两条共存，符合降级预期）。

- [ ] **Step 8: 提交验证记录（如需）**

无需代码提交；本任务为验证 gate，通过即整组特性完成。

---

## Self-Review（计划作者自查）

**1. Spec 覆盖**：
- Feature 1（冲突检测）→ Task 2/3/4 ✓
- Feature 2（recency）→ Task 5 ✓
- Feature 3（provenance）→ Task 1 ✓
- Feature 4（consolidation）→ Task 6 ✓
- Feature 5（工具）→ Task 7 ✓
- 前后端聊天验证 → Task 8 ✓
- preference_summary 复用 resolver → Task 4 Step 6 ✓
- 配置项（conflict_resolution/recency_weight/consolidation）→ Task 4/5/6 ✓

**2. 占位符扫描**：无 TBD/TODO；每个 code step 含完整代码。✓

**3. 类型/方法名一致性**：
- `ConflictResolver.resolve(new, candidates)` / `consolidate_pair(a,b)` — Task 3 定义，Task 4/6 使用一致 ✓
- `LongTermMemory.update(memory)` — Task 2 定义，Task 4/6/7 使用一致 ✓
- `MemoryBlock.get_final_recall_score(rw)` — Task 5 定义并使用一致 ✓
- `set_memory_context`/`get_memory_context` — Task 7 定义，chat 接线+工具使用一致 ✓
- `mm._conflict_resolver` / `_conflict_resolution_enabled` — Task 4 定义，Task 5/6/7 测试 stub 一致 ✓

**4. 依赖顺序**：Task 1(provenance) → Task 2(update) → Task 3(resolver) → Task 4(remember 接入) → Task 5(recency) → Task 6(consolidation，依赖 resolver.consolidate_pair) → Task 7(tools，依赖 remember+update) → Task 8(验证)。符合用户要求的 provenance→冲突→recency→consolidation→工具。✓
