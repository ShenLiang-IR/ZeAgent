import json
import re
import time
import hashlib
from collections import OrderedDict
from typing import List, Dict, Optional, Any, Tuple
from loguru import logger
from langchain_core.messages import SystemMessage, HumanMessage
from utils.llm import call_llm
from utils.config import get_config
from utils.message.message_extractor import extract_reasoning_from_content
from .schemas import ExecutionPlan, TaskNode, PlanMode
from .prompts import get_planning_system_prompt
from .agent_card import format_agent_cards

# ── Plan 缓存（内存 LRU + TTL）──
# P1 temp=0 保证确定性 → 同输入同输出 → 可安全缓存
_plan_cache: "OrderedDict[str, Tuple[ExecutionPlan, float]]" = OrderedDict()


def _plan_cache_key(user_input: str, subagents: List[Dict], response_mode: Optional[str]) -> str:
    """缓存 key：hash(user_input + sorted(agent_names) + response_mode)。"""
    names = sorted(sa.get("agent_name", "") for sa in (subagents or []) if sa and sa.get("agent_name"))
    raw = f"{user_input}|{','.join(names)}|{response_mode or ''}"
    return hashlib.md5(raw.encode()).hexdigest()


def clear_plan_cache() -> int:
    """Agent CRUD 时调，清空 plan 缓存。返回清除数量。"""
    count = len(_plan_cache)
    _plan_cache.clear()
    if count:
        logger.info(f"[Planning] plan cache cleared ({count} entries)")
    return count


def _plan_cache_get(key: str) -> Optional[ExecutionPlan]:
    """查缓存（TTL 未过期则返回 plan）。"""
    cached = _plan_cache.get(key)
    if not cached:
        return None
    plan, ts = cached
    ttl = int(get_config("agent.planner.cache_ttl_seconds", 1800))
    if time.time() - ts > ttl:
        del _plan_cache[key]
        return None
    _plan_cache.move_to_end(key)  # LRU
    return plan


def _plan_cache_put(key: str, plan: ExecutionPlan) -> None:
    """存缓存 + LRU 淘汰。"""
    _plan_cache[key] = (plan, time.time())
    max_entries = int(get_config("agent.planner.cache_max_entries", 32))
    while len(_plan_cache) > max_entries:
        _plan_cache.popitem(last=False)


def _analyze_parallel_potential(plan: ExecutionPlan) -> Dict[str, Any]:
    task_count = len(plan.tasks)
    if task_count <= 1:
        return {"parallel_potential": "low", "reason": "2"}
    no_dep_tasks = [t for t in plan.tasks if not t.dependencies]
    with_dep_tasks = [t for t in plan.tasks if t.dependencies]
    if len(no_dep_tasks) >= 2:
        if plan.mode == PlanMode.SEQUENTIAL:
            return {
                "parallel_potential": "high",
                "reason": f"{len(no_dep_tasks)}DAGPARALLELSEQUENTIAL",
                "no_dep_tasks": [t.id for t in no_dep_tasks],
                "recommendation": "dag" if len(with_dep_tasks) > 0 else "parallel"
            }
        elif plan.mode == PlanMode.PARALLEL:
            return {
                "parallel_potential": "optimal",
                "reason": "PARALLEL"
            }
        elif plan.mode == PlanMode.DAG:
            return {
                "parallel_potential": "optimal",
                "reason": "DAG"
            }
    return {"parallel_potential": "medium", "reason": ""}
def _format_subagents(subagents: List[Dict]) -> str:
    """A4：渲染为 Agent Card 文本（含工具/MCP 能力信息，提升 Planner 路由准确率）。"""
    return format_agent_cards(subagents)
def _extract_json_by_brace_matching(text: str) -> Optional[str]:
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    bracket_depth = 0
    in_string = False
    escape_next = False
    # 记录开括号的顺序（用于截断时正确补全）
    open_stack: list = []
    i = start
    while i < len(text):
        ch = text[i]
        if escape_next:
            escape_next = False
            i += 1
            continue
        if ch == '\\' and in_string:
            escape_next = True
            i += 1
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            i += 1
            continue
        if in_string:
            i += 1
            continue
        if ch == '{':
            depth += 1
            open_stack.append('{')
        elif ch == '}':
            depth -= 1
            if open_stack and open_stack[-1] == '{':
                open_stack.pop()
            if depth == 0:
                return text[start:i + 1]
        elif ch == '[':
            bracket_depth += 1
            open_stack.append('[')
        elif ch == ']':
            bracket_depth -= 1
            if open_stack and open_stack[-1] == '[':
                open_stack.pop()
        i += 1
    # JSON 截断：自动补全缺失的括号（按反向开括号顺序）
    if depth > 0 or bracket_depth > 0 or in_string:
        # 构建正确的关闭序列（反转 open_stack 中未匹配的开括号）
        closing = ''.join('}' if c == '{' else ']' for c in reversed(open_stack))
        repaired = _auto_complete_truncated_json(
            text, start, in_string, closing
        )
        if repaired:
            return repaired
    return None


def _auto_complete_truncated_json(
    text: str, start: int, in_string: bool, closing_sequence: str
) -> Optional[str]:
    """自动补全被截断的 JSON：关闭未闭合的字符串和括号。"""
    import json as _json
    fragment = text[start:]
    if in_string:
        fragment = fragment + '"'
    attempts = [closing_sequence]
    # 去掉末尾截断的不完整 key/value
    if ',' in fragment:
        lines = fragment.rsplit(',', 1)
        attempts.append(lines[0] + closing_sequence)
    # 补齐 key 后缺少的 value（如 "tasks": 被截断）
    if fragment.rstrip().endswith(':'):
        attempts.insert(0, 'null' + closing_sequence)
    for closing in attempts:
        candidate = fragment + closing
        try:
            _json.loads(candidate)
            return candidate
        except _json.JSONDecodeError:
            continue
    return None
def _clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```(json)?', '', text, flags=re.MULTILINE)
        text = re.sub(r'```$', '', text, flags=re.MULTILINE)
    return text.strip()
def _validate_plan_structure(plan: ExecutionPlan):
    """P3: plan 结构校验——重复 id / 悬空依赖 / 循环依赖。

    在 generator 层提前失败，防畸形 plan 到图构建或运行期才暴露。
    """
    task_ids = [t.id for t in plan.tasks]
    # 1. 重复 task id
    if len(task_ids) != len(set(task_ids)):
        dupes = sorted({i for i in task_ids if task_ids.count(i) > 1})
        raise ValueError(f"plan 校验失败：重复 task id: {dupes}")
    id_set = set(task_ids)
    # 2. 悬空依赖（依赖不存在的 task id）
    for t in plan.tasks:
        for dep in (t.dependencies or []):
            if dep not in id_set:
                raise ValueError(f"plan 校验失败：task '{t.id}' 依赖不存在的 task '{dep}'")
    # 3. 循环依赖（Kahn 拓扑排序：若无法排序所有节点则有环）
    in_degree = {tid: 0 for tid in task_ids}
    adj = {tid: [] for tid in task_ids}
    for t in plan.tasks:
        for dep in (t.dependencies or []):
            adj[dep].append(t.id)
            in_degree[t.id] += 1
    queue = [tid for tid in task_ids if in_degree[tid] == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    if visited != len(task_ids):
        raise ValueError(
            f"plan 校验失败：检测到循环依赖（{len(task_ids) - visited} 个 task 在环中）")


async def generate_execution_plan(
    user_input: str,
    subagents: List[Dict],
    session_history: Optional[str] = None,
    llm_model: Optional[Any] = None,
    disable_thinking: bool = False,
    response_mode: Optional[str] = None
) -> ExecutionPlan:
    if not llm_model:
        from utils.llm import get_default_llm
        llm_model = get_default_llm()
    if not llm_model:
        raise ValueError(" LLM ")
    # Plan 缓存：temp=0 保证确定性 → 同输入同输出 → 命中则跳过 LLM 调用
    cache_key = _plan_cache_key(user_input, subagents, response_mode)
    cached_plan = _plan_cache_get(cache_key)
    if cached_plan is not None:
        logger.info("[Planning] cache hit, skip LLM call")
        return cached_plan
    subagents_text = _format_subagents(subagents)
    logger.debug(f"[Planning]  Agent :\n{subagents_text}")
    system_prompt = get_planning_system_prompt(
        subagents_text=subagents_text,
        disable_thinking=disable_thinking,
        response_mode=response_mode
    )
    user_prompt = f"\n{user_input}"
    if session_history:
        user_prompt = f"\n{session_history}\n\n{user_prompt}"
    logger.info(f"[Planning] : {len(user_input)}, response_mode: {response_mode}")
    logger.debug(f"[Planning] ==========  System Prompt ==========")
    logger.debug(system_prompt)
    logger.debug(f"[Planning] ========== System Prompt  (: {len(system_prompt)}) ==========")
    logger.debug(f"[Planning] ========== User Prompt ==========\n{user_prompt}")
    llm_call_start = time.time()
    try:
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        # P1: planner 用 temperature=0 稳定决策（减少同问句不同结果的非确定性）
        planner_llm = llm_model
        planner_temp = get_config("agent.planner.temperature", 0)
        if planner_temp is not None:
            try:
                planner_llm = llm_model.bind(temperature=planner_temp)
            except Exception:
                planner_llm = llm_model  # bind 不支持则 fallback
        result = await call_llm(planner_llm, messages)
        llm_call_duration = time.time() - llm_call_start
        logger.info(f"[Planning] ⏱️ LLM: {llm_call_duration:.2f}")
        response_text = result.content if hasattr(result, 'content') else str(result)
        # P4: plan rationale 落日志（LLM 的推理过程，之前被 extract 丢弃）
        reasoning, cleaned_content = extract_reasoning_from_content(response_text)
        if reasoning:
            logger.info(f"[Planning] rationale: {reasoning[:300]}")
        if cleaned_content != response_text:
            logger.debug(f"[Planning] :\n{cleaned_content}")
            response_text = cleaned_content
        logger.debug(f"[Planning] LLM:\n{response_text}")
        json_text = _clean_json_text(response_text)
        try:
            plan_dict = json.loads(json_text)
        except json.JSONDecodeError as e:
            logger.warning(f"[Planning] JSON brace matching : {e}")
            extracted = _extract_json_by_brace_matching(json_text)
            if extracted and extracted != json_text:
                logger.info("[Planning] brace matching ")
                logger.debug(f"[Planning] : ...{extracted[-50:]}")
                plan_dict = json.loads(extracted)
            else:
                raise ValueError(f" JSON: {json_text[:200]}...")
        plan = ExecutionPlan(**plan_dict)
        # P4: plan rationale 存入 metadata（供下游 plan_review / 日志）
        if reasoning:
            plan.metadata["rationale"] = reasoning[:500]
        # P3: plan 结构校验——重复 id / 悬空依赖 / 循环依赖
        _validate_plan_structure(plan)
        _log_mode_choice_analysis(plan)
        if plan.mode != PlanMode.DIRECT:
            valid_agent_names = {sa.get('agent_name') for sa in subagents if sa and sa.get('agent_name')}
            for task in plan.tasks:
                if task.agent not in valid_agent_names:
                    raise ValueError(f" Agent: '{task.agent}' Agent: {list(valid_agent_names)}")
        if plan.mode != PlanMode.DIRECT and len(plan.tasks) == 1:
            logger.info(f"[Planning]  AGENT  (: {plan.mode})")
            plan.mode = PlanMode.AGENT
        logger.info(f"[Planning] : {plan.mode} , {len(plan.tasks)} ")
        # 缓存成功的 plan（fallback plan 不缓存——mode=direct/agent/sequential/parallel/dag 才缓存）
        if plan.mode != PlanMode.DIRECT or plan.direct_response:
            _plan_cache_put(cache_key, plan)
            logger.debug(f"[Planning] plan cached (key={cache_key[:8]}, size={len(_plan_cache)})")
        return plan
    except Exception as e:
        logger.error(f"[Planning] : {e}", exc_info=True)
        logger.info("[Planning] ")
        return ExecutionPlan(
            mode=PlanMode.SEQUENTIAL,
            tasks=[
                TaskNode(
                    id="fallback_task",
                    agent="default",
                    description=user_input,
                    dependencies=[],
                    on_failure="stop"
                )
            ],
            original_query=user_input,
            auto_summary=False,
            metadata={"fallback": True, "error": str(e)}
        )
def _log_mode_choice_analysis(plan: ExecutionPlan):
    analysis = _analyze_parallel_potential(plan)
    if analysis.get("parallel_potential") == "high":
        logger.warning(
            f"[Planning] ⚠️ : {analysis.get('reason')}"
        )
        logger.warning(
            f"[Planning] :  {analysis.get('recommendation').upper()} "
        )
        logger.warning(
            f"[Planning] : {analysis.get('no_dep_tasks', [])}"
        )
    elif analysis.get("parallel_potential") == "optimal":
        logger.info(
            f"[Planning] [] {plan.mode.value}"
        )