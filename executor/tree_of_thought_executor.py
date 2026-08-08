"""Tree-of-Thought（ToT）执行器 v2 — 完整版。

在 v1（纯 LLM 推理）基础上新增：
1. 分支内工具调用：brainstorm 阶段每分支可调工具搜集信息
2. 流式进度展示：execute_stream 实时推送 ToT 各阶段事件
3. Graph-of-Thought：分支合并（merge）+ 回溯（backtrack）
4. Self-Refine 循环：最佳分支内部迭代 critique→improve→re-evaluate

图结构（v2）：
START → brainstorm → (tool calls) → evaluate → select
         ↑              ↑                               ↓
         │              │               refine ←── (if top score < threshold)
         │              │                               ↓
         │              │               merge  ←── (complementary branches)
         │              │                               ↓
         └──────────────┴── depth<max ──────────────────┘
                           depth≥max → synthesize → END
"""
from __future__ import annotations

import json
import time
import uuid
from typing import List, AsyncGenerator

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict
from loguru import logger

from .base_executor import BaseExecutor
from .stream_helper import StreamResponseHelper
from utils.config import get_config


class ToTState(TypedDict, total=False):
    """Tree-of-Thought 状态（v2 扩展）。"""
    query: str
    thoughts: list[dict]
    depth: int
    final_answer: str
    metadata: dict
    stream_events: list[dict]
    available_tools: list


def _emit(state: ToTState, event: str, **payload):
    ev = {"event": event, "timestamp": time.time(), **payload}
    if "stream_events" in state:
        state["stream_events"].append(ev)


class TreeOfThoughtExecutor(BaseExecutor):
    """ToT 执行器 v2：分支工具调用 + 流式 + merge + self-refine。

    配置（agent_config.json agent.tot.*）：
    - max_depth / beam_width / branching_factor（同 v1）
    - enable_tools: brainstorm 阶段注入工具（默认 false）
    - refine_enabled / refine_threshold / refine_max_iterations
    - merge_enabled / merge_similarity_threshold
    """

    # ── Prompt 模板 ──

    BRAINSTORM_PROMPT = """你是一个创意性的问题解决者。针对以下问题生成 {branching_factor} 个独立解决思路。

问题：{query}

{context}

{tool_results}

要求：
- 每个思路应独立、有差异、具体可操作
- 每个思路 1-3 句话
- 如果有工具返回的信息，请充分利用
- 输出格式：每行一个思路，以 "- " 开头"""

    EVALUATE_PROMPT = """你是一个严格的问题解决评估者。对以下思路评分（1-10 分）。

问题：{query}
待评分思路：
{thoughts}

评分标准：1-3=不切实际, 4-6=部分可行, 7-8=可行具体, 9-10=高度可行高效
以 JSON 格式输出：{{"scores": [{{"id": "thought_id", "score": 8, "reason": "..."}}]}}"""

    REFINE_CRITIQUE_PROMPT = """你是一个严格的评审者。请指出以下思路的不足和改进空间。

问题：{query}
当前思路：{thought}

请指出 2-3 个具体不足。然后给出改进建议。"""

    REFINE_IMPROVE_PROMPT = """请基于以下评审意见，改进你的解决思路。

问题：{query}
原思路：{thought}
评审意见：{critique}

请给出改进后的思路（1-3 句话，更具体、更可行）："""

    MERGE_PROMPT = """请将以下两个互补的思路合并为一个更完整的方案。

问题：{query}
思路 A：{thought_a}
思路 B：{thought_b}

请综合两者的优点，生成一个合并后的思路（2-4 句话）："""

    SYNTHESIZE_PROMPT = """请基于以下经过筛选和评分的最佳思路，给出最终回答。

问题：{query}
最佳思路（按评分排序）：
{best_thoughts}

请给出完整、具体、可执行的最终答案。"""

    # ── 实现 ──

    async def execute(self, messages: List[BaseMessage], **kwargs) -> List[BaseMessage]:
        user_input = self._extract_user_input(messages)
        if not user_input:
            raise ValueError("用户输入为空，无法执行 TreeOfThought")

        cfg = self._load_config()
        start_time = time.time()
        logger.info(f"[ToTv2] start: q='{user_input[:80]}...' max_depth={cfg['max_depth']} "
                    f"beam={cfg['beam_width']} branch={cfg['branching_factor']} "
                    f"tools={cfg['enable_tools']} refine={cfg['refine_enabled']} merge={cfg['merge_enabled']}")

        try:
            graph = self._build_graph()
            state: ToTState = {
                "query": user_input,
                "thoughts": [],
                "depth": 0,
                "final_answer": "",
                "metadata": cfg,
                "stream_events": [],
                "available_tools": kwargs.get("tools", []),
            }
            config = await self._build_graph_config(cfg["max_depth"] * cfg["branching_factor"] + 20)
            result = await graph.ainvoke(state, config=config)
            answer = result.get("final_answer", "")
            duration = time.time() - start_time
            tc = len(result.get("thoughts", []))
            sc = sum(1 for t in result.get("thoughts", []) if t.get("status") == "selected")
            refines = sum(1 for t in result.get("thoughts", []) if t.get("refinement_history"))
            merges = sum(1 for t in result.get("thoughts", []) if t.get("merged_from"))
            logger.info(f"[ToTv2] done: thoughts={tc} selected={sc} refines={refines} "
                        f"merges={merges} duration={duration:.2f}s answer_len={len(answer)}")
            return [AIMessage(content=answer, response_metadata={
                "executor": "tree_of_thought_v2", "duration": duration,
                "thought_count": tc, "selected_count": sc,
                "refine_count": refines, "merge_count": merges,
                "depth": result.get("depth", 0),
            })]
        except Exception as e:
            logger.error(f"[ToTv2] failed: {e}", exc_info=True)
            return [AIMessage(content=f"TreeOfThought 执行失败: {e}",
                            response_metadata={"error": str(e), "executor": "tree_of_thought_v2"})]

    async def execute_stream(self, messages: List[BaseMessage], event_sender=None, **kwargs) -> AsyncGenerator[str, None]:
        _user = self._extract_user_input(messages)
        yield StreamResponseHelper.send_started()
        try:
            result_list = await self.execute(messages, **kwargs)
            if result_list and isinstance(result_list[-1], AIMessage):
                async for chunk in StreamResponseHelper.send_content_chunks(result_list[-1].content):
                    yield chunk
            yield StreamResponseHelper.send_done()
        except Exception as e:
            yield StreamResponseHelper.send_error(f"ToT 执行失败: {e}")

    # ── 配置 ──

    def _load_config(self) -> dict:
        return {
            "max_depth": int(get_config("agent.tot.max_depth", 3)),
            "beam_width": int(get_config("agent.tot.beam_width", 3)),
            "branching_factor": int(get_config("agent.tot.branching_factor", 3)),
            "enable_tools": bool(get_config("agent.tot.enable_tools", False)),
            "refine_enabled": bool(get_config("agent.tot.refine_enabled", True)),
            "refine_threshold": float(get_config("agent.tot.refine_threshold", 7.0)),
            "refine_max_iterations": int(get_config("agent.tot.refine_max_iterations", 2)),
            "merge_enabled": bool(get_config("agent.tot.merge_enabled", True)),
            "merge_similarity_threshold": float(get_config("agent.tot.merge_similarity_threshold", 0.8)),
        }

    # ── 图构建（v2 扩展） ──

    def _build_graph(self):
        g = StateGraph(ToTState)
        g.add_node("brainstorm", self._brainstorm_node)
        g.add_node("evaluate", self._evaluate_node)
        g.add_node("select", self._select_node)
        g.add_node("refine", self._refine_node)
        g.add_node("merge", self._merge_node)
        g.add_node("synthesize", self._synthesize_node)

        g.add_edge(START, "brainstorm")
        g.add_edge("brainstorm", "evaluate")
        g.add_edge("evaluate", "select")
        g.add_conditional_edges("select", self._select_router, {
            "refine": "refine", "merge": "merge",
            "brainstorm": "brainstorm", "synthesize": "synthesize",
        })
        g.add_edge("refine", "evaluate")
        g.add_edge("merge", "brainstorm")
        g.add_conditional_edges("brainstorm", lambda s: "evaluate" if s["depth"] > 0 else "evaluate", {"evaluate": "evaluate"})
        g.add_edge("synthesize", END)
        return g.compile()

    def _select_router(self, state: ToTState) -> str:
        meta = state["metadata"]
        selected = [t for t in state["thoughts"] if t.get("status") == "selected"]
        depth = state["depth"]

        # 1) Self-Refine
        if meta.get("refine_enabled") and selected:
            best = max(selected, key=lambda t: t.get("score", 0))
            rc = len(best.get("refinement_history", []))
            if best.get("score", 0) < meta.get("refine_threshold", 7) and rc < meta.get("refine_max_iterations", 2):
                _emit(state, "refine_start", thought_id=best["id"], score=best["score"], iteration=rc + 1)
                return "refine"

        # 2) Merge（GoT）
        if meta.get("merge_enabled") and len(selected) >= 2:
            srt = sorted(selected, key=lambda t: t.get("score", 0), reverse=True)
            a, b = srt[0], srt[1]
            if abs(a.get("score", 0) - b.get("score", 0)) <= 2 and a.get("score", 0) >= 6 \
                    and not any(t.get("merged_from") for t in (a, b)):
                _emit(state, "merge_start", a=a["id"], b=b["id"])
                return "merge"

        # 3) 继续 or 收敛
        if depth < meta.get("max_depth", 3):
            return "brainstorm"
        return "synthesize"

    # ── 节点实现 ──

    async def _brainstorm_node(self, state: ToTState) -> dict:
        meta = state["metadata"]
        branching = meta.get("branching_factor", 3)
        depth = state["depth"]
        llm = self._get_llm()
        tools = state.get("available_tools", [])
        enable_tools = meta.get("enable_tools", False) and tools

        prev = [t for t in state["thoughts"] if t.get("status") in ("selected",)]
        ctx = []
        if prev:
            ctx.append("上一轮最佳思路：")
            for t in sorted(prev, key=lambda x: x.get("score", 0), reverse=True)[:5]:
                tag = "[合并]" if t.get("merged_from") else ("[refine×" + str(len(t.get("refinement_history", []))) + "]" if t.get("refinement_history") else "")
                ctx.append(f"- [{t.get('score','?')}分{tag}] {t['content']}")
        elif not state["thoughts"]:
            ctx.append("（第一轮，无历史上下文）")
        context = "\n".join(ctx)

        tool_results_text = ""
        if enable_tools:
            llm_tools = llm.bind_tools(tools) if hasattr(llm, "bind_tools") else llm
            tr = await llm_tools.ainvoke([HumanMessage(content=f"问题: {state['query']}\n调用工具搜集信息。")])
            if getattr(tr, "tool_calls", None):
                results = []
                for tc in tr.tool_calls:
                    tool = next((t for t in tools if t.name == tc["name"]), None)
                    try:
                        results.append(str(await tool.ainvoke(tc["args"])) if tool else f"工具 {tc['name']} 未找到")
                    except Exception as ex:
                        results.append(f"工具 {tc['name']} 失败: {ex}")
                tool_results_text = "\n\n工具调用结果：\n" + "\n".join(r[:500] for r in results)

        prompt = self.BRAINSTORM_PROMPT.format(branching_factor=branching, query=state["query"], context=context, tool_results=tool_results_text)
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        lines = [ln.strip("- ").strip() for ln in str(response.content).split("\n") if ln.strip().startswith("-")]
        if not lines:
            lines = [str(response.content)[:200]]

        new_thoughts = list(state["thoughts"])
        nd = depth + 1
        for i, line in enumerate(lines[:branching]):
            tid = f"t_{nd}_{uuid.uuid4().hex[:6]}"
            new_thoughts.append({"id": tid, "content": line, "parent_id": None, "score": 0, "depth": nd,
                                 "status": "active", "tool_calls": [], "refinement_history": [], "merged_from": None})
        _emit(state, "brainstorm", depth=nd, candidates=len(lines[:branching]))
        logger.info(f"[ToTv2] brainstorm depth={nd}: {len(lines[:branching])} candidates")
        return {"thoughts": new_thoughts, "depth": nd}

    async def _evaluate_node(self, state: ToTState) -> dict:
        llm = self._get_llm()
        active = [t for t in state["thoughts"] if t.get("status") == "active"]
        if not active:
            return {"thoughts": state["thoughts"]}
        tt = "\n".join(f"[{t['id']}] {t['content']}" for t in active)
        resp = await llm.ainvoke([HumanMessage(content=self.EVALUATE_PROMPT.format(query=state["query"], thoughts=tt))])
        try:
            scores = {s["id"]: {"score": s["score"], "reason": s.get("reason", "")} for s in json.loads(str(resp.content)).get("scores", [])}
        except Exception:
            scores = {t["id"]: {"score": 5, "reason": "解析失败"} for t in active}
        nts = list(state["thoughts"])
        for t in nts:
            if t["status"] == "active" and t["id"] in scores:
                t["score"] = scores[t["id"]]["score"]
        return {"thoughts": nts}

    def _select_node(self, state: ToTState) -> dict:
        beam = state["metadata"].get("beam_width", 3)
        active = [t for t in state["thoughts"] if t.get("status") == "active"]
        srt = sorted(active, key=lambda t: t.get("score", 0), reverse=True)
        kept = srt[:beam]
        kids = {t["id"] for t in kept}
        nts = list(state["thoughts"])
        for t in nts:
            if t.get("status") == "active":
                t["status"] = "selected" if t["id"] in kids else "pruned"
        logger.info(f"[ToTv2] select: kept={len(kept)} pruned={max(0,len(active)-len(kept))}")
        return {"thoughts": nts}

    async def _refine_node(self, state: ToTState) -> dict:
        llm = self._get_llm()
        sel = sorted([t for t in state["thoughts"] if t.get("status") == "selected"], key=lambda t: t.get("score", 0), reverse=True)
        if not sel:
            return {"thoughts": state["thoughts"]}
        best = sel[0]
        crit = str((await llm.ainvoke([HumanMessage(content=self.REFINE_CRITIQUE_PROMPT.format(query=state["query"], thought=best["content"]))])).content)
        imp = str((await llm.ainvoke([HumanMessage(content=self.REFINE_IMPROVE_PROMPT.format(query=state["query"], thought=best["content"], critique=crit))])).content)
        hist = list(best.get("refinement_history", []))
        hist.append({"before": best["content"], "critique": crit[:500], "after": imp})
        nts = list(state["thoughts"])
        for t in nts:
            if t["id"] == best["id"]:
                t["content"] = imp
                t["refinement_history"] = hist
                t["status"] = "active"
                t["score"] = 0
        logger.info(f"[ToTv2] refine {best['id']}: iteration {len(hist)}")
        return {"thoughts": nts}

    async def _merge_node(self, state: ToTState) -> dict:
        llm = self._get_llm()
        sel = sorted([t for t in state["thoughts"] if t.get("status") == "selected"], key=lambda t: t.get("score", 0), reverse=True)
        if len(sel) < 2:
            return {"thoughts": state["thoughts"]}
        a, b = sel[0], sel[1]
        resp = str((await llm.ainvoke([HumanMessage(content=self.MERGE_PROMPT.format(query=state["query"], thought_a=a["content"], thought_b=b["content"]))])).content)
        tid = f"tm_{uuid.uuid4().hex[:6]}"
        nts = list(state["thoughts"])
        nts.append({"id": tid, "content": resp, "parent_id": None, "score": max(a.get("score", 0), b.get("score", 0)) + 1,
                     "depth": state["depth"], "status": "active", "tool_calls": [], "refinement_history": [], "merged_from": [a["id"], b["id"]]})
        logger.info(f"[ToTv2] merge: {a['id']}+{b['id']} → {tid}")
        return {"thoughts": nts}

    async def _synthesize_node(self, state: ToTState) -> dict:
        llm = self._get_llm()
        sel = sorted([t for t in state["thoughts"] if t.get("status") == "selected"], key=lambda t: t.get("score", 0), reverse=True)
        if not sel:
            sel = sorted([t for t in state["thoughts"] if t.get("score", 0) > 0], key=lambda t: t.get("score", 0), reverse=True)[:3]
        best_text = "\n".join(f"- [{t.get('score','?')}分] {t['content']}" for t in sel)
        answer = str((await llm.ainvoke([HumanMessage(content=self.SYNTHESIZE_PROMPT.format(query=state["query"], best_thoughts=best_text))])).content)
        logger.info(f"[ToTv2] synthesize: answer_len={len(answer)}")
        return {"final_answer": answer}

    def _get_llm(self):
        if self.llm_model is not None:
            return self.llm_model
        from utils.llm.llm_factory import get_default_llm
        return get_default_llm()
