# multi_agent_service token 流式补齐 + thinking 清理收尾 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** multi_agent_service 补齐 stream_mode="stream" + astream(["updates","custom"]) 实现真正 token 流式；event_parser._clean_content 委托消除子集重复。

**Architecture:** 项6 改 multi_agent_service.build() 传 stream_mode="stream"（node 用 execute_task_stream + get_stream_writer）+ astream 双通道消费 custom 转发 CONTENT_CHUNK；项5 _clean_content 委托 _clean_and_extract_reasoning[0]。前端零改动（+= 兼容）。

**Tech Stack:** Python 3.13 + langgraph + pytest(asyncio_mode=auto)

**Spec:** `docs/superpowers/specs/2026-07-16-multi-agent-stream-and-thinking-cleanup-design.md`（方案 B）

**Environment:** conda env `D:\ProgramData\miniconda3\envs\install_deb_refactor`，git repo

**Test command:** `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest <test_file> -v -p no:warnings`

## Global Constraints

- `StateGraphBuilder.build` 已支持 `stream_mode` 参数（不改 builder）
- `plan_executor` 不改（已正确实现双通道）
- 前端不改（`AgentList.vue:589` `+=` 已验证兼容）
- **验证限制**：`test_multi_agent_dispatch.py` / `test_dag_dispatch.py` 依赖 MySQL（当前未启动，回归失败），单元测试用 mock adapter 不依赖 MySQL
- 回退：build 去掉 stream_mode + astream 去掉双通道 = 恢复旧行为

---

## File Structure

| File | Type | Responsibility |
|------|------|----------------|
| `executor/langgraph/event_parser.py` | Modify | `_clean_content` 委托 `_clean_and_extract_reasoning[0]` |
| `services/multi_agent_service.py` | Modify | build 加 stream_mode + astream 双通道 + custom 转发 |
| `test/test_multi_agent_stream.py` | Create | mock adapter 单元测试（不依赖 MySQL） |

---

### Task 1: 项5 event_parser._clean_content 委托（RED→GREEN）

**Files:**
- Modify: `executor/langgraph/event_parser.py:156-164`
- Test: `test/test_event_parser_cleanup.py`（新建）

- [ ] **Step 1: Write failing test**

```python
# test/test_event_parser_cleanup.py
"""event_parser _clean_content 委托 _clean_and_extract_reasoning 测试。"""
from executor.langgraph.event_parser import LangGraphEventParser


def _make_parser():
    return LangGraphEventParser.__new__(LangGraphEventParser)


def test_clean_content_strips_reasoning():
    """_clean_content 剥离 thinking 标签，返回 cleaned（无 reasoning）。"""
    pe = _make_parser()
    content = "<think>hidden reasoning</think>visible answer"
    cleaned = pe._clean_content(content)
    assert "hidden" not in cleaned
    assert "visible answer" in cleaned


def test_clean_content_empty():
    """空串 → 空串。"""
    pe = _make_parser()
    assert pe._clean_content("") == ""


def test_clean_content_no_think_tag():
    """无 think 标签 → 原样。"""
    pe = _make_parser()
    assert pe._clean_content("plain text") == "plain text"


def test_clean_content_consistent_with_extract():
    """_clean_content 与 _clean_and_extract_reasoning[0] 一致。"""
    pe = _make_parser()
    content = "<think>r</think>c"
    assert pe._clean_content(content) == pe._clean_and_extract_reasoning(content)[0]
```

- [ ] **Step 2: Run to verify fails (or passes if logic already equivalent)**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_event_parser_cleanup.py -v -p no:warnings --tb=line`
Expected: PASS（现状 _clean_content 已调 extract_reasoning_from_content，逻辑等价；测试锁定行为）

- [ ] **Step 3: Refactor _clean_content to delegate**

`executor/langgraph/event_parser.py:156-164` 现状：

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

改为委托：

```python
    def _clean_content(self, content: str) -> str:
        return self._clean_and_extract_reasoning(content)[0]
```

- [ ] **Step 4: Run test to verify passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_event_parser_cleanup.py -v -p no:warnings`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add executor/langgraph/event_parser.py test/test_event_parser_cleanup.py
git commit -m "refactor(event_parser): _clean_content delegates to _clean_and_extract_reasoning (dedupe subset)"
```

---

### Task 2: 项6 build() 加 stream_mode="stream"

**Files:**
- Modify: `services/multi_agent_service.py:200-204`

- [ ] **Step 1: Add stream_mode to build() call**

现状（line 200-204）：

```python
        graph = builder.build(
            plan=plan,
            semaphore=semaphore,
            max_concurrency=max_concurrency,
        )
```

改为：

```python
        graph = builder.build(
            plan=plan,
            semaphore=semaphore,
            max_concurrency=max_concurrency,
            stream_mode="stream",
        )
```

- [ ] **Step 2: Verify import still works**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -c "import services.multi_agent_service; print('import OK')"`
Expected: `import OK`

- [ ] **Step 3: Commit**

```bash
git add services/multi_agent_service.py
git commit -m "feat(multi_agent_service): build() with stream_mode=stream (enable custom channel token streaming)"
```

---

### Task 3: 项6 astream 双通道 + custom 转发 + 单元测试

**Files:**
- Modify: `services/multi_agent_service.py:226-246`（astream 消费循环）
- Test: `test/test_multi_agent_stream.py`（新建，mock adapter）

**Interfaces:**
- Consumes: stream_mode="stream" from Task 2（custom 通道有数据）
- Produces: dispatch_stream yield 增量 content_chunk SSE

- [ ] **Step 1: Write failing test (mock adapter, no MySQL)**

```python
# test/test_multi_agent_stream.py
"""multi_agent_service token 流式补齐测试（mock adapter，不依赖 MySQL）。

验证 custom 通道转发 CONTENT_CHUNK → content_chunk SSE。
"""
import asyncio
import pytest
from types import SimpleNamespace
from enum import Enum


class _EvType(Enum):
    TASK_STARTED = "task_started"
    CONTENT_CHUNK = "content_chunk"
    TASK_COMPLETED = "task_completed"


def _ev(t, data=None):
    return SimpleNamespace(type=t, data=data, metadata={})


async def _mock_astream(stream_events):
    """mock graph.astream：yield (mode, data) 序列。"""
    for mode, data in stream_events:
        yield (mode, data)


class _MockGraph:
    def __init__(self, stream_events):
        self._events = stream_events

    async def astream(self, initial_state, config=None, stream_mode=None):
        async for ev in _mock_astream(self._events):
            yield ev


def _build_service_with_mock_graph(monkeypatch, stream_events):
    """构造 MultiAgentService，mock graph 为 _MockGraph。"""
    import services.multi_agent_service as mod

    # mock builder.build 返回 _MockGraph
    class _MockBuilder:
        def build(self, **kwargs):
            return _MockGraph(stream_events)

    # mock 掉 StateGraphBuilder / adapter / DB / config 依赖
    monkeypatch.setattr(mod, "StateGraphBuilder", lambda **kw: _MockBuilder())
    monkeypatch.setattr(mod, "create_langgraph_adapter", lambda **kw: SimpleNamespace())
    monkeypatch.setattr(mod, "get_config_session", _mock_session)
    monkeypatch.setattr(mod, "MysqlSaverFactory", SimpleNamespace(get_saver=_async_none))
    monkeypatch.setattr(mod, "MemorySaver", lambda: None)
    monkeypatch.setattr(mod, "attach_callbacks", lambda cfg, **kw: cfg)
    monkeypatch.setattr(mod, "get_config", lambda k, d=None: d)

    svc = mod.MultiAgentService.__new__(mod.MultiAgentService)
    return svc


async def _async_none(*a, **kw):
    return None


class _MockSession:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def add(self, *a): pass
    def flush(self): pass
    def query(self, *a):
        class _Q:
            def filter(self, *a): return self
            def update(self, *a, **k): return None
        return _Q()


def _mock_session():
    return _MockSession()


def _parse_sse_events(agen):
    """收集 dispatch_stream yield 的 SSE dict 列表。"""
    out = []
    import json


def test_custom_channel_content_chunk_forwarded(monkeypatch):
    """custom 通道 CONTENT_CHUNK → content_chunk SSE。"""
    import json
    events = [
        ("custom", {"task_id": "t1", "event": _ev(_EvType.TASK_STARTED)}),
        ("custom", {"task_id": "t1", "event": _ev(_EvType.CONTENT_CHUNK, "hello")}),
        ("custom", {"task_id": "t1", "event": _ev(_EvType.CONTENT_CHUNK, " world")}),
        ("custom", {"task_id": "t1", "event": _ev(_EvType.TASK_COMPLETED, {"result": "hello world"})}),
    ]
    svc = _build_service_with_mock_graph(monkeypatch, events)

    collected = []
    # 直接调 dispatch_stream 的 graph 消费部分（绕过 DB）
    # 注：dispatch_stream 含 DB 写，需 mock session（已 mock）
    agen = svc.dispatch_stream(agent_ids=["1"], message="hi", mode="parallel", dispatch_id="d1")
    import asyncio as _aio
    async def _collect():
        async for ev in agen:
            collected.append(ev)
    _aio.get_event_loop().run_until_complete(_collect())

    content_chunks = [e for e in collected if e.get("type") == "content_chunk"]
    assert len(content_chunks) == 2, f"应有 2 个 content_chunk，实际 {len(content_chunks)}"
    assert content_chunks[0]["content"] == "hello"
    assert content_chunks[1]["content"] == " world"
```

- [ ] **Step 2: Run to verify it fails**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_multi_agent_stream.py -v -p no:warnings --tb=line`
Expected: FAIL（现状单通道，custom 事件不被消费）

- [ ] **Step 3: Modify astream to dual-channel + custom forwarding**

`services/multi_agent_service.py:226-246` 现状（单通道）：

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
                                from utils.sse import build_sse_event
                                yield build_sse_event("task_started", task_id=task_id, done=False)
                                yield build_sse_event("content_chunk", task_id=task_id, content=result, done=False)
                                if task_id in errors:
                                    yield build_sse_event("task_failed", task_id=task_id, done=True)
                                else:
                                    yield build_sse_event("task_completed", task_id=task_id, done=True)
                                collected_results[task_id] = result
```

改为（双通道 + custom 转发 + updates 兜底）：

```python
        from utils.sse import build_sse_event
        collected_results = {}
        seen_task_started = set()
        try:
            async for event in graph.astream(
                initial_state, config=config,
                stream_mode=["updates", "custom"],
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
                        if isinstance(ev_data, dict):
                            collected_results[task_id] = ev_data.get("result", "")
                        yield build_sse_event("task_completed", task_id=task_id, done=True)
                    elif ev_type_str == "task_failed":
                        yield build_sse_event("task_failed", task_id=task_id, done=True)
                elif mode == "updates":
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

- [ ] **Step 4: Run test to verify passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_multi_agent_stream.py -v -p no:warnings`
Expected: PASS（custom 通道 content_chunk 转发）

- [ ] **Step 5: Commit**

```bash
git add services/multi_agent_service.py test/test_multi_agent_stream.py
git commit -m "feat(multi_agent_service): dual-channel astream forwards custom CONTENT_CHUNK to SSE (real token streaming)"
```

---

### Task 4: 回归（标注 MySQL 限制）

**Files:**
- No changes

- [ ] **Step 1: Run non-MySQL regression**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_multi_agent_stream.py test/test_event_parser_cleanup.py test/test_dispatch_detail.py test/test_context_truncation.py -v -p no:warnings --tb=line`
Expected: 全 PASS（不依赖 MySQL 的测试）

- [ ] **Step 2: Document MySQL-dependent regression (cannot run)**

`test_multi_agent_dispatch.py` / `test_dag_dispatch.py` 依赖 MySQL（当前未启动）。**需启动 MySQL 后补跑验证**：
```
python -m pytest test/test_multi_agent_dispatch.py test/test_dag_dispatch.py -v
```
记录：本次改动改了 multi_agent_service 的 astream 消费循环，这两个测试是核心回归，启动 MySQL 后必须补跑确认。

---

## Self-Review

**1. Spec coverage（spec §5.1/§5.2/§5.3）：**
- ✅ §5.1 build() 加 stream_mode → Task 2
- ✅ §5.2 astream 双通道 + custom 转发 → Task 3
- ✅ §5.3 event_parser._clean_content 委托 → Task 1
- ✅ §6 单元测试（不依赖 MySQL）→ Task 3

**2. Placeholder scan:** 无 TBD/TODO，所有 step 含完整代码 + 命令。

**3. Type consistency:** `build_sse_event(type, task_id=, content=, done=)` 在 Task 3 一致；`stream_mode="stream"` 在 Task 2/3 一致；adapter event 的 type/data/metadata 访问与 plan_executor:459-461 一致。
