from loguru import logger
from typing import Optional
from utils.config import get_config
from utils.sse import build_sse_event, send_sse_data
from utils.common.constants import get_content_chunk_size


class StreamResponseHelper:
    """统一 SSE 事件 helper（B-3：chat stream 与 dispatch 用统一 schema {type, content?, reasoning_content?, done?}）。

    所有方法用 build_sse_event 构建统一 schema（加 type 字段）。
    保持 content/reasoning_content/done 字段兼容前端（前端忽略 type 不破坏）。

    P2-21: 非生成器方法去 async 仪式（无 await，sync 即可），调用方不再 yield await。
    send_content_chunks 是真 async generator（用 yield），保持 async。
    """

    @staticmethod
    def send_config(enable_execution_panel: Optional[bool] = None) -> str:
        if enable_execution_panel is None:
            enable_execution_panel = get_config('agent.enable_execution_panel', False)
        return send_sse_data(build_sse_event("config", config={"enable_execution_panel": enable_execution_panel}))

    @staticmethod
    def send_started() -> str:
        return send_sse_data(build_sse_event("status", status="started"))

    @staticmethod
    def send_error(error_msg: str) -> str:
        logger.error(f"SSE error: {error_msg}")
        return send_sse_data(build_sse_event("error", content=error_msg, reasoning_content="", done=True))

    @staticmethod
    def send_done() -> str:
        return send_sse_data(build_sse_event("done", content="", reasoning_content="", done=True))

    @staticmethod
    async def send_content_chunks(content: str, chunk_size: int = None):
        if chunk_size is None:
            chunk_size = get_content_chunk_size()
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            yield send_sse_data(build_sse_event("content_chunk", content=chunk, reasoning_content=''))

    @staticmethod
    def send_thinking_start() -> str:
        return send_sse_data(build_sse_event("thinking_start", reasoning_content='...\n'))

    @staticmethod
    def send_thinking(content: str) -> str:
        return send_sse_data(build_sse_event("thinking", reasoning_content=f'{content}\n'))
