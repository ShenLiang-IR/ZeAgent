# multi_agent_service token 流式补齐 + thinking 清理收尾（项5/6 方案 B）

> 日期：2026-07-16
> 方案：B（补齐 token 级流式，与 plan_executor 对齐 + 项5 收尾）
> 前置分析：`docs/executoranalyse.md` 缺点6/8
> 触及模块：`services/multi_agent_service.py`、`executor/langgraph/event_parser.py`

---

## 1. 背景

### 1.1 现状（代码实证）

`multi_agent_service.dispatch_stream` 与 `plan_executor._execute_with_workflow` 是**两套不同的流式实现**：

| | plan_executor（chat 主路径） | multi_agent_service（多 agent 调度） |
|---|---|---|
| `StateGraphBuilder.build` 的 stream_mode | `"stream"`（line 434） | **`"final"`（默认，line 200 未传）** |
| node 函数 | `execute_task_stream` + `get_stream_writer` 转发 token 增量 | `execute_task`（非流式） |
| `astream` stream_mode | `["updates","custom"]` 双通道（line 450） | **默认单通道（line 228）** |
| token 级增量 | ✅ custom 通道实时 `CONTENT_CHUNK` | ❌ 无——把 task 完成后**最终 result** 当一个 `content_chunk` 整体发出（line 239） |

### 1.2 关键前提（已验证）

- `StateGraphBuilder.build(stream_mode="final" 默认)`：node 用 `execute_task`（非流式），custom 通道无数据
- `StateGraphBuilder.build(stream_mode="stream")`：node 用 `execute_task_stream` + `get_stream_writer` 转发 adapter 事件到 custom 通道（`stategraph_builder.py:119`）
- 前端 `AgentList.vue:589`：`if (data.content) ch.content += data.content`（**追加模式**），从"发 1 个完整 content_chunk"变"发 N 个增量"前端零改动

### 1.3 项5 thinking 清理现状

`event_parser._clean_content`（line 156）与 `_clean_and_extract_reasoning`（line 166）都调 `extract_reasoning_from_content`，前者返回 cleaned，后者返回 (cleaned, reasoning)。前者是后者子集——可合并。

`StreamingThinkingCleaner` 死代码已删（`event_parser.py:14-15` 注释印证），thinking 清理已统一到 `message_extractor`。

---

## 2. 目标

- **项6**：`multi_agent_service` 补齐 `stream_mode="stream"` + `astream(["updates","custom"])`，custom 通道转发 adapter `CONTENT_CHUNK` → `build_sse_event("content_chunk")`，实现真正 token 级流式
- **项5 收尾**：`event_parser._clean_content` 改为调 `_clean_and_extract_reasoning(content)[0]`，消除子集重复
- **前端零改动**（已验证 `+=` 兼容）
- **降级安全**：回退到 `stream_mode="final"` + 单通道即恢复旧行为

## 3. 非目标

- 不改 `plan_executor`（它已正确实现双通道）
- 不改 `StateGraphBuilder` / `adapter`（build 已支持 stream_mode 参数）
- 不改前端（`+=` 兼容）
- 不改 `ContextEditingMiddleware`（与项3 不同的层面）

---

## 4. ⚠️ 验证限制（必须明示）

`test_multi_agent_dispatch.py` / `test_dag_dispatch.py` 依赖 MySQL（`DispatchRecord` 持久化）。当前环境 MySQL 未启动，回归时这 6 个测试因 `Can't connect to MySQL` 失败。

**后果**：改完 `multi_agent_service` 后，无法跑这些回归测试验证没破坏现有功能。

**缓解**：
1. 写**不依赖 MySQL** 的单元测试：mock adapter 产增量 `CONTENT_CHUNK`，验证 `dispatch_stream` yield 多个 `content_chunk`（去重逻辑用纯单元测试覆盖）
2. `test_dispatch_detail.py`（不依赖 MySQL，刚才 passed）作回归
3. 标注：完整回归需启动 MySQL 后补跑 `test_multi_agent_dispatch` / `test_dag_dispatch`

---

## 5. 组件设计

### 5.1 multi_agent_service.build() 加 stream_mode

**文件**：`services/multi_agent_service.py:200-204`

现状：
```python
graph = builder.build(
    plan=plan,
    semaphore=semaphore,
    max_concurrency=max_concurrency,
)
```

改后：
```python
graph = builder.build(
    plan=plan,
    semaphore=semaphore,
    max_concurrency=max_concurrency,
    stream_mode="stream",   # ← 新增：node 用 execute_task_stream + get_stream_writer
)
```

### 5.2 astream 加双通道 + custom 转发

**文件**：`services/multi_agent_service.py:226-246`

现状（单通道 + 把 result 当 content_chunk）：
```python
collected_results = {}
try:
    async for event in graph.astream(initial_state, config=config):
        for node_name, node_output in event.items():
            if isinstance(node_output, dict):
                results = node_output.get("results", {})
                errors = node_output.get("errors", {})
                for task_id, result in results.items():
                    if task_id not in collected_results:
                        yield build_sse_event("task_started", ...)
                        yield build_sse_event("content_chunk", task_id=task_id, content=result, ...)
                        ...task_completed/failed...
                        collected_results[task_id] = result
```

改后（双通道，custom 实时转发 + updates 兜底）：
```python
from utils.sse import build_sse_event
collected_results = {}
seen_task_started = set()   # custom 已发 task_started 时 updates 不重发
try:
    async for event in graph.astream(
        initial_state, config=config,
        stream_mode=["updates", "custom"],   # ← 双通道
    ):
        mode, data = event
        if mode == "custom":
            task_id = (data or {}).get("task_id")
            adapter_event = (data or {}).get("event")
            if adapter_event is None:
                continue
            ev_type = getattr(adapter_event, "type", None)
            ev_data = getattr(adapter_event, "data", None)
            ev_type_str = ev_type.value if hasattr(ev_type, "value") else str(ev_type)
            if ev_type_str == "content_chunk" and ev_data:
                yield build_sse_event("content_chunk", task_id=task_id, content=ev_data, done=False)
            elif ev_type_str == "task_started":
                seen_task_started.add(task_id)
                yield build_sse_event("task_started", task_id=task_id, done=False)
            elif ev_type_str == "task_completed":
                collected_results[task_id] = ev_data.get("result", "") if isinstance(ev_data, dict) else ""
                yield build_sse_event("task_completed", task_id=task_id, done=True)
            elif ev_type_str == "task_failed":
                yield build_sse_event("task_failed", task_id=task_id, done=True)
        elif mode == "updates":
            # updates 兜底：custom 未发的 task（如非流式降级场景）补发终结
            for _node, output in (data or {}).items():
                if isinstance(output, dict):
                    results = output.get("results", {})
                    errors = output.get("errors", {})
                    for task_id, result in results.items():
                        if task_id not in collected_results:
                            if task_id not in seen_task_started:
                                yield build_sse_event("task_started", task_id=task_id, done=False)
                            yield build_sse_event("content_chunk", task_id=task_id, content=result, done=False)
                            if task_id in errors:
                                yield build_sse_event("task_failed", task_id=task_id, done=True)
                            else:
                                yield build_sse_event("task_completed", task_id=task_id, done=True)
                            collected_results[task_id] = result
```

### 5.3 event_parser._clean_content 合并

**文件**：`executor/langgraph/event_parser.py:156-164`

现状：
```python
def _clean_content(self, content: str) -> str:
    if not content:
        return content
    try:
        _, cleaned = extract_reasoning_from_content(content)
        return cleaned
    except Exception as e:
        logger.warning(f"[EventParser] : {e}")
        return content
```

改后（委托 _clean_and_extract_reasoning）：
```python
def _clean_content(self, content: str) -> str:
    return self._clean_and_extract_reasoning(content)[0]
```

`_clean_and_extract_reasoning`（line 166）已含空值/异常处理，`_clean_content` 委托即可。

---

## 6. 测试策略

### 6.1 单元测试 `test/test_multi_agent_stream.py`（新建，不依赖 MySQL）

mock adapter 产增量事件，验证 `dispatch_stream` 的 custom 通道转发：

| 测试 | 验证 |
|---|---|
| content_chunk 转发 | mock adapter yield 3 个 CONTENT_CHUNK → dispatch_stream yield 3 个 content_chunk SSE |
| task_started/completed | mock adapter yield task_started+content+task_completed → SSE 三联 |
| updates 兜底 | mock 不产 custom（模拟降级）+ updates 有 result → 补发完整事件 |
| 去重 | custom 已发 task_started → updates 不重发 |

### 6.2 回归

- `test_dispatch_detail.py`（不依赖 MySQL）：PASS
- `test_multi_agent_dispatch.py` / `test_dag_dispatch.py`：**需启动 MySQL 后补跑**（当前环境失败）

---

## 7. 风险与回退

| 风险 | 等级 | 缓解 |
|---|---|---|
| stream_mode="stream" 让 node 调 execute_task_stream（流式 LLM），开销略增 | 低 | 功能更强（真正流式），开销可接受 |
| custom 通道事件类型遗漏 | 中 | 参照 plan_executor:446-527 全覆盖 |
| 回归无法跑（MySQL 未启动） | **中** | 单元测试覆盖转发逻辑 + 标注需补跑 |
| 前端兼容 | 低 | `+=` 已验证 |

**回退**：
1. `build()` 去掉 `stream_mode="stream"`（恢复 "final"）
2. `astream` 去掉 `stream_mode=["updates","custom"]`（恢复默认单通道）
3. 即完全恢复旧行为

---

## 8. 文件变更清单

| 文件 | 变更类型 |
|---|---|
| `services/multi_agent_service.py` | 改（build 加 stream_mode + astream 双通道 + custom 转发） |
| `executor/langgraph/event_parser.py` | 改（`_clean_content` 委托） |
| `test/test_multi_agent_stream.py` | 新建（不依赖 MySQL 的单元测试） |
