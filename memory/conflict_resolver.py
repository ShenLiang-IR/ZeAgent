"""冲突检测/合并 — Mem0 式 LLM 判 ADD/UPDATE/MERGE/NONE。

- 仅当存在相似候选才调 LLM（相似门控由调用方负责过滤候选）。
- LLM 不可用/解析失败/非法 action → 降级 ADD（兼容现状）。
- llm_caller 可注入：签名 (system_prompt, user_prompt) -> Awaitable[Optional[dict]]，
  返回已解析的 dict；默认走 LLMCaller.call_with_prompt(parse_json=True)。
"""
from __future__ import annotations
from typing import Awaitable, Callable, List, Optional, TypedDict
from loguru import logger
from .blocks import MemoryBlock

Literal_action = str  # "ADD"|"UPDATE"|"MERGE"|"NONE"


class ConflictDecision(TypedDict, total=False):
    action: str
    target_id: Optional[str]
    merged_content: Optional[str]
    reason: Optional[str]


class ConflictResolver:
    def __init__(
        self,
        llm_caller: Optional[Callable[[str, str], Awaitable[Optional[dict]]]] = None,
        similarity_threshold: float = 0.6,
        max_candidates: int = 5,
    ):
        self._llm_call = llm_caller or self._default_llm_call
        self.similarity_threshold = similarity_threshold
        self.max_candidates = max_candidates

    async def _default_llm_call(self, system_prompt: str, user_prompt: str) -> Optional[dict]:
        try:
            from utils.llm.llm_caller import LLMCaller
            r = await LLMCaller.call_with_prompt(system_prompt, user_prompt, parse_json=True)
            if r.success and r.parsed:
                return r.parsed
        except Exception as e:
            logger.warning(f"[ConflictResolver] LLM 调用失败，降级 ADD: {e}")
        return None

    async def resolve(self, new: MemoryBlock, candidates: List[MemoryBlock]) -> ConflictDecision:
        if not candidates:
            return {"action": "ADD", "target_id": None, "merged_content": None, "reason": "no candidates"}
        parsed = await self._llm_call(self._system_prompt(), self._user_prompt(new, candidates))
        action = (parsed or {}).get("action", "").upper() if parsed else ""
        if action not in ("ADD", "UPDATE", "MERGE", "NONE"):
            logger.warning(f"[ConflictResolver] 非法/缺失 action={action!r}，降级 ADD")
            return {"action": "ADD", "target_id": None, "merged_content": None, "reason": "degraded"}
        return {
            "action": action,
            "target_id": parsed.get("target_id"),
            "merged_content": parsed.get("merged_content"),
            "reason": parsed.get("reason"),
        }

    async def consolidate_pair(self, a: MemoryBlock, b: MemoryBlock) -> Optional[str]:
        parsed = await self._llm_call(self._merge_system_prompt(), self._merge_user_prompt(a, b))
        if not parsed:
            return None
        if not parsed.get("merge", False):
            return None
        merged = (parsed.get("merged_content") or "").strip()
        return merged or None

    def _system_prompt(self) -> str:
        return (
            "你是记忆冲突判定器。给定【新记忆】与【候选记忆列表】，判断新记忆与候选的关系，"
            "只输出 JSON：{\"action\":\"ADD|UPDATE|MERGE|NONE\","
            "\"target_id\":\"候选id\",\"merged_content\":\"合并后内容\",\"reason\":\"简述\"}。\n"
            "- ADD：新事实，与候选无关。\n"
            "- UPDATE：新记忆取代/纠正候选（如偏好变更），target_id 指向被取代的候选。\n"
            "- MERGE：互补，合并为一条更完整记忆，给出 merged_content，target_id 指向保留的候选。\n"
            "- NONE：重复，丢弃新记忆，target_id 指向重复的候选。\n"
            "只输出 JSON，不要解释。"
        )

    def _user_prompt(self, new: MemoryBlock, candidates: List[MemoryBlock]) -> str:
        import json as _json
        cands = [{"id": c.id, "type": getattr(c.type, "value", str(c.type)), "content": c.content}
                 for c in candidates]
        return _json.dumps({
            "new": {"id": new.id, "type": getattr(new.type, "value", str(new.type)),
                    "content": new.content},
            "candidates": cands,
        }, ensure_ascii=False)

    def _merge_system_prompt(self) -> str:
        return (
            "你是记忆合并器。判断两条已有记忆是否可合并为一条更完整、不丢信息的记忆。"
            "只输出 JSON：{\"merge\":true|false,\"merged_content\":\"合并后内容\"}。\n"
            "merge=true 时 merged_content 须保留两者关键信息、消除冗余；"
            "内容主题无关则 merge=false。只输出 JSON。"
        )

    def _merge_user_prompt(self, a: MemoryBlock, b: MemoryBlock) -> str:
        import json as _json
        return _json.dumps({
            "memory_a": {"id": a.id, "content": a.content},
            "memory_b": {"id": b.id, "content": b.content},
        }, ensure_ascii=False)
