# 上下文注入优化（dep_result 截断）实施计划 — 方案 A

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `_build_input` 的 task 间 dep_result 注入加字符预算截断，控制 DAG 深层链式 token 膨胀。

**Architecture:** 消费侧截断——`_build_task_context` 收集侧不改，`_build_input` 拼接 dep_result 前调 `_truncate_dep_result` 超限截断（首 70%+尾 30%+中间标记）。config `context.dep_result_max_chars` 驱动，0=禁用（向后兼容）。

**Tech Stack:** Python 3.13 + pydantic + langgraph + loguru + pytest(asyncio_mode=auto)

**Spec:** `docs/superpowers/specs/2026-07-16-context-injection-optimization-design.md`（方案 A）

**Environment:** conda env `D:\ProgramData\miniconda3\envs\install_deb_refactor`，git repo，Python 3.13，pytest（asyncio_mode=auto, testpaths=test）

**Test command:** `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest <test_file> -v -p no:warnings`

## Global Constraints

- `ContextEditingMiddleware` 管的是内层 agent tool 历史，**不动**（与 task 间 dep_result 无关）
- `_build_task_context`（`langgraph_adapter.py:138-149`）**不改**（收集侧保持完整 dep_result）
- 截断只在 `_build_input` 消费侧做
- `max_chars <= 0` 禁用截断（兼容旧行为），是回退开关
- 首尾比例固定 70/30（`head = int(max_chars * 0.7)`，`tail = max_chars - head`）
- 默认 `dep_result_max_chars = 6000`

---

## File Structure

| File | Type | Responsibility |
|------|------|----------------|
| `executor/langgraph/task_executor.py` | Modify | 新增 `_truncate_dep_result` 方法 + 改 `_build_input` 拼接处调截断 |
| `config/agent_config.json` | Modify | `context` 段加 `dep_result_max_chars` |
| `test/test_context_truncation.py` | Create | 截断单元测试 + `_build_input` 集成测试 |

---

### Task 1: 写单元测试（RED）

**Files:**
- Create: `test/test_context_truncation.py`

**Interfaces:**
- Produces: `LangGraphTaskExecutor._truncate_dep_result(self, text: str, max_chars: int) -> str`（Task 2 实现）

- [ ] **Step 1: Write the failing test**

```python
# test/test_context_truncation.py
"""上下文注入优化测试 — dep_result 截断（方案 A）。

spec: docs/superpowers/specs/2026-07-16-context-injection-optimization-design.md
"""
from executor.langgraph.task_executor import LangGraphTaskExecutor


def _make_executor():
    """绕过 __init__（_truncate_dep_result 不依赖 self 其他属性）。"""
    return LangGraphTaskExecutor.__new__(LangGraphTaskExecutor)


def test_truncate_over_limit():
    """超长输入 → 截断 + 标记 + 长度受控。"""
    pe = _make_executor()
    text = "A" * 10000
    result = pe._truncate_dep_result(text, 6000)
    assert "已截断" in result, "应含截断标记"
    assert "已截断 4000 字符" in result, "标记应显示省略字符数"
    assert len(result) < len(text), "截断后应更短"


def test_truncate_under_limit():
    """未超上限 → 原样返回，无标记。"""
    pe = _make_executor()
    text = "A" * 3000
    assert pe._truncate_dep_result(text, 6000) == text


def test_truncate_disabled_zero():
    """max_chars=0 → 禁用截断，原样返回（兼容旧行为）。"""
    pe = _make_executor()
    text = "A" * 10000
    assert pe._truncate_dep_result(text, 0) == text


def test_truncate_disabled_negative():
    """max_chars 为负 → 禁用截断，原样返回。"""
    pe = _make_executor()
    assert pe._truncate_dep_result("A" * 10000, -1) == "A" * 10000


def test_truncate_head_tail_preserved():
    """截断保留首尾（首尾含标记词时仍在结果中）。"""
    pe = _make_executor()
    text = "HEADMARKER" + "X" * 9990 + "TAILMARKER"  # len=10010
    result = pe._truncate_dep_result(text, 6000)
    assert "HEADMARKER" in result, "首部应保留"
    assert "TAILMARKER" in result, "尾部应保留"


def test_truncate_proportions_70_30():
    """首尾比例 70/30：head=4200(全H), tail=1800(全T)。"""
    pe = _make_executor()
    text = "H" * 4200 + "M" * 4000 + "T" * 1800  # len=10000
    result = pe._truncate_dep_result(text, 6000)
    assert result.startswith("H"), "应以首部 H 开头"
    assert result.rstrip().endswith("T"), "应以尾部 T 结尾"
    # 中间的 M 被丢弃
    assert "M" * 100 not in result, "中间 M 应被截断"


def test_truncate_empty_string():
    """空串 → 原样返回。"""
    pe = _make_executor()
    assert pe._truncate_dep_result("", 6000) == ""


def test_truncate_non_str_input():
    """非 str 输入 → str() 转换后处理，不抛异常。"""
    pe = _make_executor()
    result = pe._truncate_dep_result([1, 2, 3], 6000)
    assert isinstance(result, str)
    assert "1" in result


def test_truncate_exception_fallback(monkeypatch):
    """截断异常 → fallback 原样返回（不阻断）。"""
    pe = _make_executor()
    text = "A" * 10000

    class BadStr(str):
        def __new__(cls, s):
            obj = super().__new__(cls, s)
            return obj
        def __getitem__(self, idx):
            # 切片时抛异常，触发 except 分支
            raise RuntimeError("mock slice error")

    bad = BadStr(text)
    result = pe._truncate_dep_result(bad, 6000)
    # fallback 返回原样（转为普通 str）
    assert isinstance(result, str)
    assert "已截断" not in result, "异常时应 fallback 不截断"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_context_truncation.py -v -p no:warnings --tb=line`
Expected: FAIL（`AttributeError: 'LangGraphTaskExecutor' object has no attribute '_truncate_dep_result'`）

---

### Task 2: 实现 `_truncate_dep_result`（GREEN）

**Files:**
- Modify: `executor/langgraph/task_executor.py`（在 `_build_input` 方法前，约 line 384 附近插入）

**Interfaces:**
- Consumes: 无
- Produces: `LangGraphTaskExecutor._truncate_dep_result(self, text: str, max_chars: int) -> str`

- [ ] **Step 1: Add `_truncate_dep_result` method**

在 `executor/langgraph/task_executor.py` 的 `LangGraphTaskExecutor` 类中，`_build_input` 方法（line 386）前插入：

```python
    def _truncate_dep_result(self, text: str, max_chars: int) -> str:
        """截断 dep_result 到 max_chars 以内，保留首 70% + 尾 30%，中间插标记。

        Args:
            text: 上游 task 结果文本
            max_chars: 字符上限；0 或负数表示不截断（兼容旧行为）
        Returns:
            截断后的文本（含标记）或原文本
        """
        if not isinstance(text, str):
            text = str(text)
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        try:
            head = int(max_chars * 0.7)
            tail = max_chars - head
            omitted = len(text) - max_chars
            return (
                f"{text[:head]}"
                f"\n...[已截断 {omitted} 字符]...\n"
                f"{text[-tail:]}"
            )
        except Exception as e:
            logger.warning(f"[LangGraphTaskExecutor] dep_result 截断失败，原样返回: {e}")
            return text
```

注：`logger` 已在 task_executor.py 顶部导入（模块级），无需新增 import。

- [ ] **Step 2: Run test to verify it passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_context_truncation.py -v -p no:warnings`
Expected: 9 PASS（除 `test_truncate_exception_fallback` 可能需调整 mock 外，其余应全过）

若 `test_truncate_exception_fallback` 失败，检查 BadStr 的 `__len__` 是否也需 mock（`len(text) <= max_chars` 先判断）。必要时把 `BadStr` 改为 `__len__` 返回大数 + `__getitem__` 抛错。

- [ ] **Step 3: Commit**

```bash
git add executor/langgraph/task_executor.py test/test_context_truncation.py
git commit -m "feat(task_executor): add _truncate_dep_result for dep_result budget control (plan A, TDD GREEN)"
```

---

### Task 3: 改 `_build_input` 用截断 + 集成测试

**Files:**
- Modify: `executor/langgraph/task_executor.py:396-403`（`_build_input` 的 dependencies 循环）
- Test: `test/test_context_truncation.py`（追加集成用例）

**Interfaces:**
- Consumes: `_truncate_dep_result` from Task 2
- Produces: `_build_input` 输出的 prompt 含截断后的 dep_result

- [ ] **Step 1: Add integration test**

追加到 `test/test_context_truncation.py` 末尾：

```python
from types import SimpleNamespace


def test_build_input_uses_truncation(monkeypatch):
    """_build_input 拼接 dep_result 时调用截断（超长 dep 含标记）。"""
    pe = _make_executor()
    # mock get_config 返回小 max_chars 触发截断
    import executor.langgraph.task_executor as te_mod
    monkeypatch.setattr(te_mod, "get_config", lambda key, default=None: 100 if key == "context.dep_result_max_chars" else default)

    long_dep = "START" + "X" * 5000 + "END"  # len=5010
    task = SimpleNamespace(id="t1", agent="a", description="do task", context_focus=None)
    context = SimpleNamespace(
        dependencies={"dep_A": long_dep},
        session_history=None,
        original_query="original question",
    )
    result = pe._build_input(task, context)
    assert "已截断" in result, "超长 dep_result 应被截断"
    assert "START" in result, "首部应保留"
    assert "END" in result, "尾部应保留"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_context_truncation.py::test_build_input_uses_truncation -v -p no:warnings --tb=line`
Expected: FAIL（`_build_input` 仍全量拼接，无 "已截断" 标记）

- [ ] **Step 3: Modify `_build_input` to use truncation**

`executor/langgraph/task_executor.py:386-408` 的 `_build_input`，现状 dependencies 循环（约 396-405）：

```python
        if context.dependencies:
            input_parts.append("\n")
            has_dep = False
            for dep_id, dep_result in context.dependencies.items():
                if is_error_result(dep_result):
                    continue
                input_parts.append(f"---  {dep_id}  ---\n{dep_result}\n")
                has_dep = True
            if not has_dep:
                input_parts.append("()\n")
```

改为（在循环前读 max_chars，循环内调截断）：

```python
        if context.dependencies:
            max_chars = get_config('context.dep_result_max_chars', 6000)
            input_parts.append("\n")
            has_dep = False
            for dep_id, dep_result in context.dependencies.items():
                if is_error_result(dep_result):
                    continue
                truncated = self._truncate_dep_result(dep_result, max_chars)
                input_parts.append(f"---  {dep_id}  ---\n{truncated}\n")
                has_dep = True
            if not has_dep:
                input_parts.append("()\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_context_truncation.py -v -p no:warnings`
Expected: 10 PASS（含新增集成用例）

- [ ] **Step 5: Commit**

```bash
git add executor/langgraph/task_executor.py test/test_context_truncation.py
git commit -m "feat(task_executor): _build_input truncates dep_result by max_chars budget (plan A, integration)"
```

---

### Task 4: 加 config 项 + JSON 验证

**Files:**
- Modify: `config/agent_config.json`（`context` 段，`edit_trigger` 之后，约 line 317 附近）

- [ ] **Step 1: Add config key**

在 `config/agent_config.json` 的 `context` 段（`edit_trigger` / `_comment_edit_trigger` 之后）加：

```json
        "dep_result_max_chars": 6000,
        "_comment_dep_result_max_chars": "task 间依赖结果(dep_result)注入 prompt 的字符上限，超限截断保留首70%+尾30%+中间标记。0=不截断（兼容旧行为）。默认 6000 约合 1500 token",
```

- [ ] **Step 2: Verify JSON valid**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -c "import json; json.load(open('config/agent_config.json', encoding='utf-8')); print('JSON OK')"`
Expected: `JSON OK`

- [ ] **Step 3: Verify config-driven truncation**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_context_truncation.py::test_build_input_uses_truncation -v -p no:warnings`
Expected: PASS（monkeypatch 模拟 config，验证 config 驱动生效）

- [ ] **Step 4: Commit**

```bash
git add config/agent_config.json
git commit -m "feat(config): add context.dep_result_max_chars for dep_result truncation budget"
```

---

### Task 5: 回归测试

**Files:**
- No changes

- [ ] **Step 1: Run full regression**

Run: `"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_context_truncation.py test/test_multi_agent_dispatch.py test/test_dag_dispatch.py test/test_dispatch_detail.py test/test_dynamic_replanning.py -v -p no:warnings --tb=line`
Expected: 全部 PASS（截断只改 prompt 长度，不影响调度链路）

若回归失败：
- 检查是否某测试的 mock dep_result 超过 6000 被截断导致断言失败 → 调整测试数据或设 `dep_result_max_chars=0`
- 确认 `_build_input` 改动未影响无 dependencies 的分支

- [ ] **Step 2: Final commit (if any fixup needed)**

若回归有 fixup：
```bash
git add -A
git commit -m "test: fix regression after dep_result truncation"
```

若无 fixup，Task 4 的 commit 即终点。

---

## Self-Review

**1. Spec coverage（spec §5.1/§5.2/§5.3/§9）：**
- ✅ §5.1 `_truncate_dep_result`（首70%+尾30%+标记）→ Task 2
- ✅ §5.2 `_build_input` 改用截断 → Task 3
- ✅ §5.3 config `dep_result_max_chars` → Task 4
- ✅ §8 测试（超长/未超/禁用/首尾/空串/非str/异常 fallback）→ Task 1
- ✅ §8.3 回归 → Task 5

**2. Placeholder scan:** 无 TBD/TODO，所有 step 含完整测试代码 + 实现代码 + 确切命令 + 期望输出。

**3. Type consistency:** `_truncate_dep_result(self, text: str, max_chars: int) -> str` 在 Task 1（测试调用）/Task 2（实现）一致；`get_config('context.dep_result_max_chars', 6000)` 在 Task 3/Task 4 一致；首尾 70/30 在所有 task 一致。
