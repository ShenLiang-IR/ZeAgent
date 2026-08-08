# 上下文注入优化设计 — dep_result 截断 + 预算控制（方案 A）

> 日期：2026-07-16
> 方案：A（截断 + 预算控制，零额外 LLM 调用）
> 前置分析：`docs/executoranalyse.md` 缺点3（上下文全量文本注入）
> 关联代码：`executor/langgraph/task_executor.py` `_build_input` / `executor/workflow/langgraph_adapter.py` `_build_task_context`

## 1. 背景

### 1.1 痛点

DAG 模式下，下游 task 通过 `_build_input` 把上游 task 的完整输出文本（`dep_result`）拼进初始 prompt。深层链式依赖时 context 逐层累积，token 成本快速膨胀。

### 1.2 现状（代码实证）

`executor/langgraph/task_executor.py:386-408` 的 `_build_input`：

```python
for dep_id, dep_result in context.dependencies.items():
    if is_error_result(dep_result):
        continue
    input_parts.append(f"---  {dep_id}  ---\n{dep_result}\n")   # ← 全量拼接，无截断
```

`executor/workflow/langgraph_adapter.py:138-149` 的 `_build_task_context`：遍历 `task.dependencies`，从 `context[dep_id]` 取**完整** `dep_result` 放入 `dependencies` dict，同样无截断。

### 1.3 为何 ContextEditingMiddleware 帮不上

`config/agent_config.json:316` 已把 `context.edit_trigger` 降到 **30000**（注释："降至 30000 减少长链式 DAG 的 token 成本"）。但 `ContextEditingMiddleware` / `ClearToolUsesEdit`（`core/middleware/context_editing_middleware.py:25-35`）压缩的是**内层 agent 图 ReAct 循环的 tool messages 历史**（除最近 keep=3 个 tool 结果外替换为 placeholder），**不管 task 间传递的 dep_result**。

`_build_input` 构建的是**初始 HumanMessage**，此时还未进入 ReAct 循环、middleware 尚未介入。所以 dep_result 全量注入的膨胀，middleware 根本管不到——"调阈值"这条路已经走过且无效。

### 1.4 为什么不选摘要方案（B）

方案 B（上游 task 完成后额外 LLM 生成摘要，下游接收摘要）：
- 每条依赖多一次 LLM 调用，DAG 深链路时延迟/成本累积
- 摘要质量依赖 LLM，可能丢失下游判断所需细节
- 改动大（node 返回结构 + adapter context 传递 + node 函数）
- 非确定性，难测

方案 A（截断）零 LLM 调用、确定性强、改动集中、易测，作为首期实现。

## 2. 目标

- 给 `_build_input` 的 dep_result 注入加**字符预算上限**，超限截断保留首尾，控制 task 间传递的 prompt 体积
- 零额外 LLM 调用（纯字符串处理）
- 向后兼容：`max_chars=0` 禁用截断，行为与现状一致
- 不改调度链路语义（仅改 prompt 长度，不影响 task 完成与 context 传递）
- 有回归保护（现有 dispatch 测试全通过）

## 3. 非目标

- 不做摘要传递（方案 B，后续可选）
- 不改 `_build_task_context` 的依赖收集逻辑（仅在 `_build_input` 消费侧截断）
- 不改 ContextEditingMiddleware（它管内层，职责不同）
- 不改 SSE / 前端（截断只影响内部 prompt，不影响对外事件）
- 不按 token 计（首期用字符数，简单可测；token 计需 tokenizer，后续可选）

## 4. 架构

```
下游 task node 执行
  └─ adapter._build_task_context: 把 dep_result 完整放入 context.dependencies（不改）
     └─ task_executor._build_input:
        ├─ 读 config context.dep_result_max_chars（默认 6000）
        ├─ 遍历 context.dependencies:
        │    truncated = self._truncate_dep_result(dep_result, max_chars)
        │    input_parts.append(f"---  {dep_id}  ---\n{truncated}\n")
        └─ （其余拼接逻辑不变）
```

截断发生在 `_build_input` 消费侧，`_build_task_context` 的收集侧保持原样（完整 dep_result 仍在 context 中，供降级/调试/其他消费方使用）。

## 5. 组件设计

### 5.1 新增 `_truncate_dep_result`

**文件**：`executor/langgraph/task_executor.py`（`LangGraphTaskExecutor` 类内，`_build_input` 前）

```python
def _truncate_dep_result(self, text: str, max_chars: int) -> str:
    """截断 dep_result 到 max_chars，超限保留首部 70% + 尾部 30%，中间插标记。

    Args:
        text: 上游 task 结果文本
        max_chars: 字符上限；0 或负数表示不截断（原样返回）

    Returns:
        截断后的文本（含标记）或原文本
    """
    if not max_chars or max_chars <= 0:
        return text
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= max_chars:
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
        logger.warning(f"[LangGraphTaskExecutor] dep_result 截断失败: {e}，原样返回")
        return text
```

**首尾比例依据**：上游 task 输出通常是"结论/摘要在前 + 过程论述在中 + 最终结果在后"。首部 70% 覆盖结论与大部分论述，尾部 30% 保留最终结果。中间过程论述信息密度较低，截断影响最小。

### 5.2 改 `_build_input`

**文件**：`executor/langgraph/task_executor.py:386-408`

现状（399-403）：
```python
for dep_id, dep_result in context.dependencies.items():
    if is_error_result(dep_result):
        continue
    input_parts.append(f"---  {dep_id}  ---\n{dep_result}\n")
    has_dep = True
```

改后：
```python
max_chars = get_config('context.dep_result_max_chars', 6000)
for dep_id, dep_result in context.dependencies.items():
    if is_error_result(dep_result):
        continue
    truncated = self._truncate_dep_result(dep_result, max_chars)
    input_parts.append(f"---  {dep_id}  ---\n{truncated}\n")
    has_dep = True
```

### 5.3 新增 config

**文件**：`config/agent_config.json`（`context` 段，`edit_keep` / `edit_trigger` 之后）

```json
"dep_result_max_chars": 6000,
"_comment_dep_result_max_chars": "task 间依赖结果(dep_result)注入 prompt 的字符上限，超限截断保留首70%+尾30%+中间标记。0=不截断（兼容旧行为）。默认 6000 约合 1500 token"
```

## 6. 数据流

```
DAG: A → C (C 依赖 A)
  A 执行完成, result = "<10000 字符的市场分析报告>"
  → context["A"] = result（完整，_build_task_context 不改）
  → C 的 node 执行:
    adapter._build_task_context:
      dependencies = {"A": "<10000 字符>"}  ← 完整收集
    task_executor._build_input:
      max_chars = 6000
      truncated = _truncate_dep_result("<10000 字符>", 6000)
        → "<4200 字符>\n...[已截断 4000 字符]...\n<1800 字符>"
      input_parts.append("--- A ---\n{truncated}\n")
    → C 的 LLM 收到约 6000 字符的 A 结果（而非 10000）
```

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| 截断异常（理论上仅 str 转换/切片失败） | fallback 原样返回 + log warning，不阻断执行 |
| `max_chars=0` 或负数 | 不截断，原样返回（兼容旧行为） |
| `max_chars` 非法（非 int / None） | `get_config` fallback 默认 6000 |
| `dep_result` 非 str | `_truncate_dep_result` 内 `str(text)` 转换后截断（现有 `_build_input` 已隐式 str 化） |
| config 项缺失 | `get_config('context.dep_result_max_chars', 6000)` 用默认 6000 |

## 8. 测试策略

### 8.1 单元测试 `test/test_context_truncation.py`

| 用例 | 验证 |
|---|---|
| `test_truncate_over_limit` | 10000 字符输入，max=6000 → 输出含 "已截断 4000 字符" 标记，总长 ≤ 6000 + 标记长度 |
| `test_truncate_under_limit` | 3000 字符输入，max=6000 → 原样返回，无标记 |
| `test_truncate_disabled_zero` | 任意输入，max=0 → 原样返回 |
| `test_truncate_disabled_negative` | 任意输入，max=-1 → 原样返回 |
| `test_truncate_head_tail_preserved` | 10000 字符（首="HEADMARKER"，尾="TAILMARKER"），max=6000 → 输出含 HEADMARKER 与 TAILMARKER |
| `test_truncate_non_str_input` | 输入 list/dict，max=6000 → str 化后处理，不抛异常 |
| `test_truncate_exception_fallback` | mock 切片抛异常 → 原样返回 + warning |
| `test_build_input_uses_truncation` | mock context.dependencies 含超长 dep_result，调 `_build_input` → 输出含截断标记 |

### 8.2 回归测试

| 测试 | 预期 |
|---|---|
| `test/test_multi_agent_dispatch.py` | 3/3 通过（截断不影响调度） |
| `test/test_dag_dispatch.py` | 3/3 通过（DAG 依赖传递正常） |
| `test/test_dispatch_detail.py` | 5/5 通过 |
| `test/test_dynamic_replanning.py` | 13/13 通过（重规划不受影响） |

**测试命令**：
```bash
"D:\ProgramData\miniconda3\envs\install_deb_refactor\python.exe" -m pytest test/test_context_truncation.py test/test_multi_agent_dispatch.py test/test_dag_dispatch.py test/test_dispatch_detail.py test/test_dynamic_replanning.py -v -p no:warnings
```

## 9. 分阶段

| 阶段 | 内容 | 验证 |
|---|---|---|
| 1 | 写 `test_context_truncation.py`（RED） | import 失败 / `_truncate_dep_result` 不存在 |
| 2 | 实现 `_truncate_dep_result` + 改 `_build_input`（GREEN） | 单元测试通过 |
| 3 | 加 config 项 `dep_result_max_chars` | JSON 有效 |
| 4 | 回归测试 | 全部 PASS |

## 10. 文件变更清单

| 文件 | 变更类型 | 阶段 |
|---|---|---|
| `executor/langgraph/task_executor.py` | 改（新增 `_truncate_dep_result` + 改 `_build_input`） | 2 |
| `config/agent_config.json` | 改（context 段加 `dep_result_max_chars`） | 3 |
| `test/test_context_truncation.py` | 新建 | 1 |

## 11. 风险与回退

| 风险 | 等级 | 缓解 |
|---|---|---|
| 截断丢失下游判断所需关键信息 | 中 | 首尾保留（结论+最终结果通常在首尾）；`max_chars` 可调大或设 0 禁用 |
| 默认 6000 过小/过大 | 低 | config 可调，0 禁用；若担心过小可调大（如 8000）或设 0 完全禁用 |
| 截断标记干扰 LLM | 低 | 标记是 `...[已截断 N 字符]...`，LLM 能理解为省略 |
| 首尾比例 70/30 不适所有场景 | 低 | 后续可 config 化（首期固定，YAGNI） |

**回退**：`context.dep_result_max_chars: 0` 即完全禁用截断，行为与现状一致，零影响。

## 12. 后续（非本期）

- 方案 B 摘要传递（关键 task 可配摘要，保真度优先场景）
- 按 token 计而非字符（需 tokenizer）
- 首尾比例 config 化（`context.dep_result_head_ratio`）
- per-task 覆盖（某些 task 的 dep_result 不截断）
