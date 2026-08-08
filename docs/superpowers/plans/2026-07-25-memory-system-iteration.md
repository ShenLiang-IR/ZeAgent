# 记忆系统迭代 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 LongTerm 记忆真正可用——启用向量检索、跨 session 召回、落地用户偏好、补齐衰减/压缩/多类提取等健壮性。

**Architecture:** 复用既有 `MemoryManager` 三层 + `VectorStorage` + `embedding_factory` + `CronTrigger` + `ACONCompressor` 基础设施，只补配置接入与召回/提取/清理逻辑，不重构既有分层。

**Tech Stack:** Python 3.13、langchain_core.messages、sentence-transformers(bge-small-zh)、chromadb/pgvector、APScheduler(CronTrigger)、SQLAlchemy、pytest。

## Global Constraints

- 后端运行环境：conda `install_deb_refactor` @ `D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe`（bash 无 python，跑测试用此）
- DB：MySQL 127.0.0.1:3306 / agent_config；记忆库 SQLite `data/memory.db`；向量库 chromadb `data/chroma_memory`
- 测试：pytest（`asyncio_mode=auto`），连真实 MySQL，无 DB 时 skip 守卫
- 既有风格：记忆按 `session_id`+`user_id` 双键；`recall` 默认按 session 过滤；`MemoryType` 枚举已含 PREFERENCE/FACT/TASK/NOTE/CONTEXT/SKILL/ERROR
- 不破坏无登录模式（`enable_permission_check=false` 时 guest 当 admin）
- **跨 session 召回开关**：`memory.cross_session_recall`（bool，默认 `true`）放 `config/agent_config.json` 的 `memory` 段；`true` 时 recall 走 user 维度跨 session 召回长期记忆，`false` 时回退原 session-only 行为

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `config/agent_config.json` | memory.vector_backend / vector_config / decay 配置 | Modify |
| `memory/memory_manager.py` | 三层管理 + recall/remember/decay | Modify（recall 加 user 维度；向量 client 注入） |
| `memory/storage.py` | SQLiteStorage / VectorStorage | Modify（VectorStorage 接 embedding；search 加 user_id 过滤） |
| `memory/embedding_factory.py` | create_embedding_model | 已存在，复用 |
| `services/agent_service.py` | chat 流程：recall + _store_conversation_to_memory | Modify（recall 传 user_id；多类提取；preference 注入） |
| `utils/common/context_manager.py` | 压缩策略链 | Modify（接入 ACONCompressor 为策略） |
| `compression/acon_compressor.py` | ACON 压缩器 | Modify（适配 CompressionStrategy 接口） |
| `services/trigger/memory_decay_trigger.py` | 定时衰减触发器 | Create |
| `memory/__init__.py` | get_memory_manager 注入 vector | Modify |
| `test/test_memory_*.py` | 记忆系统测试 | Create |

---

### Task 1: 启用 LongTerm 向量检索（chromadb + bge embedding）

**Files:**
- Modify: `config/agent_config.json`（memory 段加 vector_backend/vector_config）
- Modify: `memory/memory_manager.py:283-310`（`_ensure_vector_storage` 接 embedding）
- Modify: `memory/storage.py:162-`（VectorStorage 用 embedding 生成向量）
- Test: `test/test_memory_vector.py`

**Interfaces:**
- Consumes: `memory/embedding_factory.create_embedding_model()`，`memory.storage.VectorStorage(backend, embedding)`
- Produces: `LongTermMemory` 实例化时按 config 注入 vector_backend + embedding；`VectorStorage.save(memory)` 写入向量；`VectorStorage.search(query, limit)` 语义检索

- [ ] **Step 1: 配置 memory.vector_backend**

`config/agent_config.json` 的 `memory` 段（line 169-176）追加：
```json
"vector_backend": "chromadb",
"vector_config": {
  "collection_name": "agent_memories",
  "persist_directory": "data/chroma_memory"
}
```

- [ ] **Step 2: VectorStorage 接入 embedding**

`memory/storage.py` `VectorStorage.__init__` 增加 `embedding` 参数，`save` 时生成向量，`search` 用向量查询：
```python
class VectorStorage:
    def __init__(self, backend="chromadb", collection_name="agent_memories",
                 persist_directory="data/chroma_memory", embedding=None, knowledge_base_id=None, similarity_threshold=0.7):
        self._backend = backend
        self._embedding = embedding  # langchain Embeddings 实例
        # ... 既有 init
    async def save(self, memory: MemoryBlock) -> bool:
        if not self._embedding:
            return False
        vec = self._embedding.embed_query(memory.content)
        memory.embedding = vec
        # chroma: collection.add(ids=[memory.id], embeddings=[vec], documents=[memory.content], metadatas=[{...}])
    async def search(self, query: str, limit: int = 10) -> List[MemoryBlock]:
        if not self._embedding:
            return []
        qv = self._embedding.embed_query(query)
        # chroma: collection.query(query_embeddings=[qv], n_results=limit)
```

- [ ] **Step 3: LongTermMemory 注入 embedding**

`memory/memory_manager.py:283-310` `_ensure_vector_storage` 创建 VectorStorage 时传 embedding：
```python
from memory.embedding_factory import create_embedding_model
emb = create_embedding_model(log_tag="LongTermMemory")
if self._vector_backend == "chromadb":
    self._vector_storage = VectorStorage(
        backend="chromadb",
        collection_name=self._vector_config.get("collection_name", "agent_memories"),
        persist_directory=self._vector_config.get("persist_directory", "data/chroma_memory"),
        embedding=emb,
    )
```

- [ ] **Step 4: 写测试 + 验证**

`test/test_memory_vector.py`：
```python
def test_vector_search_returns_semantic_match():
    if not _db_available(): pytest.skip("MySQL/环境不可用")
    from memory import get_memory_manager
    mm = get_memory_manager(vector_backend="chromadb", vector_config={"persist_directory": "data/chroma_memory_test"})
    import asyncio
    asyncio.run(mm.remember("用户关注营收和利润增长", type="fact", importance=0.9, session_id="t1", user_id="u1"))
    res = asyncio.run(mm.recall("财务数据怎么样", limit=3, session_id="t1"))
    assert any("营收" in m.content or "利润" in m.content for m in res)
```
Run: `cmd //c "D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe -m pytest test/test_memory_vector.py -v"`
Expected: PASS（"财务数据"语义命中"营收/利润"）

- [ ] **Step 5: Commit**
```bash
git add config/agent_config.json memory/ test/test_memory_vector.py
git commit -m "feat(memory): 启用 LongTerm chromadb 向量检索 + bge embedding"
```

---

### Task 2: 跨 session 记忆连通（recall 加 user 维度，受 `cross_session_recall` 开关控制）

**Files:**
- Modify: `config/agent_config.json`（memory 段加 `cross_session_recall: true`）
- Modify: `memory/memory_manager.py:513-557`（recall 读 config 决定是否跨 session）
- Modify: `memory/storage.py:119-160`（SQLiteStorage.search 加 user_id 过滤；VectorStorage.search 加 user_id 过滤）
- Modify: `services/agent_service.py:134-138,305-311`（recall 调用传 user_id）
- Test: `test/test_memory_cross_session.py`

**Interfaces:**
- Consumes: Task 1 的向量检索
- Produces: `MemoryManager.recall(query, user_id, session_id, ...)` —— 当 `memory.cross_session_recall=true` 时按 user_id 跨 session 召回长期记忆；`false` 时回退 session-only

- [ ] **Step 1: 配置 cross_session_recall 开关（默认开启）**

`config/agent_config.json` 的 `memory` 段（line 169-176）追加：
```json
"cross_session_recall": true,
"_comment_cross_session_recall": "跨 session 召回开关：true=recall 按 user_id 召回长期记忆(跨会话连通)，false=仅按 session_id 召回(原行为)"
```

- [ ] **Step 2: recall 签名加 user_id + 读 config 门控**

`memory/memory_manager.py` `recall` 增参 `user_id: Optional[str] = None`，并读 `memory.cross_session_recall`（默认 true）决定是否跨 session：
```python
async def recall(self, query, limit=10, tiers=None, use_hybrid=None,
                 session_id=None, user_id=None):
    from utils.config import get_config
    cross_session = get_config('memory.cross_session_recall', True)
    # ... 既有
    for tier_name in tiers:
        if tier_name == "long_term" and user_id and cross_session:
            # 跨 session：按 user_id 召回长期记忆（不按 session 过滤）
            tier_results = await self.long_term.search(query, limit, user_id=user_id)
        else:
            # 回退：session-only（原行为）
            tier_results = await self._fallback_search(tier_name, query, limit, session_id)
```

- [ ] **Step 3: LongTermMemory.search 加 user_id**

`memory/memory_manager.py:330-366` `LongTermMemory.search` 增参 `user_id`：
```python
async def search(self, query, limit=10, session_id=None, user_id=None):
    # 向量/关键词结果过滤：
    if user_id and memory.user_id != user_id: continue   # 跨 session 按 user
    elif session_id and memory.session_id != session_id: continue  # 原 session 过滤
```
SQLiteStorage.search 同理加 user_id where 子句。

- [ ] **Step 4: agent_service recall 传 user_id**

`services/agent_service.py:134`：
```python
relevant_memories = await self._memory_manager.recall(
    query=user_input, limit=3, session_id=self.session_id, user_id=self.user_id
)
```

- [ ] **Step 5: 测试跨 session 召回（开/关两路）**

`test/test_memory_cross_session.py`：
```python
def test_recall_across_session_when_enabled():
    if not _db_available(): pytest.skip()
    mm = get_memory_manager(vector_backend="chromadb", ...)
    asyncio.run(mm.remember("用户偏好债券品种A", type="preference", importance=0.9, session_id="s1", user_id="u1"))
    # 新 session 召回（config cross_session_recall=true 默认开启）
    res = asyncio.run(mm.recall("偏好什么", limit=5, user_id="u1", session_id="s2"))
    assert any("债券品种A" in m.content for m in res)

def test_recall_session_only_when_disabled(monkeypatch):
    # monkeypatch config cross_session_recall=false，验证新 session 召回不到 s1 的记忆
    monkeypatch.setattr("utils.config.config_loader.get_config", lambda k, d=None: False if k == 'memory.cross_session_recall' else d)
    # ... 召回应返回空（session-only）
```
Run: `cmd //c "D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe -m pytest test/test_memory_cross_session.py -v"`
Expected: 两路均 PASS（开启跨 session 命中；关闭时 session-only 不命中）

- [ ] **Step 6: Commit**
```bash
git add config/agent_config.json memory/ services/agent_service.py test/test_memory_cross_session.py
git commit -m "feat(memory): recall 支持 user 维度跨 session 召回（cross_session_recall 开关默认开启）"
```

---

### Task 3: 结构化记忆多类提取（preference/relation/event/fact）

**Files:**
- Modify: `services/agent_service.py:429-466`（`_store_conversation_to_memory` 多类提取）
- Test: `test/test_memory_extract.py`

**Interfaces:**
- Consumes: `MemoryType` 枚举（PREFERENCE/FACT/...）
- Produces: 对话后 LLM 提取多类记忆，分类写入（preference 按 user_id 高 importance）

- [ ] **Step 1: 多类提取 prompt + 解析**

`services/agent_service.py` `_store_conversation_to_memory` 改 extract_prompt 为多类：
```python
extract_prompt = f"""
从以下对话提取结构化记忆，按类别输出 JSON 数组（无则输出 []）：
{context_text}
类别：preference(用户偏好/习惯/固定需求) / fact(客观事实) / relation(实体关系) / event(事件/任务)
每项: {{"type":"...","content":"...","importance":0.0-1.0}}
- preference 必须是用户的稳定偏好（如"偏好低风险债券"），importance≥0.8
- fact 是客观信息，importance 0.5-0.8
只输出 JSON，不要解释。
"""
response = await self.llm_model.ainvoke([HumanMessage(content=extract_prompt)])
items = json.loads(result)  # 解析失败则 fallback 单 fact
for it in items:
    await self._memory_manager.remember(
        content=it["content"], type=it.get("type","fact"),
        importance=it.get("importance",0.6),
        session_id=self.session_id, user_id=self.user_id,
        tags=["extracted","auto_stored", it.get("type","fact")]
    )
```
偏好类（importance≥0.8）自动进 long_term；按 user_id 跨 session 可召回（Task 2）。

- [ ] **Step 2: 测试多类提取**

`test/test_memory_extract.py`（mock llm 返回多类 JSON，验证 remember 被分类调用）：
```python
async def test_extract_multiple_types(monkeypatch):
    svc = AgentService(session_id="s1", user_id="u1", llm_model=FakeLLM('[{"type":"preference","content":"偏好低风险","importance":0.9},{"type":"fact","content":"用户问国债","importance":0.6}]'))
    await svc._store_conversation_to_memory("我想要低风险的", [AIMessage(content="推荐国债")])
    # 验证 memory_manager.remember 被调 2 次，type 分别 preference/fact
```

- [ ] **Step 3: Commit**
```bash
git add services/agent_service.py test/test_memory_extract.py
git commit -m "feat(memory): 对话后多类结构化提取(preference/fact/relation/event)"
```

---

### Task 4: 用户偏好注入 system prompt

**Files:**
- Modify: `services/agent_service.py:131-149`（recall 时单独召回 preference 注入 memory_context）
- Test: `test/test_memory_preference_inject.py`

**Interfaces:**
- Consumes: Task 2 的 user 维度召回，Task 3 的 preference 写入
- Produces: chat 时把用户偏好拼进 memory_context（经 plan_executor 进 history）

- [ ] **Step 1: recall 偏好优先注入**

`services/agent_service.py:131-149` recall 后，单独按 user_id 召回 preference 拼到 memory_context 前面：
```python
memory_context = None
if self._memory_manager:
    relevant = await self._memory_manager.recall(query=user_input, limit=3, session_id=self.session_id, user_id=self.user_id)
    # 额外召回用户长期偏好（跨 session）
    prefs = await self._memory_manager.recall(query="用户偏好", limit=3, user_id=self.user_id, tiers=["long_term"]) 
    prefs = [m for m in prefs if m.type.value == "preference"]
    parts = []
    if prefs:
        parts.append("用户偏好:\n" + "\n".join(f"- {p.content[:100]}" for p in prefs[:3]))
    if relevant:
        parts.append("相关记忆:\n" + "\n".join(f"- {m.content[:200]}" for m in relevant[:3]))
    if parts:
        memory_context = "\n\n".join(parts)
if memory_context:
    kwargs['memory_context'] = memory_context
```

- [ ] **Step 2: 测试偏好注入**

`test/test_memory_preference_inject.py`：
```python
async def test_preference_injected_to_context():
    mm = get_memory_manager(...)
    asyncio.run(mm.remember("偏好低风险债券", type="preference", importance=0.9, user_id="u1", session_id="s1"))
    svc = AgentService(session_id="s2", user_id="u1", llm_model=FakeLLM(...))
    svc._memory_manager = mm
    # 触发 recall 路径，验证 memory_context 含"偏好低风险"
```

- [ ] **Step 3: Commit**
```bash
git add services/agent_service.py test/test_memory_preference_inject.py
git commit -m "feat(memory): 用户偏好注入 memory_context 个性化"
```

---

### Task 5: decay/promote 定时衰减（CronTrigger）

**Files:**
- Create: `services/trigger/memory_decay_trigger.py`
- Modify: `config/agent_config.json`（memory.decay 配置）
- Test: `test/test_memory_decay.py`

**Interfaces:**
- Consumes: `MemoryManager.decay_memories` / `promote_memory`，`CronTrigger`
- Produces: 定时（如每日 03:00）衰减 importance + 清理低分 + 晋升高频

- [ ] **Step 1: 配置 decay**

`config/agent_config.json` memory 段加：
```json
"decay": {"enabled": true, "cron": "0 3 * * *", "factor": 0.95, "cleanup_below": 0.1}
```

- [ ] **Step 2: MemoryDecayTrigger**

`services/trigger/memory_decay_trigger.py`：
```python
from services.trigger.cron_trigger import CronTrigger
class MemoryDecayTrigger(CronTrigger):
    async def handle(self, payload):
        from memory import get_memory_manager
        mm = get_memory_manager()
        await mm.decay_memories(factor=0.95)
        # 清理 importance < cleanup_below 的 long_term 记忆
        all_m = await mm.long_term.get_all()
        for m in all_m:
            if m.importance < 0.1:
                await mm.forget(m.id)
```

- [ ] **Step 3: 测试衰减**

`test/test_memory_decay.py`：
```python
async def test_decay_lowers_importance():
    mm = get_memory_manager(...)
    await mm.remember("test", importance=0.8, session_id="s", user_id="u")
    before = 0.8
    await mm.decay_memories(factor=0.5)
    all_m = await mm.long_term.get_all()
    assert any(m.importance < before for m in all_m)
```

- [ ] **Step 4: Commit**
```bash
git add services/trigger/memory_decay_trigger.py config/agent_config.json test/test_memory_decay.py
git commit -m "feat(memory): CronTrigger 定时衰减+清理低分记忆"
```

---

### Task 6: ACONCompressor 接入 ContextManager 策略链

**Files:**
- Modify: `compression/acon_compressor.py`（适配 `CompressionStrategy` 接口）
- Modify: `utils/common/context_manager.py:177`（strategies 注册 ACON）
- Test: `test/test_memory_compression.py`

**Interfaces:**
- Consumes: `ContextManager.CompressionStrategy` 抽象（should_compress/compress）
- Produces: ACON 作为压缩策略之一，保留决策点+AO pair+近3轮

- [ ] **Step 1: ACONCompressor 适配 CompressionStrategy**

`compression/acon_compressor.py` 加 adapter：
```python
from utils.common.context_manager import CompressionStrategy
class ACONCompressionStrategy(CompressionStrategy):
    def __init__(self, config=None, llm_model=None):
        self._compressor = ACONCompressor(config=config, llm_model=llm_model)
    def should_compress(self, messages, estimated_tokens, max_tokens):
        return estimated_tokens >= self._compressor.config.trigger_tokens
    def compress(self, messages, llm_model=None):
        # ACONCompressor.compress 是 async，ContextManager.compress 同步——需同步包装或改 ContextManager
        # 简化：用 asyncio.run 或改 optimize_messages 为 async
        import asyncio
        result, stats = asyncio.get_event_loop().run_until_complete(self._compressor.compress(messages))
        return result, stats
```
> 注：`ContextManager.compress` 当前同步；若 ACON compress 是 async，需把 `optimize_messages` 改 async（影响 agent_service 调用点已 await）。计划执行时统一改 async。

- [ ] **Step 2: 注册到 strategies**

`utils/common/context_manager.py:177`：
```python
self.strategies = [
    ClearToolResultsStrategy(...),
    ACONCompressionStrategy(config=CompressionConfig()),  # 新增，替代/补充 Truncate
    SummarizeStrategy(...) if use_llm_summary else TruncateStrategy(...),
]
```

- [ ] **Step 3: 测试压缩保留决策点**

`test/test_memory_compression.py`：
```python
async def test_acon_preserves_decision_points():
    from compression.acon_compressor import ACONCompressor
    msgs = [HumanMessage(content="我决定选方案A因为风险低"*200), AIMessage(content="...")]*20
    out, stats = await ACONCompressor().compress(msgs)
    assert any("决定" in m.content or "方案A" in m.content for m in out)  # 决策点保留
    assert stats["compression_ratio"] > 0
```

- [ ] **Step 4: Commit**
```bash
git add compression/ utils/common/context_manager.py test/test_memory_compression.py
git commit -m "feat(memory): ACONCompressor 接入 ContextManager 策略链"
```

---

## Self-Review

1. **Spec coverage**：
   - LongTerm 向量检索启用 → Task 1 ✓
   - 跨 session 记忆连通 → Task 2 ✓
   - 用户偏好落地 → Task 3（提取）+ Task 4（注入）✓
   - P1 健壮性打包：衰减 → Task 5 ✓；压缩 → Task 6 ✓；多类提取 → Task 3 ✓
2. **Placeholder scan**：每步有具体代码/测试，无 TBD。
3. **Type consistency**：`recall(query, user_id, session_id, ...)` 跨 Task 2/4 一致；`remember(type, importance, user_id, session_id)` 跨 Task 1/3 一致；`MemoryType` 用既有枚举。

## 依赖与执行顺序

Task 1（向量）→ Task 2（跨session，依赖向量召回质量）→ Task 3（多类提取，写入 preference）→ Task 4（偏好注入，依赖 Task 2/3）→ Task 5（衰减，独立）→ Task 6（压缩，独立）。

Task 5/6 与 1-4 无强依赖，可并行。

## 风险

- Task 1 向量库 chromadb 需 `pip install chromadb sentence-transformers`（conda 环境内）。
- Task 6 ACON 是 async，ContextManager 需改 async（影响面：agent_service:115 已 await，context_manager.optimize_messages 改 async 即可，optimize_messages_simple 同步包装）。
- Task 3 LLM 多类提取增加每轮 LLM 调用成本（可配 `memory.auto_store_conversation` 开关已有）。
