from typing import AsyncGenerator, Tuple
from utils.common.constants import REASONING_CHUNK_SIZE, get_content_chunk_size
from utils.message.message_extractor import THINK_OPEN, THINK_CLOSE
from .sse_utils import send_sse_data
class StreamBuffers:
    THINK_START_PATTERNS = [THINK_OPEN, f'`{THINK_OPEN}`']
    THINK_END_PATTERNS = [THINK_CLOSE, f'`{THINK_CLOSE}`']
    def __init__(self):
        self.content_buffer = ""
        self.reasoning_buffer = ""
        self._in_think_tag = False
        self._pending_tag_buffer = ""
    def add_chunk(self, content: str) -> Tuple[str, str]:
        if not content:
            return "", ""
        text = self._pending_tag_buffer + content
        self._pending_tag_buffer = ""
        content_parts = []
        reasoning_parts = []
        i = 0
        while i < len(text):
            if self._in_think_tag:
                end_pos, end_len = self._find_tag(text, i, self.THINK_END_PATTERNS)
                if end_pos >= 0:
                    reasoning_parts.append(text[i:end_pos])
                    i = end_pos + end_len
                    self._in_think_tag = False
                else:
                    safe_end = self._get_safe_end(text, i)
                    if safe_end > i:
                        reasoning_parts.append(text[i:safe_end])
                    if safe_end < len(text):
                        self._pending_tag_buffer = text[safe_end:]
                    break
            else:
                start_pos, start_len = self._find_tag(text, i, self.THINK_START_PATTERNS)
                if start_pos >= 0:
                    if start_pos > i:
                        content_parts.append(text[i:start_pos])
                    i = start_pos + start_len
                    self._in_think_tag = True
                else:
                    safe_end = self._get_safe_end(text, i)
                    if safe_end > i:
                        content_parts.append(text[i:safe_end])
                    if safe_end < len(text):
                        self._pending_tag_buffer = text[safe_end:]
                    break
        return "".join(content_parts), "".join(reasoning_parts)
    def _find_tag(self, text: str, start: int, patterns: list) -> Tuple[int, int]:
        min_pos = -1
        tag_len = 0
        for pattern in patterns:
            pos = text.find(pattern, start)
            if pos >= 0 and (min_pos < 0 or pos < min_pos):
                min_pos = pos
                tag_len = len(pattern)
        return min_pos, tag_len
    def _get_safe_end(self, text: str, start: int) -> int:
        max_tag_len = 10
        if len(text) - start <= max_tag_len:
            for j in range(start, len(text)):
                if text[j] in '<`':
                    return j
            return len(text)
        check_start = max(start, len(text) - max_tag_len)
        for j in range(check_start, len(text)):
            if text[j] in '<`':
                return j
        return len(text)
    def flush_pending(self) -> Tuple[str, str]:
        pending = self._pending_tag_buffer
        self._pending_tag_buffer = ""
        if not pending:
            return "", ""
        if self._in_think_tag:
            return "", pending
        else:
            return pending, ""
    async def flush_content(self, force: bool = False) -> AsyncGenerator[str, None]:
        if not self.content_buffer:
            return
        buffer_len = len(self.content_buffer)
        chunk_size = get_content_chunk_size()
        if force or buffer_len >= chunk_size:
            chunks_to_send = buffer_len // chunk_size
            if chunks_to_send > 0:
                for i in range(chunks_to_send):
                    start = i * chunk_size
                    end = start + chunk_size
                    chunk = self.content_buffer[start:end]
                    yield send_sse_data({'content': chunk, 'reasoning_content': ''})
                self.content_buffer = self.content_buffer[chunks_to_send * chunk_size:]
            elif force:
                yield send_sse_data({'content': self.content_buffer, 'reasoning_content': ''})
                self.content_buffer = ""
    async def flush_reasoning(self, force: bool = False) -> AsyncGenerator[str, None]:
        if not self.reasoning_buffer:
            return
        buffer_len = len(self.reasoning_buffer)
        if force or buffer_len >= REASONING_CHUNK_SIZE:
            chunks_to_send = buffer_len // REASONING_CHUNK_SIZE
            if chunks_to_send > 0:
                for i in range(chunks_to_send):
                    start = i * REASONING_CHUNK_SIZE
                    end = start + REASONING_CHUNK_SIZE
                    chunk = self.reasoning_buffer[start:end]
                    yield send_sse_data({'content': '', 'reasoning_content': chunk})
                self.reasoning_buffer = self.reasoning_buffer[chunks_to_send * REASONING_CHUNK_SIZE:]
            elif force:
                yield send_sse_data({'content': '', 'reasoning_content': self.reasoning_buffer})
                self.reasoning_buffer = ""