"""规划提示词（最小重建版）

原文件被破坏（三引号 f-string 未终止 + 中文清空），无法恢复原文。
保留完整函数，重建被破坏的 _get_base_planning_prompt 等为最小有效实现。
"""
from typing import Optional
from loguru import logger
from .components.quality import get_quality_assurance


def get_planning_system_prompt(
    subagents_text: str,
    disable_thinking: bool = False,
    response_mode: Optional[str] = None
) -> str:
    mode_guidance = _get_planning_mode_guidance(response_mode)
    base_prompt = _get_base_planning_prompt(subagents_text)
    agent_recommendations = _get_agent_recommendations_section(response_mode)
    quality_standards = _get_quality_standards_section()
    full_prompt = mode_guidance + base_prompt + agent_recommendations + quality_standards
    if disable_thinking:
        full_prompt += "\n\n/no_think"
    return full_prompt


def _get_agent_recommendations_section(response_mode: Optional[str]) -> str:
    if not response_mode:
        return ""
    try:
        from utils.config.mode_helper import get_mode_agent_recommendations
        recommendations = get_mode_agent_recommendations(response_mode)
        priority_agent = recommendations.get('priority_agent', '')
        recommended_agents = recommendations.get('recommended_agents', '')
        if not priority_agent and not recommended_agents:
            return ""
        section_parts = ["\n\n## Agent"]
        if priority_agent:
            section_parts.append(f"\n: {priority_agent}")
            logger.debug(f"[Planning] mode '{response_mode}' Agent: {priority_agent}")
        if recommended_agents:
            recommended_list = [a.strip() for a in recommended_agents.split(',') if a.strip()]
            if priority_agent and priority_agent in recommended_list:
                recommended_list = [a for a in recommended_list if a != priority_agent]
            if recommended_list:
                section_parts.append(f"\n: {', '.join(recommended_list)}")
        return "".join(section_parts)
    except Exception as e:
        logger.warning(f"[Planning] Agent: {e}")
    return ""


def _get_base_planning_prompt(subagents_text: str) -> str:
    return f"""你是任务规划器（Task Planner）。根据用户请求、可用 agent 列表与会话历史，生成 JSON 执行计划。

## 可用 Agents
{subagents_text}

## 执行模式（mode）选择规则
- direct：仅当请求纯属闲聊/问候/无需任何工具或专业能力的常识时才直接回答（如"你好""你是谁""现在几点"）
- agent：单个 agent 即可完成（单 task）
- sequential：有序多步骤，前一个 task 的结果传递给后一个，需按序执行
- parallel：多个无依赖的任务，可同时执行
- dag：存在依赖关系的多任务，按 dependencies 拓扑编排（fan-in）
- dynamic：迭代规划——仅输出第一个 task，系统执行后把结果回灌，你再规划下一个 task 或用 direct 给出最终回复（适用于后续步骤依赖前序结果的场景，每步只需 1 个 task）
- debate：用户要求正反方观点/利弊权衡/多方视角对抗时使用——首轮至少 2 个论证 task（parallel 执行）+ 1 个裁判 task（依赖所有论证 task）。裁判输出含共识点/分歧点后系统自动 replan 第 2 轮（终裁）
- vote：用户要求投票/表决/评选/多数决定时使用——所有投票者 task 并行执行，系统自动统计票数（相对多数/绝对多数/平局），输出结构化投票摘要

## 汇总规则
- 如用户要求"综合""汇总""总结"多个 task 结果，最后一个 task 应是汇总 agent
- 汇总 agent 的 dependencies 必须包含所有前序 task id，系统自动用其输出作为最终答案
- parallel 模式下汇总 agent 需显式设 dependencies 指向所有前序 task
- vote 模式下无需指定计票 task（系统自动计票合成）

## 任务分解（task decomposition）指导
- 将复杂请求拆分为多个 task，每个 task 由一个 agent 承担
- 单个 agent 能完成的请求，使用 agent 模式（仅 1 个 task）
- **委派优先**：涉及文本处理/统计/分析/查询/文档操作等任务时，即使看似简单（如词数统计、格式转换、句子分析），只要可用 agent 列表中存在能力匹配的 agent，**必须委派给该 agent 执行**（agent/sequential/parallel/dag），不得用 direct 直接回答
- 仅当请求纯属闲聊/问候（无任何可委派的任务特征）时才用 direct 模式
- task.id 必须唯一；被依赖的 task 必须存在于 tasks 列表中

## dependencies 说明
- dependencies 是该 task 依赖的其他 task id 列表
- 无依赖的 task 用空列表 []
- dag 模式下用 dependencies 编排依赖顺序（fan-in：等所有依赖完成才执行）
- parallel 模式下所有 task 的 dependencies 为空 []
- sequential 模式下后一个 task 依赖前一个 task id

## 输出格式（仅输出 JSON，不要解释文本）
```json
{{
  "mode": "direct|agent|sequential|parallel|dag|debate|vote",
  "tasks": [
    {{"id": "task_1", "agent": "<agent_name>", "description": "<任务描述>", "dependencies": [], "on_failure": "stop", "condition": null, "replan_on": null}}
  ],
  "original_query": "<用户原始请求>",
  "auto_summary": true
}}
```

- mode 选 direct 时可不输出 tasks，改用 "direct_response" 字段直接给出回复
- on_failure 可选值：stop（失败即终止）、continue（失败但继续）、retry（重试）
- condition（可选，动态重规划）：条件分支触发，形如 {{"when": "failed"}}（task 失败时触发重规划）或 {{"when": "contains", "keyword": "<关键词>"}}（结果含关键词时触发重规划）
- replan_on（可选，动态重规划）：重规划触发表达式，形如 "result.contains('<关键词>')"（结果含关键词时触发 LLM 重规划追加 task）
- condition/replan_on 触发时，系统执行完当前 plan 后调 LLM 重规划（事后重规划，非中断当前执行）；未触发或重规划失败则用原结果
"""



def _get_planning_mode_guidance(response_mode: Optional[str]) -> str:
    if not response_mode:
        return ""
    try:
        from utils.config.mode_helper import get_mode_execution_guidance
        return get_mode_execution_guidance(response_mode) or ""
    except Exception:
        return ""


def _get_quality_standards_section() -> str:
    return get_quality_assurance(for_planning=True)


def get_quality_assurance_for_planning() -> str:
    return get_quality_assurance(for_planning=True)


def get_quality_assurance_for_execution() -> str:
    return get_quality_assurance(for_planning=False)


def get_execution_mode_guidance(response_mode: Optional[str]) -> str:
    if not response_mode:
        return ""
    try:
        from utils.config.mode_helper import get_mode_execution_guidance
        guidance = get_mode_execution_guidance(response_mode)
        if guidance:
            logger.debug(f"[Execution] mode '{response_mode}'")
            return guidance
    except Exception as e:
        logger.warning(f"[Execution] : {e}")
    return ""
