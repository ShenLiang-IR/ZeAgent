import os
import re
import json
import asyncio
from typing import Any, Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
    FunctionMessage,
)

# ---------------------------------------------------------------------------
# tiktoken 估算器（离线安全，自包含；失败回退字符比例估算）
# ---------------------------------------------------------------------------
_TIKTOKEN_CACHE_DIR = os.path.join(os.path.dirname(__file__), "tiktoken_cache")
os.environ["TIKTOKEN_CACHE_DIR"] = _TIKTOKEN_CACHE_DIR

_TIKTOKEN_AVAILABLE = False
_ENCODER = None
try:
    import tiktoken
    import tiktoken.load as _tiktoken_load

    _original_read_file = _tiktoken_load.read_file

    def _offline_read_file(blobpath: str) -> bytes:
        if "://" in blobpath:
            raise RuntimeError(
                f"[ACONCompressor] tiktoken 离线模式，禁止下载: {blobpath}"
            )
        return _original_read_file(blobpath)

    _tiktoken_load.read_file = _offline_read_file
    try:
        _ENCODER = tiktoken.get_encoding("cl100k_base")
        _TIKTOKEN_AVAILABLE = True
    except Exception as e:  # 离线且无缓存时回退
        logger.warning(f"[ACONCompressor] tiktoken 编码不可用，回退字符估算: {e}")
except ImportError:
    logger.warning("[ACONCompressor] tiktoken 未安装，回退字符估算")


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    if _TIKTOKEN_AVAILABLE and _ENCODER is not None:
        try:
            return len(_ENCODER.encode(text))
        except Exception:
            pass
    # 回退：非 ASCII（CJK 等）按 ~1.5 token/字估算（cl100k 实测约 1.25，
    # 取略保守值以防压缩触发偏晚），ASCII 按 ~4 字符/token。
    # 比统一 len//3 更贴近真实，避免中文密集对话在离线环境下压缩触发偏晚。
    non_ascii = sum(1 for c in text if ord(c) > 127)
    return int(non_ascii * 1.5 + (len(text) - non_ascii) // 4)


# 单个 tool_call action 序列化后的最大字符数，防止超大参数导致内存膨胀
_MAX_ACTION_CHARS = 5000


@dataclass
class CompressionConfig:
    trigger_tokens: int = 40000
    target_tokens: int = 20000
    keep_recent_turns: int = 3
    keep_tool_results: int = 2
    keep_system_message: bool = True
    compress_tool_results: bool = True
    max_tool_result_length: int = 500
    compress_old_messages: bool = True
    use_llm_summary: bool = False
    preserve_decision_points: bool = True
    # LLM 决策点识别的 preview token 上限，超过则跳过 LLM 回退规则版（控成本）
    decision_llm_max_tokens: int = 6000
    # LLM 摘要输入的 token 上限，超过则只保留最近的旧消息（防 prompt 溢出）
    summary_max_tokens: int = 8000
    decision_keywords: List[str] = field(default_factory=lambda: [
        "决定", "选择", "因为", "所以", "结论", "最终",
        "decide", "choose", "because", "therefore", "result",
    ])


@dataclass
class ActionObservationPair:
    action: str
    observation: str
    is_compressed: bool = False
    compressed_content: Optional[str] = None
    importance: float = 0.5
    timestamp: datetime = field(default_factory=datetime.now)


class ACONCompressor:
    def __init__(self, config: Optional[CompressionConfig] = None, llm_model: Any = None):
        self.config = config or CompressionConfig()
        self.llm_model = llm_model

    # ------------------------------------------------------------------
    # Token 估算
    # ------------------------------------------------------------------
    def estimate_tokens(self, messages: List[BaseMessage]) -> int:
        """基于 tiktoken 的统一估算，覆盖 content / tool_calls / response_metadata。"""
        total = 0
        for msg in messages:
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                total += _count_tokens(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        total += _count_tokens(item["text"])
                    elif isinstance(item, str):
                        total += _count_tokens(item)
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    total += _count_tokens(self._safe_dumps_tool_call(tc))
            if hasattr(msg, "response_metadata") and msg.response_metadata:
                total += _count_tokens(str(msg.response_metadata))
            total += 4  # 每条消息的结构开销
        return total

    def should_compress(self, messages: List[BaseMessage]) -> bool:
        estimated = self.estimate_tokens(messages)
        return estimated >= self.config.trigger_tokens

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    async def compress(
        self,
        messages: List[BaseMessage],
        current_input: Optional[str] = None,
    ) -> Tuple[List[BaseMessage], Dict[str, Any]]:
        stats: Dict[str, Any] = {
            "original_count": len(messages),
            "original_tokens": self.estimate_tokens(messages),
            "compressed_count": 0,
            "compressed_tokens": 0,
            "compression_ratio": 0.0,
            "ao_pairs_found": 0,
            "decision_points_preserved": 0,
            "tool_results_compressed": 0,
            "strategies_applied": [],
            "llm_failures": 0,
            "fallback_reasons": [],
        }
        logger.debug(
            f"[ACONCompressor] compress() 开始: "
            f"消息数={len(messages)}, tokens={stats['original_tokens']}, "
            f"触发阈值={self.config.trigger_tokens}"
        )
        # 去重：original_tokens 已算过，直接复用，避免 should_compress 再全量估算一次
        if stats["original_tokens"] < self.config.trigger_tokens:
            stats["compressed_count"] = len(messages)
            stats["compressed_tokens"] = stats["original_tokens"]
            logger.debug(
                f"[ACONCompressor] 未触发压缩 "
                f"(tokens={stats['original_tokens']} < {self.config.trigger_tokens})"
            )
            return messages, stats

        ao_pairs = self._extract_ao_pairs(messages)
        stats["ao_pairs_found"] = len(ao_pairs)
        logger.debug(f"[ACONCompressor] 提取到 {len(ao_pairs)} 个 A-O 对")

        # 优先使用 LLM 语义识别决策点，失败回退规则版
        if self.llm_model is not None:
            decision_indices = await self._find_decision_points_llm(messages, stats)
        else:
            decision_indices = self._find_decision_points(messages)
        stats["decision_points_preserved"] = len(decision_indices)
        logger.debug(f"[ACONCompressor] 决策点 {len(decision_indices)} 个")

        compressed_messages = await self._apply_compression(
            messages=messages,
            decision_indices=decision_indices,
            current_input=current_input,
            stats=stats,
        )
        stats["compressed_count"] = len(compressed_messages)
        stats["compressed_tokens"] = self.estimate_tokens(compressed_messages)
        if stats["original_tokens"] > 0:
            stats["compression_ratio"] = 1 - (
                stats["compressed_tokens"] / stats["original_tokens"]
            )
        logger.info(
            f"[ACONCompressor] 压缩完成: {stats['original_tokens']} -> "
            f"{stats['compressed_tokens']} tokens (压缩率: {stats['compression_ratio']:.1%})"
        )
        return compressed_messages, stats

    # ------------------------------------------------------------------
    # AO 对提取（并行安全：按 tool_call_id 匹配）
    # ------------------------------------------------------------------
    def _extract_ao_pairs(self, messages: List[BaseMessage]) -> List[ActionObservationPair]:
        pairs: List[ActionObservationPair] = []
        n = len(messages)
        i = 0
        while i < n:
            msg = messages[i]
            if isinstance(msg, AIMessage) and msg.tool_calls:
                wanted_ids = {tc.get("id") for tc in msg.tool_calls if tc.get("id")}
                observations: Dict[str, str] = {tid: "" for tid in wanted_ids}
                # 向前扫描匹配的 ToolMessage，遇到下一次 AI 动作边界停止；
                # 允许中间穿插 HumanMessage 等非动作消息，按 tool_call_id 精确匹配
                j = i + 1
                while j < n:
                    nxt = messages[j]
                    if isinstance(nxt, AIMessage) and nxt.tool_calls:
                        break
                    if isinstance(nxt, ToolMessage) and nxt.tool_call_id in wanted_ids:
                        observations[nxt.tool_call_id] = str(nxt.content)
                    j += 1
                for tc in msg.tool_calls:
                    pairs.append(ActionObservationPair(
                        action=self._safe_dumps_tool_call(tc),
                        observation=observations.get(tc.get("id"), ""),
                        importance=0.5,
                    ))
            i += 1
        return pairs

    def _safe_dumps_tool_call(self, tool_call: Dict[str, Any]) -> str:
        """序列化 tool_call，并对超大参数做长度保护。"""
        try:
            s = json.dumps(tool_call, ensure_ascii=False)
        except (TypeError, ValueError):
            s = str(tool_call)
        if len(s) > _MAX_ACTION_CHARS:
            s = s[:_MAX_ACTION_CHARS] + f"... [参数已截断，原 {len(s)} 字符]"
        return s

    # ------------------------------------------------------------------
    # 决策点识别
    # ------------------------------------------------------------------
    def _find_decision_points(self, messages: List[BaseMessage]) -> Set[int]:
        """规则版决策点识别（同步），供无 LLM 或失败回退使用。"""
        decision_indices: Set[int] = set()
        for i, msg in enumerate(messages):
            content = str(getattr(msg, "content", ""))
            content_lower = content.lower()
            for keyword in self.config.decision_keywords:
                if keyword and keyword.lower() in content_lower:
                    decision_indices.add(i)
                    if i > 0:
                        decision_indices.add(i - 1)
                    if i < len(messages) - 1:
                        decision_indices.add(i + 1)
                    break
            if isinstance(msg, AIMessage) and msg.tool_calls:
                if i == 0 or i == len(messages) - 1:
                    decision_indices.add(i)
        return decision_indices

    async def _find_decision_points_llm(
        self, messages: List[BaseMessage], stats: Dict[str, Any]
    ) -> Set[int]:
        """LLM 语义决策点识别。要求 LLM 返回 {"indices": [...]} JSON。

        任何解析失败均回退到规则版 _find_decision_points，并记录到 stats。
        """
        if self.llm_model is None:
            return self._find_decision_points(messages)
        try:
            preview = "\n".join(
                f"{i}: {type(m).__name__}: {str(getattr(m, 'content', ''))[:200]}"
                for i, m in enumerate(messages)
            )
            # 成本控制：preview 超过 token 上限则跳过 LLM，回退规则版
            if _count_tokens(preview) > self.config.decision_llm_max_tokens:
                logger.debug(
                    f"[ACONCompressor] 决策点 preview 超 "
                    f"{self.config.decision_llm_max_tokens} token，回退规则版"
                )
                self._record_fallback(stats, "决策点 preview 超预算，回退规则版")
                return self._find_decision_points(messages)
            prompt = (
                "请从下列对话消息中识别真正的'决策点'消息索引（用户做出选择、"
                "确认方案、AI 给出结论性判断的节点）。只返回 JSON，格式为 "
                '{"indices": [索引整数列表]}，不要输出其它内容。\n\n' + preview
            )
            response = await self._llm_invoke([HumanMessage(content=prompt)])
            text = getattr(response, "content", str(response)).strip()
            indices = self._parse_decision_json(text)
            if indices is None:
                logger.warning("[ACONCompressor] LLM 决策点返回无法解析，回退规则版")
                self._record_fallback(stats, "决策点 LLM 返回无法解析，回退规则版")
                return self._find_decision_points(messages)
            valid = {idx for idx in indices if isinstance(idx, int) and 0 <= idx < len(messages)}
            logger.debug(f"[ACONCompressor] LLM 决策点: {valid}")
            return valid
        except Exception as e:
            logger.warning(f"[ACONCompressor] LLM 决策点识别异常，回退规则版: {e}")
            self._record_fallback(stats, f"决策点 LLM 异常: {e}")
            return self._find_decision_points(messages)

    @staticmethod
    def _record_fallback(stats: Dict[str, Any], reason: str) -> None:
        """记录一次 LLM 回退，便于调用方感知压缩质量降级。"""
        stats["llm_failures"] = stats.get("llm_failures", 0) + 1
        stats.setdefault("fallback_reasons", []).append(reason)

    @staticmethod
    def _parse_decision_json(text: str) -> Optional[List[int]]:
        """防御性解析 LLM 返回的 indices JSON。"""
        # 直接解析
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and "indices" in obj:
                return list(obj["indices"])
        except json.JSONDecodeError:
            pass
        # 尝试提取首个 JSON 对象
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
                if isinstance(obj, dict) and "indices" in obj:
                    return list(obj["indices"])
            except json.JSONDecodeError:
                pass
        return None

    async def _llm_invoke(self, messages: List[BaseMessage]) -> Any:
        """异步调用 LLM，优先 ainvoke，其次在线程中跑 invoke。"""
        model = self.llm_model
        if hasattr(model, "ainvoke"):
            return await model.ainvoke(messages)
        if hasattr(model, "invoke"):
            return await asyncio.get_event_loop().run_in_executor(
                None, lambda: model.invoke(messages)
            )
        return type("R", (), {"content": str(model)})()

    # ------------------------------------------------------------------
    # 压缩应用
    # ------------------------------------------------------------------
    async def _apply_compression(
        self,
        messages: List[BaseMessage],
        decision_indices: Set[int],
        current_input: Optional[str],
        stats: Dict[str, Any],
    ) -> List[BaseMessage]:
        result: List[BaseMessage] = []
        system_messages: List[BaseMessage] = []
        conversation_messages: List[BaseMessage] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_messages.append(msg)
            else:
                conversation_messages.append(msg)

        if self.config.keep_system_message and system_messages:
            result.extend(system_messages)
            stats["strategies_applied"].append("keep_system_message")

        keep_from_idx = max(
            0, len(conversation_messages) - self.config.keep_recent_turns * 2
        )
        # 最近 keep_tool_results 个工具结果原样保留（不压缩）
        tool_indices = [
            i for i, m in enumerate(conversation_messages) if isinstance(m, ToolMessage)
        ]
        keep_tool_idx_set: Set[int] = set()
        if self.config.keep_tool_results > 0 and tool_indices:
            keep_tool_idx_set = set(tool_indices[-self.config.keep_tool_results:])

        for i, msg in enumerate(conversation_messages):
            # 近窗：原样保留；但巨型工具结果软压缩（保留 tool_call_id/name 不破链）
            if i >= keep_from_idx:
                if isinstance(msg, ToolMessage):
                    result.append(self._maybe_soft_compress_tool(msg, stats))
                else:
                    result.append(msg)
                continue
            # 决策点：原样保留
            if i in decision_indices and self.config.preserve_decision_points:
                result.append(msg)
                continue
            # 旧 HumanMessage：保留但压缩
            if isinstance(msg, HumanMessage):
                if self.config.compress_old_messages:
                    result.append(self._compress_message(msg))
                else:
                    result.append(msg)
                continue
            # 工具结果：近 N 个原样（巨型则软压缩）；更老的按配置压缩或丢弃
            if isinstance(msg, ToolMessage):
                if i in keep_tool_idx_set:
                    result.append(self._maybe_soft_compress_tool(msg, stats))
                elif self.config.compress_tool_results:
                    compressed_msg = self._compress_tool_result(msg)
                    result.append(compressed_msg)
                    if len(compressed_msg.content) < len(str(msg.content)):
                        stats["tool_results_compressed"] += 1
                # compress_tool_results=False 时丢弃旧工具结果（保持原行为）
                continue
            # 其它旧消息（如无 tool_calls 的 AIMessage）：按原行为丢弃

        if (self.config.use_llm_summary and self.llm_model and
                self.estimate_tokens(result) > self.config.target_tokens):
            result = await self._generate_summary(messages, result, stats)

        stats["strategies_applied"].append("acon_compression")
        return result

    # ------------------------------------------------------------------
    # 单条消息压缩（多句摘要，非仅首句 50 字）
    # ------------------------------------------------------------------
    def _compress_message(self, msg: BaseMessage) -> BaseMessage:
        content = str(getattr(msg, "content", ""))
        if len(content) <= 200:
            return msg

        # 结构化内容（JSON/数组/Traceback）按句切分会破坏语法完整性，走首尾+关键行策略
        stripped = content.lstrip()
        if (
            stripped.startswith("{") or stripped.startswith("[")
            or "Traceback" in content[:200]
        ):
            return self._compress_structured_message(msg, content)

        # 按句末标点切分，保留多个句子以减少信息损失
        budget = min(300, max(100, len(content) // 3))
        raw_segments = re.split(r"(?<=[.!?。！？\n])\s*", content)
        # 软边界二次切分：对仍超过 budget 的长段（常见于无句末标点的中文口语）
        # 按中文逗号/顿号/分号等切分，避免整段硬截断丢句
        sentences: List[str] = []
        for seg in raw_segments:
            seg = seg.strip()
            if not seg:
                continue
            if len(seg) <= budget:
                sentences.append(seg)
            else:
                sub = re.split(r"(?<=[，、；;,])", seg)
                sentences.extend(s for s in sub if s.strip())
        kept: List[str] = []
        total = 0
        for s in sentences:
            if total + len(s) > budget:
                remaining = budget - total
                if remaining > 20:
                    kept.append(s[:remaining] + "...")
                break
            kept.append(s)
            total += len(s)
            if total >= budget:
                break
        if not kept:
            kept = [content[:budget]]

        compressed_content = "[已压缩] " + "".join(kept) + f" ... [原 {len(content)} 字]"
        return self._typed_message(msg, compressed_content)

    def _compress_structured_message(self, msg: BaseMessage, content: str) -> BaseMessage:
        """对 JSON / Traceback 等结构化内容保留首尾 + 中间关键错误行。"""
        budget = min(300, max(100, len(content) // 3))
        half = budget // 2
        head = content[:half]
        tail = content[-half:] if half > 0 else ""
        middle = content[half : len(content) - half] if half > 0 else ""
        key_patterns = [
            "error", "failed", "exception", "错误", "失败", "异常",
            "ValueError", "KeyError", "TypeError", "AttributeError",
        ]
        key_lines = [
            line for line in middle.split("\n")
            if any(p in line for p in key_patterns)
        ][:3]
        out = "[已压缩] " + head
        if key_lines:
            out += f"\n... [中间关键行 {len(key_lines)} 条] ...\n" + "\n".join(key_lines)
        omitted = len(content) - len(head) - len(tail)
        out += f"\n... [省略 {omitted} 字符] ...\n" + tail
        return self._typed_message(msg, out)

    @staticmethod
    def _typed_message(msg: BaseMessage, content: str) -> BaseMessage:
        if isinstance(msg, HumanMessage):
            return HumanMessage(content=content)
        if isinstance(msg, AIMessage):
            return AIMessage(content=content)
        return msg

    # ------------------------------------------------------------------
    # 工具结果压缩（首尾 + 中间关键行）
    # ------------------------------------------------------------------
    def _maybe_soft_compress_tool(
        self, msg: ToolMessage, stats: Dict[str, Any]
    ) -> BaseMessage:
        """近窗/受保护工具结果的软压缩：仅当内容超过 2 倍阈值时压缩。

        _compress_tool_result 已保留 tool_call_id 与 name，故工具调用链完整性不破。
        """
        content = str(msg.content)
        if len(content) > self.config.max_tool_result_length * 2:
            compressed = self._compress_tool_result(msg)
            if len(compressed.content) < len(content):
                stats["tool_results_compressed"] = stats.get("tool_results_compressed", 0) + 1
            return compressed
        return msg

    def _compress_tool_result(self, msg: ToolMessage) -> BaseMessage:
        content = str(msg.content)
        if len(content) <= self.config.max_tool_result_length:
            return msg

        half = self.config.max_tool_result_length // 2
        head_len = half // 2 + 10
        tail_len = half // 2
        head = content[:head_len]
        tail = content[-tail_len:] if tail_len > 0 else ""
        middle = content[head_len : len(content) - tail_len] if tail_len > 0 else content[head_len:]

        # 从被丢弃的中间区域提取关键行（错误/异常/失败信号）
        key_patterns = ["error", "failed", "exception", "错误", "失败", "异常"]
        key_lines = [
            line for line in middle.split("\n")
            if any(p in line.lower() for p in key_patterns)
        ][:5]

        truncated = head
        if key_lines:
            truncated += f"\n... [中间关键行 {len(key_lines)} 条] ...\n" + "\n".join(key_lines)
        omitted = len(content) - len(head) - len(tail)
        truncated += f"\n... [省略 {omitted} 字符] ...\n" + tail

        return ToolMessage(
            content=truncated,
            tool_call_id=msg.tool_call_id,
            name=getattr(msg, "name", None),
        )

    # ------------------------------------------------------------------
    # LLM 摘要（基于全部可压缩旧消息，合并进 SystemMessage）
    # ------------------------------------------------------------------
    async def _generate_summary(
        self,
        original_messages: List[BaseMessage],
        compressed_messages: List[BaseMessage],
        stats: Dict[str, Any],
    ) -> List[BaseMessage]:
        if not self.llm_model:
            return compressed_messages
        try:
            # 摘要范围：除 SystemMessage 与近窗之外的全部可压缩旧消息
            non_system = [m for m in original_messages if not isinstance(m, SystemMessage)]
            recent_window = self.config.keep_recent_turns * 2
            old_messages = non_system[: max(0, len(non_system) - recent_window)]
            if not old_messages:
                return compressed_messages

            # token 上界保护：从最近的旧消息倒序累积，超 budget 即停（保留更相关的近期上下文）
            budget = self.config.summary_max_tokens
            texts = [
                f"{type(m).__name__}: {str(getattr(m, 'content', ''))[:500]}"
                for m in old_messages
            ]
            kept_texts: List[str] = []
            acc = ""
            for t in reversed(texts):
                candidate = t + "\n" + acc if acc else t
                if _count_tokens(candidate) > budget:
                    break
                acc = candidate
                kept_texts.insert(0, t)
            if not kept_texts:
                # 单条即超预算：截断最后一条
                acc = texts[-1][: budget * 3]
            conversation_text = acc

            prompt = (
                "请将以下历史对话压缩为简洁摘要，保留关键事实、决策与结论。"
                "不要编造信息。\n\n" + conversation_text
            )
            response = await self._llm_invoke([HumanMessage(content=prompt)])
            summary = getattr(response, "content", str(response))
            if not summary or not summary.strip():
                return compressed_messages

            stats["strategies_applied"].append("llm_summary")
            stats["summary"] = summary

            # 合并进现有 SystemMessage：若已含旧 [历史摘要] 标记则替换，避免堆叠
            result: List[BaseMessage] = []
            merged = False
            marker = "[历史摘要]"
            for m in compressed_messages:
                if isinstance(m, SystemMessage) and not merged:
                    base = m.content
                    if marker in base:
                        # 替换旧摘要块，保留标记之前的原系统人设内容
                        base = base.split(marker, 1)[0].rstrip()
                    merged_content = f"{base}\n\n{marker} {summary}"
                    result.append(SystemMessage(content=merged_content))
                    merged = True
                else:
                    result.append(m)
            if not merged:
                result.insert(0, SystemMessage(content=f"{marker} {summary}"))
            return result
        except Exception as e:
            logger.warning(f"[ACONCompressor] LLM 摘要生成失败: {e}")
            self._record_fallback(stats, f"摘要 LLM 异常: {e}")
            return compressed_messages


async def compress_conversation(
    messages: List[BaseMessage],
    config: Optional[CompressionConfig] = None,
    llm_model: Any = None,
) -> Tuple[List[BaseMessage], Dict[str, Any]]:
    compressor = ACONCompressor(config=config, llm_model=llm_model)
    return await compressor.compress(messages)
