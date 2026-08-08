import os
from loguru import logger
from typing import List, Optional, Any, Dict, Tuple
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from ..config.config_loader import get_config
_TIKTOKEN_CACHE_DIR = os.path.join(os.path.dirname(__file__), 'tiktoken_cache')
os.environ['TIKTOKEN_CACHE_DIR'] = _TIKTOKEN_CACHE_DIR
try:
    import tiktoken
    import tiktoken.load as _tiktoken_load
    _original_read_file = _tiktoken_load.read_file
    def _offline_read_file(blobpath: str) -> bytes:
        if "://" in blobpath:
            raise RuntimeError(
                f"[tiktoken]  {blobpath}"
                f" {_TIKTOKEN_CACHE_DIR}"
            )
        return _original_read_file(blobpath)
    _tiktoken_load.read_file = _offline_read_file
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logger.warning("[ContextManager] tiktoken ")
class TokenEstimator:
    def __init__(self, model_name: str = "cl100k_base"):
        self._encoder = None
        self._model_name = model_name
        self._init_encoder()
    def _init_encoder(self):
        if not TIKTOKEN_AVAILABLE:
            return
        try:
            self._encoder = tiktoken.get_encoding(self._model_name)
            logger.debug(f"[TokenEstimator]  tiktoken : {self._model_name}")
        except Exception as e:
            logger.warning(f"[TokenEstimator] tiktoken : {e}")
    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        if self._encoder:
            try:
                return len(self._encoder.encode(text))
            except Exception:
                pass
        return len(text) // 3
    def count_messages_tokens(self, messages: List[BaseMessage]) -> int:
        total = 0
        for msg in messages:
            total += self.count_tokens(str(msg.content))
            if hasattr(msg, 'response_metadata') and msg.response_metadata:
                total += self.count_tokens(str(msg.response_metadata))
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    total += self.count_tokens(str(tc))
            total += 4
        return total
class CompressionStrategy:
    def should_compress(self, messages: List[BaseMessage], estimated_tokens: int, max_tokens: int) -> bool:
        raise NotImplementedError
    def compress(self, messages: List[BaseMessage], llm_model: Any = None) -> Tuple[List[BaseMessage], Dict[str, Any]]:
        raise NotImplementedError
class TruncateStrategy(CompressionStrategy):
    def __init__(self, max_messages: int = 50):
        self.max_messages = max_messages
    def should_compress(self, messages: List[BaseMessage], estimated_tokens: int, max_tokens: int) -> bool:
        return len(messages) > self.max_messages
    def compress(self, messages: List[BaseMessage], llm_model: Any = None) -> Tuple[List[BaseMessage], Dict[str, Any]]:
        if len(messages) <= self.max_messages:
            return messages, {}
        system_messages = [msg for msg in messages if isinstance(msg, SystemMessage)]
        conversation_messages = [msg for msg in messages if not isinstance(msg, SystemMessage)]
        recent_messages = conversation_messages[-self.max_messages:]
        truncated_count = len(conversation_messages) - len(recent_messages)
        return system_messages + recent_messages, {
            'truncated_count': truncated_count
        }
class SummarizeStrategy(CompressionStrategy):
    def __init__(self, recent_window_size: int = 10):
        self.recent_window_size = recent_window_size
    def should_compress(self, messages: List[BaseMessage], estimated_tokens: int, max_tokens: int) -> bool:
        return len(messages) > self.recent_window_size
    def compress(self, messages: List[BaseMessage], llm_model: Any = None) -> Tuple[List[BaseMessage], Dict[str, Any]]:
        if len(messages) <= self.recent_window_size:
            return messages, {}
        system_messages = [msg for msg in messages if isinstance(msg, SystemMessage)]
        conversation_messages = [msg for msg in messages if not isinstance(msg, SystemMessage)]
        recent_messages = conversation_messages[-self.recent_window_size:]
        old_messages = conversation_messages[:-self.recent_window_size]
        if not old_messages:
            return system_messages + recent_messages, {}
        logger.debug(
            f"[SummarizeStrategy] : "
            f"old_messages={len(old_messages)}, recent_messages={len(recent_messages)}, "
            f"llm_model_type={type(llm_model).__name__ if llm_model else 'None'}, "
            f"llm_model_is_none={llm_model is None}"
        )
        if llm_model:
            try:
                logger.debug(f"[SummarizeStrategy]  LLM ...")
                summary = self._summarize_messages(old_messages, llm_model)
                logger.debug(f"[SummarizeStrategy] : {summary[:100]}...")
                summary_message = SystemMessage(
                    content=f"[] {summary}"
                )
                return (
                    system_messages + [summary_message] + recent_messages,
                    {
                        'summary': summary,
                        'compressed_count': len(old_messages)
                    }
                )
            except Exception as e:
                logger.warning(f"[SummarizeStrategy] : {e}")
        logger.warning(
            f"[SummarizeStrategy] llm_model  None"
            f""
        )
        return system_messages + recent_messages, {'compressed_count': len(old_messages)}
    def _summarize_messages(self, messages: List[BaseMessage], llm_model: Any) -> str:
        conversation_text = "\n".join([
            f"{'' if isinstance(msg, HumanMessage) else ''}: {msg.content}"
            for msg in messages
        ])
        prompt = f"""
{conversation_text}
"""
        try:
            response = llm_model.invoke([HumanMessage(content=prompt)])
            if hasattr(response, 'content'):
                return response.content
            return str(response)
        except Exception as e:
            logger.error(f"上下文压缩失败: {e}")
            return f"[ {len(messages)} ]"
class ClearToolResultsStrategy(CompressionStrategy):
    def __init__(self, keep_recent: int = 3, placeholder: str = "[]"):
        self.keep_recent = keep_recent
        self.placeholder = placeholder
    def should_compress(self, messages: List[BaseMessage], estimated_tokens: int, max_tokens: int) -> bool:
        tool_count = sum(1 for msg in messages if isinstance(msg, ToolMessage))
        return tool_count > self.keep_recent
    def compress(self, messages: List[BaseMessage], llm_model: Any = None) -> Tuple[List[BaseMessage], Dict[str, Any]]:
        tool_message_indices = []
        for i, msg in enumerate(messages):
            if isinstance(msg, ToolMessage):
                tool_message_indices.append(i)
        if len(tool_message_indices) <= self.keep_recent:
            return messages, {}
        indices_to_clear = tool_message_indices[:-self.keep_recent]
        if not indices_to_clear:
            return messages, {}
        result = []
        cleared_count = 0
        for i, msg in enumerate(messages):
            if i in indices_to_clear:
                tool_name = getattr(msg, 'name', None) or getattr(msg, 'tool_name', 'unknown')
                simplified = AIMessage(
                    content=self.placeholder,
                    response_metadata={'cleared_tool': tool_name}
                )
                result.append(simplified)
                cleared_count += 1
            else:
                result.append(msg)
        logger.info(f"[ClearToolResultsStrategy]  {cleared_count} ")
        return result, {'cleared_tool_results': cleared_count}
class ACONCompressionStrategy(CompressionStrategy):
    """ACON 压缩策略：保留决策点 + 近 N 轮 + 压缩旧消息/工具结果。

    同步实现（复用 ACONCompressor 的同步分析方法；不调 LLM summary 以避免 async 适配）。
    若需 LLM 摘要，SummarizeStrategy 在其后接力。
    """
    def __init__(self, config=None):
        from compression.acon_compressor import ACONCompressor, CompressionConfig
        self._cfg = config or CompressionConfig()
        self._compressor = ACONCompressor(config=self._cfg)
    def should_compress(self, messages: List[BaseMessage], estimated_tokens: int, max_tokens: int) -> bool:
        return self._compressor.should_compress(messages)
    def compress(self, messages: List[BaseMessage], llm_model: Any = None) -> Tuple[List[BaseMessage], Dict[str, Any]]:
        cfg = self._cfg
        decision_indices = self._compressor._find_decision_points(messages)
        result: List[BaseMessage] = []
        system_messages = [m for m in messages if isinstance(m, SystemMessage)]
        conversation_messages = [m for m in messages if not isinstance(m, SystemMessage)]
        if cfg.keep_system_message and system_messages:
            result.extend(system_messages)
        keep_from_idx = max(0, len(conversation_messages) - cfg.keep_recent_turns * 2)
        compressed_count = 0
        for i, msg in enumerate(conversation_messages):
            should_keep = False
            should_compress_old = False
            if i >= keep_from_idx:
                should_keep = True
            elif i in decision_indices and cfg.preserve_decision_points:
                should_keep = True
            elif isinstance(msg, HumanMessage):
                should_keep = True
                should_compress_old = i < keep_from_idx
            if should_keep:
                if should_compress_old and cfg.compress_old_messages:
                    result.append(self._compressor._compress_message(msg))
                    compressed_count += 1
                elif isinstance(msg, ToolMessage) and cfg.compress_tool_results:
                    result.append(self._compressor._compress_tool_result(msg))
                    compressed_count += 1
                else:
                    result.append(msg)
        return result, {
            "acon": True,
            "decision_points_preserved": len(decision_indices),
            "compressed_count": compressed_count,
        }
class ContextManager:
    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self.max_history = get_config('context.max_history', 50)
        self.compression_enabled = get_config('context.compression_enabled', True)
        self.max_tokens = get_config('llm.default.max_tokens', 2000)
        self.recent_window_size = get_config('context.recent_window_size', 10)
        self.compression_threshold = get_config('context.compression_threshold', 0.8)
        self._token_estimator = TokenEstimator()
        self.strategies: List[CompressionStrategy] = [
            ClearToolResultsStrategy(keep_recent=get_config('context.edit_keep', 3)),
            ACONCompressionStrategy(),
            SummarizeStrategy(recent_window_size=self.recent_window_size),
        ]
        logger.info(f"[ContextManager] : session_id={self.session_id}")
    def set_session_id(self, session_id: str):
        if session_id != self.session_id:
            self.session_id = session_id
            logger.debug(f"[ContextManager]  ID : {session_id}")
    def add_strategy(self, strategy: CompressionStrategy) -> None:
        self.strategies.append(strategy)
    def truncate_messages(
        self, 
        messages: List[BaseMessage],
        max_messages: Optional[int] = None
    ) -> List[BaseMessage]:
        if max_messages is None:
            max_messages = self.max_history
        if len(messages) <= max_messages:
            return messages
        system_messages = [msg for msg in messages if isinstance(msg, SystemMessage)]
        conversation_messages = [msg for msg in messages if not isinstance(msg, SystemMessage)]
        recent_messages = conversation_messages[-max_messages:]
        return system_messages + recent_messages
    def compress_old_messages(
        self,
        messages: List[BaseMessage],
        llm_model: Any
    ) -> List[BaseMessage]:
        if not self.compression_enabled:
            return messages
        if len(messages) <= self.recent_window_size:
            return messages
        system_messages = [msg for msg in messages if isinstance(msg, SystemMessage)]
        conversation_messages = [msg for msg in messages if not isinstance(msg, SystemMessage)]
        recent_messages = conversation_messages[-self.recent_window_size:]
        old_messages = conversation_messages[:-self.recent_window_size]
        if not old_messages:
            return system_messages + recent_messages
        try:
            summary = self._summarize_messages(old_messages, llm_model)
            summary_message = SystemMessage(
                content=f"[] {summary}"
            )
            return system_messages + [summary_message] + recent_messages
        except Exception as e:
            logger.warning(f"上下文压缩警告: {e}")
            return system_messages + recent_messages
    def _summarize_messages(
        self,
        messages: List[BaseMessage],
        llm_model: Any
    ) -> str:
        conversation_text = "\n".join([
            f"{'' if isinstance(msg, HumanMessage) else ''}: {msg.content}"
            for msg in messages
        ])
        prompt = f"""
{conversation_text}
"""
        try:
            response = llm_model.invoke([HumanMessage(content=prompt)])
            if hasattr(response, 'content'):
                return response.content
            return str(response)
        except Exception as e:
            logger.error(f"上下文压缩失败: {e}")
            return f"[ {len(messages)} ]"
    def estimate_tokens(self, messages: List[BaseMessage]) -> int:
        return self._token_estimator.count_messages_tokens(messages)
    def optimize_messages(
        self,
        messages: List[BaseMessage],
        current_input: str,
        llm_model: Any = None,
        max_tokens: Optional[int] = None
    ) -> Tuple[List[BaseMessage], Dict[str, Any]]:
        if max_tokens is None:
            max_tokens = self.max_tokens
        stats = {
            'original_count': len(messages),
            'original_tokens': self.estimate_tokens(messages),
            'strategies_applied': [],
            'final_count': 0,
            'final_tokens': 0,
            'compression_ratio': 0.0,
            'summary': None,
        }
        logger.debug(
            f"[ContextManager] optimize_messages() : "
            f"={len(messages)}, tokens={stats['original_tokens']}, "
            f"max_tokens={max_tokens}, compression_enabled={self.compression_enabled}"
        )
        if not self.compression_enabled:
            stats['final_count'] = len(messages)
            stats['final_tokens'] = stats['original_tokens']
            logger.debug("[ContextManager] ")
            return messages, stats
        result_messages = messages
        estimated_tokens = stats['original_tokens']
        for strategy in self.strategies:
            if strategy.should_compress(result_messages, estimated_tokens, max_tokens):
                strategy_name = strategy.__class__.__name__
                logger.info(f"[ContextManager]  {strategy_name}")
                result_messages, strategy_info = strategy.compress(result_messages, llm_model)
                estimated_tokens = self.estimate_tokens(result_messages)
                stats['strategies_applied'].append(strategy_name)
                if strategy_info.get('summary'):
                    stats['summary'] = strategy_info['summary']
                if estimated_tokens <= max_tokens * (1 - self.compression_threshold + 1):
                    break
        stats['final_count'] = len(result_messages)
        stats['final_tokens'] = estimated_tokens
        if stats['original_tokens'] > 0:
            stats['compression_ratio'] = 1 - (stats['final_tokens'] / stats['original_tokens'])
        return result_messages, stats
    def optimize_messages_simple(
        self,
        messages: List[BaseMessage],
        current_input: str,
        llm_model: Any,
        max_tokens: Optional[int] = None
    ) -> List[BaseMessage]:
        result, _ = self.optimize_messages(messages, current_input, llm_model, max_tokens)
        return result