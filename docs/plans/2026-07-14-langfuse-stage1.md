# langfuse 集成 阶段 1 实施计划 — handler factory + task_executor 单点注入

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** langfuse handler factory + config 节 + task_executor 单点注入，验证 langfuse SDK 与 langchain 1.x 兼容性，为后续阶段（外层注入/trace_context/Path A/自托管）打基础

**Architecture:** `LangfuseHandlerFactory.create()` 单例读 config 创建 `langfuse.langchain.CallbackHandler`（enabled=false/import 失败/key 缺失返回 None 降级）；`attach_callbacks(config)` 辅助函数注入 callbacks（不改原 dict）；`task_executor` 的 `execute_task`/`execute_task_stream` 调用 `attach_callbacks`

**Tech Stack:** langfuse SDK（langfuse.langchain.CallbackHandler）+ langchain 1.2.15 + langgraph 1.1.8 + Python 3.13

**Spec:** `docs/specs/2026-07-14-langfuse-integration-design.md` §5.1/§5.4 注入点① / §9 阶段 1

**Environment:** conda env `D:\ProgramData\miniconda3\envs\install_deb_refactor`，**非 git repo**（commit 步骤改为运行测试验证），Python 3.13，pytest + pytest-asyncio（asyncio_mode=auto）

**Test command:** `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest <test_file> -v`

## Global Constraints

- langfuse 当前未安装（requirements.txt 无），阶段 1 需先 `pip install langfuse`
- `get_config(key, default)` 是通用点分 key 查询（config_loader.py），新增 `observability.langfuse.*` 自动支持
- 所有 langfuse 异常必须降级（返回 None），**绝不阻断主流程**
- 不改图构建逻辑（StateGraphBuilder / AgentFactory 不动），只 runtime config 注入

---

## File Structure

| File | Type | Responsibility |
|------|------|----------------|
| `utils/observability/__init__.py` | Create | 包出口 |
| `utils/observability/langfuse_handler.py` | Create | LangfuseHandlerFactory（create/reset）+ attach_callbacks |
| `config/agent_config.json` | Modify | 顶层加 observability.langfuse 节（enabled=false 默认） |
| `executor/langgraph/task_executor.py` | Modify | execute_task(L123)/execute_task_stream(L192) 调 attach_callbacks |
| `requirements.txt` | Modify | 加 langfuse |
| `test/test_langfuse_handler_factory.py` | Create | factory + attach_callbacks 单元测试 |

---

### Task 1: 安装 langfuse + factory 骨架（enabled=false 返回 None）

**Files:**
- Modify: `requirements.txt`
- Create: `utils/observability/__init__.py`
- Create: `utils/observability/langfuse_handler.py`
- Create: `test/test_langfuse_handler_factory.py`

**Interfaces:**
- Produces: `LangfuseHandlerFactory.create() -> Optional[Any]`（enabled=false → None）；`LangfuseHandlerFactory.reset()`（测试重置单例）

- [ ] **Step 1: 安装 langfuse**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pip install langfuse`
Expected: Successfully installed langfuse-*

- [ ] **Step 2: 在 requirements.txt 加 langfuse**

在 `requirements.txt` 末尾加一行（或按字母序插入）：
```
langfuse
```

- [ ] **Step 3: 写失败测试**

```python
# test/test_langfuse_handler_factory.py
"""langfuse handler factory 单元测试。"""
import pytest
from unittest.mock import patch


def test_create_returns_none_when_disabled():
    """enabled=false 时 create() 返回 None（降级，不创建 handler）。"""
    from utils.observability.langfuse_handler import LangfuseHandlerFactory
    LangfuseHandlerFactory.reset()
    with patch("utils.observability.langfuse_handler.get_config", side_effect=lambda k, d=None: False if k == "observability.langfuse.enabled" else d):
        result = LangfuseHandlerFactory.create()
    assert result is None, "enabled=false 应返回 None"
```

- [ ] **Step 4: 运行测试验证失败**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langfuse_handler_factory.py::test_create_returns_none_when_disabled -v -p no:warnings`
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.observability'`

- [ ] **Step 5: 写最小实现**

```python
# utils/observability/__init__.py
from .langfuse_handler import LangfuseHandlerFactory, attach_callbacks

__all__ = ["LangfuseHandlerFactory", "attach_callbacks"]
```

```python
# utils/observability/langfuse_handler.py
"""langfuse CallbackHandler 工厂。

读 config 创建 langfuse CallbackHandler；enabled=false/import 失败/key 缺失时返回 None（降级，不阻断主流程）。
单例缓存，避免每次 astream 重建 handler。
"""
from __future__ import annotations
from typing import Any, Optional
from loguru import logger
from utils.config import get_config


class LangfuseHandlerFactory:
    """langfuse CallbackHandler 工厂（单例缓存）。"""

    _handler: Optional[Any] = None
    _initialized: bool = False

    @classmethod
    def create(cls) -> Optional[Any]:
        """返回 langfuse CallbackHandler 实例，或 None（降级）。

        enabled=false / langfuse 未装 / key 缺失 → None。
        单例：首次调用后缓存，后续返回同一实例。
        """
        if cls._initialized:
            return cls._handler
        cls._initialized = True
        try:
            enabled = get_config("observability.langfuse.enabled", False)
            if not enabled:
                logger.info("[Langfuse] observability.langfuse.enabled=false，跳过 tracing")
                return None
            public_key = get_config("observability.langfuse.public_key", "")
            secret_key = get_config("observability.langfuse.secret_key", "")
            host = get_config("observability.langfuse.host", "")
            if not (public_key and secret_key and host):
                logger.warning("[Langfuse] 配置不完整（public_key/secret_key/host 缺失），跳过 tracing")
                return None
            from langfuse.langchain import CallbackHandler
            cls._handler = CallbackHandler(public_key=public_key, secret_key=secret_key, host=host)
            logger.info(f"[Langfuse] handler 已创建，host={host}")
        except ImportError:
            logger.warning("[Langfuse] langfuse 未安装，跳过 tracing")
            return None
        except Exception as e:
            logger.warning(f"[Langfuse] handler 创建失败: {type(e).__name__}: {e}，跳过 tracing")
            return None
        return cls._handler

    @classmethod
    def reset(cls):
        """测试用：重置单例缓存。"""
        cls._handler = None
        cls._initialized = False


def attach_callbacks(config: dict) -> dict:
    """向 config 注入 langfuse callbacks（handler 非 None 时）。

    不改原 config dict（返回新 dict）。
    handler 为 None 时原样返回 config（零影响）。
    """
    handler = LangfuseHandlerFactory.create()
    if handler is None:
        return config
    new_config = dict(config)
    existing = new_config.get("callbacks", [])
    new_config["callbacks"] = [*existing, handler]
    return new_config
```

- [ ] **Step 6: 运行测试验证通过**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langfuse_handler_factory.py::test_create_returns_none_when_disabled -v -p no:warnings`
Expected: PASS

---

### Task 2: factory enabled=true 返回 handler（mock langfuse）

**Files:**
- Modify: `test/test_langfuse_handler_factory.py`

**Interfaces:**
- Consumes: `LangfuseHandlerFactory.create()` from Task 1

- [ ] **Step 1: 写测试**

```python
# 追加到 test/test_langfuse_handler_factory.py

def test_create_returns_handler_when_enabled():
    """enabled=true + 配置完整时 create() 返回 CallbackHandler 实例（mock langfuse）。"""
    from utils.observability.langfuse_handler import LangfuseHandlerFactory
    LangfuseHandlerFactory.reset()

    fake_handler = object()  # 模拟 CallbackHandler 实例

    def fake_get_config(key, default=None):
        cfg = {
            "observability.langfuse.enabled": True,
            "observability.langfuse.public_key": "pk-test",
            "observability.langfuse.secret_key": "sk-test",
            "observability.langfuse.host": "http://localhost:3000",
        }
        return cfg.get(key, default)

    import sys, types
    fake_langfuse = types.ModuleType("langfuse")
    fake_langchain_mod = types.ModuleType("langfuse.langchain")
    fake_langchain_mod.CallbackHandler = lambda **kw: fake_handler
    fake_langfuse.langchain = fake_langchain_mod
    with patch("utils.observability.langfuse_handler.get_config", side_effect=fake_get_config), \
         patch.dict(sys.modules, {"langfuse": fake_langfuse, "langfuse.langchain": fake_langchain_mod}):
        result = LangfuseHandlerFactory.create()

    assert result is fake_handler, "enabled=true + 配置完整应返回 handler 实例"
```

- [ ] **Step 2: 运行测试验证通过**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langfuse_handler_factory.py::test_create_returns_handler_when_enabled -v -p no:warnings`
Expected: PASS（Task 1 实现已含 enabled=true 分支）

---

### Task 3: factory 降级（import 失败 + key 缺失 + 单例）

**Files:**
- Modify: `test/test_langfuse_handler_factory.py`

- [ ] **Step 1: 写测试**

```python
# 追加到 test/test_langfuse_handler_factory.py
import sys


def test_create_returns_none_when_langfuse_not_installed():
    """langfuse 未装（import 失败）时返回 None，不抛异常。"""
    from utils.observability.langfuse_handler import LangfuseHandlerFactory
    LangfuseHandlerFactory.reset()

    def fake_get_config(key, default=None):
        if key == "observability.langfuse.enabled":
            return True
        return {"observability.langfuse.public_key": "pk", "observability.langfuse.secret_key": "sk", "observability.langfuse.host": "http://x"}.get(key, default)

    # 模拟 langfuse 未装：import langfuse.langchain 抛 ImportError
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "langfuse.langchain":
            raise ImportError("No module named 'langfuse'")
        return real_import(name, *args, **kwargs)

    with patch("utils.observability.langfuse_handler.get_config", side_effect=fake_get_config), \
         patch("builtins.__import__", side_effect=fake_import):
        result = LangfuseHandlerFactory.create()

    assert result is None, "langfuse 未装应返回 None，不抛异常"


def test_create_returns_none_when_key_missing():
    """enabled=true 但 key 缺失时返回 None。"""
    from utils.observability.langfuse_handler import LangfuseHandlerFactory
    LangfuseHandlerFactory.reset()

    def fake_get_config(key, default=None):
        cfg = {
            "observability.langfuse.enabled": True,
            "observability.langfuse.public_key": "",  # 缺失
            "observability.langfuse.secret_key": "sk",
            "observability.langfuse.host": "http://x",
        }
        return cfg.get(key, default)

    with patch("utils.observability.langfuse_handler.get_config", side_effect=fake_get_config):
        result = LangfuseHandlerFactory.create()

    assert result is None, "key 缺失应返回 None"


def test_create_is_singleton():
    """多次 create() 返回同一实例（单例缓存）。"""
    from utils.observability.langfuse_handler import LangfuseHandlerFactory
    LangfuseHandlerFactory.reset()

    fake_handler = object()
    call_count = [0]

    def fake_get_config(key, default=None):
        cfg = {
            "observability.langfuse.enabled": True,
            "observability.langfuse.public_key": "pk",
            "observability.langfuse.secret_key": "sk",
            "observability.langfuse.host": "http://x",
        }
        return cfg.get(key, default)

    import types
    fake_langfuse = types.ModuleType("langfuse")
    fake_langchain_mod = types.ModuleType("langfuse.langchain")
    fake_langchain_mod.CallbackHandler = lambda **kw: fake_handler
    fake_langfuse.langchain = fake_langchain_mod

    with patch("utils.observability.langfuse_handler.get_config", side_effect=fake_get_config), \
         patch.dict(sys.modules, {"langfuse": fake_langfuse, "langfuse.langchain": fake_langchain_mod}):
        r1 = LangfuseHandlerFactory.create()
        r2 = LangfuseHandlerFactory.create()

    assert r1 is r2 is fake_handler, "多次 create 应返回同一实例"
```

- [ ] **Step 2: 运行测试验证通过**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langfuse_handler_factory.py -v -p no:warnings`
Expected: 4 PASS（disabled + enabled + import 失败 + key 缺失）+ 1 PASS（singleton）

---

### Task 4: attach_callbacks 辅助函数测试

**Files:**
- Modify: `test/test_langfuse_handler_factory.py`

- [ ] **Step 1: 写测试**

```python
# 追加到 test/test_langfuse_handler_factory.py

def test_attach_callbacks_adds_handler_when_present():
    """handler 非 None 时 attach_callbacks 向 config 加 callbacks。"""
    from utils.observability.langfuse_handler import attach_callbacks, LangfuseHandlerFactory
    LangfuseHandlerFactory.reset()
    fake_handler = object()
    # 预设 factory 单例返回 fake_handler
    LangfuseHandlerFactory._handler = fake_handler
    LangfuseHandlerFactory._initialized = True

    config = {"configurable": {"thread_id": "t1"}}
    result = attach_callbacks(config)

    assert "callbacks" in result, "应注入 callbacks"
    assert fake_handler in result["callbacks"], "callbacks 应含 handler"


def test_attach_callbacks_noop_when_handler_none():
    """handler 为 None 时 attach_callbacks 原样返回 config。"""
    from utils.observability.langfuse_handler import attach_callbacks, LangfuseHandlerFactory
    LangfuseHandlerFactory.reset()
    LangfuseHandlerFactory._handler = None
    LangfuseHandlerFactory._initialized = True

    config = {"configurable": {"thread_id": "t1"}}
    result = attach_callbacks(config)

    assert "callbacks" not in result, "handler None 时不应加 callbacks"


def test_attach_callbacks_does_not_mutate_original():
    """attach_callbacks 不改原 config dict。"""
    from utils.observability.langfuse_handler import attach_callbacks, LangfuseHandlerFactory
    LangfuseHandlerFactory.reset()
    fake_handler = object()
    LangfuseHandlerFactory._handler = fake_handler
    LangfuseHandlerFactory._initialized = True

    config = {"configurable": {"thread_id": "t1"}}
    attach_callbacks(config)

    assert "callbacks" not in config, "原 config 不应被改"


def test_attach_callbacks_preserves_existing_callbacks():
    """已有 callbacks 时追加 langfuse handler（并存）。"""
    from utils.observability.langfuse_handler import attach_callbacks, LangfuseHandlerFactory
    LangfuseHandlerFactory.reset()
    fake_handler = object()
    LangfuseHandlerFactory._handler = fake_handler
    LangfuseHandlerFactory._initialized = True

    existing_handler = object()
    config = {"callbacks": [existing_handler]}
    result = attach_callbacks(config)

    assert existing_handler in result["callbacks"], "应保留已有 callbacks"
    assert fake_handler in result["callbacks"], "应追加 langfuse handler"
```

- [ ] **Step 2: 运行测试验证通过**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langfuse_handler_factory.py -v -p no:warnings`
Expected: 全部 PASS（factory 5 + attach_callbacks 4）

---

### Task 5: config 节（agent_config.json 加 observability.langfuse）

**Files:**
- Modify: `config/agent_config.json`

- [ ] **Step 1: 在顶层加 observability 节**

在 `config/agent_config.json` 顶层（与 `"llm"`、`"agent"` 并列，建议放 `"llm"` 之后或文件末尾 `"agent"` 之后）加：

```json
    "observability": {
        "langfuse": {
            "enabled": false,
            "public_key": "",
            "secret_key": "",
            "host": "http://localhost:3000",
            "self_hosted": true
        }
    },
```

注意 JSON 逗号：若加在 `"llm": {...}` 之后（`"agent"` 之前），`"llm"` 的 `}` 后加逗号；若加在文件末尾（最后一个顶层 key 之后），去掉末尾逗号。

- [ ] **Step 2: 验证 JSON 合法**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -c "import json; json.load(open('config/agent_config.json', encoding='utf-8')); print('JSON OK')"`
Expected: `JSON OK`

- [ ] **Step 3: 验证 get_config 可读**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -c "from utils.config import get_config; print('enabled=', get_config('observability.langfuse.enabled', 'MISSING'))"`
Expected: `enabled= False`（或 MISSING 若 get_config 未加载新配置，需重启进程；首次运行可能 MISSING，正常）

---

### Task 6: task_executor 注入（L123/192 调 attach_callbacks）

**Files:**
- Modify: `executor/langgraph/task_executor.py:123-129`（execute_task）/ `192-201`（execute_task_stream）
- Create: `test/test_langfuse_callbacks_injection.py`

**Interfaces:**
- Consumes: `attach_callbacks(config) -> dict` from Task 1
- Produces: task_executor 的 config 在 enabled 时含 langfuse callbacks

- [ ] **Step 1: 写失败测试**

```python
# test/test_langfuse_callbacks_injection.py
"""验证 task_executor 的 config 注入 langfuse callbacks。"""
import pytest
from unittest.mock import patch, MagicMock


def test_task_executor_execute_task_attaches_callbacks_when_enabled():
    """enabled 时 execute_task 的 config 含 langfuse callbacks（mock factory + graph.ainvoke）。"""
    from utils.observability.langfuse_handler import LangfuseHandlerFactory
    LangfuseHandlerFactory.reset()
    fake_handler = object()
    LangfuseHandlerFactory._handler = fake_handler
    LangfuseHandlerFactory._initialized = True

    captured_config = {}

    class FakeGraph:
        async def ainvoke(self, state, config=None, **kw):
            captured_config.update(config or {})
            from langchain_core.messages import AIMessage
            return {"messages": [AIMessage(content="ok")]}  # 合理 final_state 让 extract_final_output/TaskResult 跑通

    from executor.langgraph.task_executor import LangGraphTaskExecutor
    executor = LangGraphTaskExecutor.__new__(LangGraphTaskExecutor)
    executor._compiled_graphs = {}
    executor.enable_step_monitor = False  # 跳过 step 监控

    from utils.planning.schemas import TaskNode
    from executor.langgraph.task_context import TaskContext, ExecutionOptions
    task = TaskNode(id="t1", agent="a", description="test")
    ctx = TaskContext(session_id="s", task_id="t1")
    opts = ExecutionOptions(timeout=30)

    # _get_or_build_graph 返回 (graph, checkpointer) 元组（见 task_executor.py:118）
    with patch.object(executor, "_get_or_build_graph", return_value=(FakeGraph(), None)):
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            executor.execute_task(task=task, context=ctx, options=opts)
        )

    assert "callbacks" in captured_config, "execute_task 的 config 应含 callbacks"
    assert fake_handler in captured_config["callbacks"], "callbacks 应含 langfuse handler"


def test_task_executor_execute_task_no_callbacks_when_disabled():
    """disabled 时 execute_task 的 config 不含 callbacks（factory 返回 None）。"""
    from utils.observability.langfuse_handler import LangfuseHandlerFactory
    LangfuseHandlerFactory.reset()
    LangfuseHandlerFactory._handler = None
    LangfuseHandlerFactory._initialized = True

    captured_config = {}

    class FakeGraph:
        async def ainvoke(self, state, config=None, **kw):
            captured_config.update(config or {})
            from langchain_core.messages import AIMessage
            return {"messages": [AIMessage(content="ok")]}

    from executor.langgraph.task_executor import LangGraphTaskExecutor
    executor = LangGraphTaskExecutor.__new__(LangGraphTaskExecutor)
    executor._compiled_graphs = {}
    executor.enable_step_monitor = False

    from utils.planning.schemas import TaskNode
    from executor.langgraph.task_context import TaskContext, ExecutionOptions
    task = TaskNode(id="t1", agent="a", description="test")
    ctx = TaskContext(session_id="s", task_id="t1")
    opts = ExecutionOptions(timeout=30)

    with patch.object(executor, "_get_or_build_graph", return_value=(FakeGraph(), None)):
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            executor.execute_task(task=task, context=ctx, options=opts)
        )

    assert "callbacks" not in captured_config, "disabled 时 config 不应含 callbacks"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langfuse_callbacks_injection.py -v -p no:warnings`
Expected: FAIL（execute_task 的 config 不含 callbacks——当前 task_executor 未调 attach_callbacks）

- [ ] **Step 3: 改 execute_task 注入 callbacks**

在 `executor/langgraph/task_executor.py` 的 `execute_task` 方法中，找到 config 构造处（约 L123-126）：

```python
# 当前（约 L123-126）：
config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
```

改为：

```python
from utils.observability.langfuse_handler import attach_callbacks
config = attach_callbacks({"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit})
```

（import 放文件顶部或方法内；建议方法内 import 避免 circular）

- [ ] **Step 4: 改 execute_task_stream 注入 callbacks**

在 `execute_task_stream` 方法中（约 L192-195），同样改：

```python
# 当前（约 L192-195）：
config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
```

改为：

```python
from utils.observability.langfuse_handler import attach_callbacks
config = attach_callbacks({"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit})
```

- [ ] **Step 5: 运行测试验证通过**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_langfuse_callbacks_injection.py -v -p no:warnings`
Expected: 2 PASS（enabled 含 callbacks + disabled 不含）

---

### Task 7: 回归测试

**Files:**
- No changes

- [ ] **Step 1: 跑 test/ 目录全量回归**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/ -v -p no:warnings --tb=short`
Expected: 全部 PASS（含 test_langfuse_handler_factory + test_langfuse_callbacks_injection + 现有 test_task_executor_* / test_stategraph_builder 等）。无回归。

- [ ] **Step 2: 跑根目录关键调度测试回归**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test_task_executor_build_input_bug.py test_plan_executor_summary_bug.py -v -p no:warnings --tb=short`
Expected: 全部 PASS（注入 callbacks 不影响 task_executor 的 _build_input / plan_executor 的 summary 逻辑）

- [ ] **Step 3: 端到端验证（可选，需 langfuse 后端运行）**

若已启动 langfuse（自托管 docker-compose 或云端），设 `observability.langfuse.enabled=true` + 真实 key/host，跑一次对话：

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" test_core_framework.py`
Expected: 对话成功，langfuse dashboard 出现 trace（含 LLM/tool 调用）

若 langfuse 后端未运行，跳过此步（阶段 1 的单元测试已验证注入链路正确）。

---

## Self-Review

**Spec coverage（§5.1/§5.4 注入点①/§9 阶段 1）：**
- ✅ LangfuseHandlerFactory（create + reset + 单例 + 降级）→ Task 1-3
- ✅ attach_callbacks（注入 + 不改原 dict + 保留已有 + None no-op）→ Task 4
- ✅ config 节（observability.langfuse）→ Task 5
- ✅ task_executor 注入点①（execute_task + execute_task_stream）→ Task 6
- ✅ 回归 → Task 7

**Placeholder scan:** 无 TBD/TODO，所有步骤含完整代码 + 确切命令。

**Type consistency:** `LangfuseHandlerFactory.create() -> Optional[Any]`、`attach_callbacks(config: dict) -> dict`、`reset()` 在所有 task 一致。

**风险提示：**
- Task 6 的 execute_task/execute_task_stream 行号（L123/192）可能因前序改动漂移，执行时需读文件确认实际 config 构造位置
- langfuse SDK 与 langchain 1.x 的兼容性需 Task 7 Step 3 端到端验证（单元测试 mock 了 langfuse，不验证真实兼容）
- 非.git repo，无 commit 步骤，改动直接写文件（建议手动备份关键文件）
