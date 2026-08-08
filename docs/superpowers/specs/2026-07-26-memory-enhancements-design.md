# 记忆系统增强（冲突检测/recency/provenance/consolidation/自主工具）设计文档

创建时间：2026-07-26
状态：设计草案，待用户审查
关联：`memory/`（MemoryManager 三层记忆 + hybrid 混合搜索）、`services/trigger/`（memory_decay / memory_preference_summary 两个现有定时触发器）、`utils/llm/llm_caller.py`（LLMCaller）、`tools/`（LangChain 工具 registry）

## 一、背景与目标

### 现状
- `MemoryManager.remember()` 直接按 importance 分层存储，**无冲突检测**：先存"喜欢意大利菜"再存"喜欢墨西哥菜"会矛盾共存（真 bug）。
- `recall()` 最终排序用 `metadata.get('hybrid_score', m.get_combined_score())`——**一旦有 hybrid_score，recency 完全被忽略**，旧记忆与新记忆同权。
- `MemoryBlock` 无 provenance 字段，记忆无法溯源到产生它的会话/消息。
- 记忆只增不减，相似碎片长期堆积，无定期合并机制。
- Agent 不能自主调用记忆，只能靠系统自动注入；无法在推理过程中按需检索/写入。

已有基础设施（决定本设计可行性）：
- LLM 真实路径 `utils/llm/llm_caller.py` → `LLMCaller.call_with_prompt(system, user, parse_json=True)` → `LLMCallResult(success, content, parsed)`；`get_default_llm()` 返回 langchain llm。
- `services/trigger/` 已有 `MemoryDecayTrigger`（每日衰减+清理）、`MemoryPreferenceSummaryTrigger`（LLM 定时总结偏好），均为独立轻量 cron，共享 `CronTrigger.get_scheduler()` 的 APScheduler 单例。
- `tools/` 下 LangChain `@tool`/`BaseTool`，`ToolRegistry.discover_tools()` 自动发现 `tools/__init__.__all__`。
- `MemoryBlock.get_recency_score(half_life_hours)` / `get_combined_score()` 已实现。

### 目标
完成 5 项记忆增强：
1. **冲突检测/合并**（Mem0 式 LLM 判 ADD/UPDATE/MERGE/NONE）——消除矛盾共存。
2. **recall recency 加权**——排序引入时间衰减因子。
3. **记忆 provenance**——remember 写入 `source_session_id`/`source_message_id` 元数据。
4. **memory consolidation**——定时合并相似记忆。
5. **LLM 自主记忆工具**（Letta 式）——给 agent `memory_search`/`memory_insert`/`memory_update` 工具。

### 非目标（YAGNI）
- 不做知识图谱/Graphiti/Zep（项 6，本期不做）。
- 不做 LoComo benchmark 评测（项 7，本期不做）。
- 不做记忆前端页面（用户明确"后面再讨论开发方案"）。
- 不给 agent 暴露 `memory_delete`（与衰减清理职责重叠，agent 触发删除风险高）。
- 不改 SQLite 表结构（provenance 走 metadata JSON 列，向后兼容）。
- consolidation 默认关闭（破坏性操作，保守 opt-in）。

## 二、关键设计决策（已与用户确认）

| 决策 | 选择 | 理由 |
|---|---|---|
| Feature 1 触发模型 | **全类型 + 相似门控** | 所有 MemoryType 都做冲突检测；先按内容召回相似候选，**仅命中候选才调 LLM**，无候选直接 ADD（成本由门控封顶）；LLM 不可用降级 ADD（兼容现状） |
| Feature 1 生效层 | **long_term-bound 记忆**（importance≥0.8） | 持久层才有"矛盾共存"持久 bug；immediate/short_term 短暂，自然过期 |
| Feature 5 工具面 | **search + insert + update** | 不含 delete；update 用于 agent 主动修正；insert 自动触发 Feature 1 |
| Feature 4 合并维度 | **按 user 维度** | 不跨用户合并（避免 A 的偏好并入 B） |
| Feature 3 存储 | **metadata** | 无 schema 变更，向后兼容 |
| consolidation 默认 | **enabled=false** | 破坏性，保守 opt-in（同 preference_summary） |
| conflict_resolution 默认 | **enabled=true** | 安全降级为 ADD，且是核心价值 |

## 三、Feature 1 — 冲突检测/合并（ConflictResolver）

### 数据流
```
remember(content, ...)
  ├─ create_memory_block(...)
  ├─ 判定目标层 = importance≥0.8 ? long_term : (≥0.5 ? short_term : immediate)
  ├─ 若 conflict_resolution.enabled 且 目标层==long_term：
  │     ├─ candidates = recall(content, limit=max_candidates, user_id, tiers=[long_term])
  │     │     并按 similarity/hybrid_score ≥ similarity_threshold 过滤
  │     ├─ if 无候选 → 走原 ADD 路径
  │     └─ else → ConflictResolver.resolve(new_block, candidates)
  │           └─ LLMCaller.call_with_prompt(SYSTEM_PROMPT, USER_PROMPT, parse_json=True)
  │                 → {action, target_id?, merged_content?, reason}
  │                 → LLM 不可用/解析失败 → {action:"ADD"}（降级）
  │     ├─ ADD    → long_term.add(new_block)（原路径）
  │     ├─ UPDATE → long_term.update(target)：target.content=new.content，
  │     │            importance=max(两者)+0.1(cap 1.0)，touch()，重嵌
  │     ├─ MERGE  → long_term.update(target)：target.content=merged_content，
  │     │            importance=max(两者)+0.1，touch()，重嵌；new_block 不存
  │     └─ NONE   → 跳过（重复），new_block 不存
  └─ else → 原分层存储路径
```

### ConflictResolver 接口
```python
# memory/conflict_resolver.py
class ConflictDecision(TypedDict):
    action: Literal["ADD", "UPDATE", "MERGE", "NONE"]
    target_id: Optional[str]       # UPDATE/MERGE 时指向候选
    merged_content: Optional[str]  # MERGE 时 LLM 产出
    reason: Optional[str]

class ConflictResolver:
    def __init__(self, llm_caller=None, similarity_threshold=0.6, max_candidates=5):
        # llm_caller 可注入（测试可替换）；默认用 LLMCaller.call_with_prompt
        ...
    async def resolve(self, new: MemoryBlock, candidates: List[MemoryBlock]) -> ConflictDecision: ...
    async def consolidate_pair(self, a: MemoryBlock, b: MemoryBlock) -> Optional[str]:
        """Feature 4 复用：对两条已有记忆产出合并后 content，无法合并返回 None"""
```

### LLM Prompt（JSON 输出）
- SYSTEM：你是记忆冲突判定器。给定新记忆与候选列表，对**每个候选**判定关系并输出 JSON。
- USER：新记忆 + 候选列表（id+content+type）。
- 输出：`{"action":"ADD|UPDATE|MERGE|NONE","target_id":"...","merged_content":"...","reason":"..."}`
  - ADD：新事实，与候选无关。
  - UPDATE：新记忆取代/纠正候选（如偏好变更）。
  - MERGE：互补，合并为一条更完整记忆，给出 merged_content。
  - NONE：重复，丢弃新记忆。
- 解析失败 → `ADD`。

### LongTermMemory.update(memory)
```python
async def update(self, memory: MemoryBlock) -> bool:
    result = await self._storage.save(memory)  # INSERT OR REPLACE by id
    if result and self._vector_backend:
        vs = await self._ensure_vector_storage()
        if vs:
            try:
                await vs.delete(memory.id)   # 先删（chromadb 无 upsert）
                await vs.save(memory)        # 重新嵌入+写入
            except Exception as e:
                logger.warning(...)
    return result
```

### 配置
```json
"memory": {
  "conflict_resolution": {
    "enabled": true,
    "similarity_threshold": 0.6,
    "max_candidates": 5,
    "_comment": "写入 long_term 前做 LLM 冲突检测；仅命中相似候选才调 LLM；LLM 不可用降级 ADD"
  }
}
```

### 复用改造
- `services/trigger/memory_preference_summary_trigger.py` 现有朴素去重 `if any(content in ec or ec in content for ec in existing_prefs)` 改为：插入前调 `ConflictResolver.resolve()` 判定（Feature 1 已就绪后）。保留 fallback：resolver 不可用时回退原包含匹配。

## 四、Feature 2 — recall recency 加权

### 现状 bug
`MemoryManager.recall()`：
```python
all_results.sort(key=lambda m: m.metadata.get('hybrid_score', m.get_combined_score()), reverse=True)
```
当 `hybrid_score` 存在时，完全忽略 recency。`LongTermMemory.search()` 排序用 `metadata.get('similarity', m.importance)`，同样无 recency。

### 方案：relevance × (1-rw) + recency × rw
- `MemoryBlock` 加方法 `get_final_recall_score(recency_weight)`：
  ```python
  def get_final_recall_score(self, recency_weight: float = 0.15) -> float:
      relevance = self.metadata.get('hybrid_score',
                  self.metadata.get('similarity',
                  self.get_combined_score()))
      recency = self.get_recency_score(half_life_hours=168.0)  # 一周半衰期
      return float(relevance) * (1 - recency_weight) + recency * recency_weight
  ```
- `MemoryManager.recall()` 最终排序改为：
  ```python
  rw = get_config('memory.recency_weight', 0.15)
  all_results.sort(key=lambda m: m.get_final_recall_score(rw), reverse=True)
  ```
- `LongTermMemory.search()` 排序同步用 `get_final_recall_score()`（保证层内候选也含 recency，与最终排序一致）。

### 配置
```json
"memory": { "recency_weight": 0.15, "_comment": "recall 排序 recency 权重(0-1)，0=纯相关性，1=纯时间衰减" }
```

## 五、Feature 3 — 记忆 provenance

### 改动
- `create_memory_block()` 与 `MemoryManager.remember()` 增加 `source_session_id: Optional[str]`、`source_message_id: Optional[str]` 参数。
- 非空时写入 `metadata["source_session_id"]` / `metadata["source_message_id"]`。
- 无 schema 变更（metadata 是 JSON 列）。默认 None，向后兼容。
- `MemoryBlock.from_dict()` / `to_dict()` 已支持 metadata 透传，无需改。

### 调用方
- 现有自动存储路径（auto_store_conversation / preference_summary）按需传入可得的 source_message_id（如 chat message 的 id）。本期交付 API 能力 + 在自动存储路径接线；其他调用点保持 None。

## 六、Feature 4 — memory consolidation trigger

### 模式（复用 MemoryDecayTrigger 同构）
```python
# services/trigger/memory_consolidation_trigger.py
class MemoryConsolidationTrigger:
    def __init__(self):
        cfg = get_config("memory.consolidation", {}) or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.cron = cfg.get("cron", "0 5 * * *")  # 05:00，避开 decay(03:00)/pref(04:00)
        self.similarity_threshold = float(cfg.get("similarity_threshold", 0.85))
        self.max_pairs_per_user = int(cfg.get("max_pairs_per_user", 10))
    async def handle(self) -> dict: ...
    async def start(self) -> None: ...  # 同 decay：APSCronTrigger + sched.add_job(id="memory_consolidation")
```

### handle() 流程
```
for user_id in long_term distinct user_ids:
    mems = long_term.get_all() 过滤 user_id
    embeddings = [m.embedding or embed(m.content) for m in mems]
    pairs = [(i,j) for i<j if cosine(emb[i],emb[j]) >= similarity_threshold]  # 排序后取 top max_pairs_per_user
    for (a, b) in pairs:
        merged = await ConflictResolver.consolidate_pair(a, b)
        if merged:
            a.content = merged; a.importance=max(a,b)+0.05; a.touch()
            await long_term.update(a)      # 重嵌
            await mm.forget(b.id)         # 删被合并方
            merged_count += 1
return {"users": n, "pairs": p, "merged": merged_count}
```

### 配置
```json
"memory": {
  "consolidation": {
    "enabled": false,
    "cron": "0 5 * * *",
    "similarity_threshold": 0.85,
    "max_pairs_per_user": 10,
    "_comment": "每日 05:00 按 user 维度合并高相似长期记忆（embedding 相似度≥阈值）；破坏性，默认关闭"
  }
}
```

### 启动注册
- 在已注册 `MemoryDecayTrigger.start()` / `MemoryPreferenceSummaryTrigger.start()` 的同一启动处追加 `MemoryConsolidationTrigger().start()`（实现时定位该处）。

## 七、Feature 5 — LLM 自主记忆工具（Letta 式）

### 工具（LangChain @tool）
```python
# tools/memory_tool.py
@tool
async def memory_search(query: str, limit: int = 5) -> str:
    """搜索当前用户记忆，返回相关记忆列表（content + type + importance）"""
    ctx = get_memory_context()  # (user_id, session_id)
    mm = get_memory_manager()
    results = await mm.recall(query, limit=limit, user_id=ctx.user_id, session_id=ctx.session_id)
    return json.dumps([{"id":m.id,"content":m.content,"type":...,} for m in results], ensure_ascii=False)

@tool
async def memory_insert(content: str, type: str = "note", importance: float = 0.8) -> str:
    """写入一条持久记忆（importance 默认 0.8 落 long_term，自动触发冲突检测，必要时合并/更新）"""
    ctx = get_memory_context()
    mm = get_memory_manager()
    m = await mm.remember(content, type=type, importance=importance,
                          user_id=ctx.user_id, session_id=ctx.session_id,
                          source_session_id=ctx.session_id)
    return f"stored memory_id={m.id}"

@tool
async def memory_update(memory_id: str, content: str) -> str:
    """更新指定记忆内容（重嵌）"""
    ctx = get_memory_context()
    mm = get_memory_manager()
    m = await mm.long_term.get(memory_id)
    if not m: return "not found"
    if m.user_id != ctx.user_id: return "forbidden"  # 隔离：仅改自己的
    m.content = content; m.touch()
    await mm.long_term.update(m)
    return "updated"
```

### 运行时上下文（ContextVar）
```python
# utils/common/memory_context.py
@dataclass
class MemoryContext:
    user_id: Optional[str]
    session_id: Optional[str]
_var: ContextVar[MemoryContext] = ContextVar("memory_context", default=MemoryContext(None,None))
def set_memory_context(user_id, session_id): _var.set(MemoryContext(user_id, session_id))
def get_memory_context() -> MemoryContext: return _var.get()
```
- 在 chat 请求入口（`api/chat/` 或 executor 绑定会话处）`set_memory_context(user_id, session_id)`（实现时定位入口接线；该 context 在 async 任务内有效）。
- 工具内 `get_memory_context()` 取当前 user/session；LLM 只传 query/content/memory_id。

### 注册与 opt-in
- `tools/__init__.__all__` 加入三个工具名。
- **opt-in**：agent 配置（`tb_agent.tools` 或 `external_tools` 列表）显式挂载才生效，不强制全量 agent。系统提示词建议附带"可调用 memory_search/insert/update 管理长期记忆"的引导（可由 prompt_template 管理）。

## 八、错误处理与降级
- ConflictResolver：LLM 调用失败 / JSON 解析失败 / 超时 → 返回 `ADD`（行为等价现状）。记 warning。
- memory_search：recall 异常 → 返回空列表 JSON。
- memory_insert：remember 异常 → 返回 error 字符串，不抛（工具不阻断 agent 流程）。
- memory_update：memory_id 不存在 → "not found"；跨 user → "forbidden"。
- consolidation handle：单对失败 continue，不影响其他对；trigger 失败不崩主进程。
- 所有 LLM 依赖特性在 LLM 未配置时安全降级（conflict→ADD，consolidation 跳过）。

## 九、测试策略（TDD）

沿用现有 `test/test_memory_*.py` 风格；LLM 可注入/monkeypatch，不依赖真实 LLM。

| 测试文件 | 验证 |
|---|---|
| `test/test_memory_conflict.py` | 4 种 action 判定 + LLM 失败降级 ADD + UPDATE/MERGE 写回 + recall 候选过滤 |
| `test/test_memory_recency.py` | 含 hybrid_score 时 recency 仍生效；recency_weight=0 退化为纯相关；新旧排序差异 |
| `test/test_memory_provenance.py` | remember 传 source_session_id/message_id 写入 metadata；不传时无此键 |
| `test/test_memory_consolidation.py` | trigger handle 合并高相似对 + 删被合并方 + max_pairs 封顶 + 默认 disabled 不跑 |
| `test/test_memory_tools.py` | 三工具 happy path + context 隔离（跨 user forbidden）+ recall/remember 接线 + 注入式 mm |

TDD 顺序：每特性先写 RED 契约测试，再实现 GREEN。冲突检测优先（Feature 4/5 依赖 ConflictResolver）。

## 十、实施顺序与依赖
1. **Feature 3（provenance）**——零依赖，改 API 签名，最快。
2. **Feature 1（ConflictResolver + remember 改造 + LongTermMemory.update）**——Feature 4/5 依赖。
3. **Feature 2（recency 加权）**——独立，1 处核心改动。
4. **Feature 4（consolidation trigger）**——依赖 ConflictResolver.consolidate_pair。
5. **Feature 5（memory 工具 + context）**——依赖 remember（含 Feature 1）+ LongTermMemory.update。

## 十一、涉及文件清单
**新增**：
- `memory/conflict_resolver.py`
- `services/trigger/memory_consolidation_trigger.py`
- `tools/memory_tool.py`
- `utils/common/memory_context.py`
- `test/test_memory_conflict.py`、`test/test_memory_recency.py`、`test/test_memory_provenance.py`、`test/test_memory_consolidation.py`、`test/test_memory_tools.py`

**修改**：
- `memory/memory_manager.py`（remember 冲突检测接线、recall recency 排序、provenance 参数、LongTermMemory.update）
- `memory/blocks.py`（create_memory_block provenance 参数、get_final_recall_score）
- `memory/storage.py`（VectorStorage upsert 辅助，若需）
- `services/trigger/memory_preference_summary_trigger.py`（去重改调 ConflictResolver）
- `tools/__init__.py`（注册三工具）
- `config/agent_config.json` + `config/agent_config.json.example`（新配置项）
- trigger 启动注册处（追加 MemoryConsolidationTrigger.start()）
- chat 请求入口（set_memory_context 接线）

## 十二、非功能性约束
- 后端规范：分层清晰（resolver 属 memory 层、trigger 属 services/trigger、tools 属 tools 层、context 属 utils/common）；repo 只管数据；路由薄。
- Surgical Changes：只动必要行，匹配既有风格，不顺手重构。
- 日志：`from loguru import logger`，关键操作 info，异常 warning/error 带 exc_info。
- 代码标识符英文，注释/日志可中文。
