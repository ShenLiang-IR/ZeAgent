"""SSE 工具（向后兼容 re-export）。

P2-2: 真相源已迁至 utils.sse，本模块保留 re-export 供 api/chat 内既有
`from .sse_utils import send_sse_data` 的消费者使用，避免破坏调用方。
"""
from utils.sse import send_sse_data, _send_execution_event

__all__ = ["send_sse_data", "_send_execution_event"]
