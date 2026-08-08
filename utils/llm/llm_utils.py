import time
import random
from typing import Dict
from langchain_core.messages import BaseMessage
from loguru import logger
from utils.message import extract_reasoning_from_content
def generate_trace_id() -> str:
    ts = str(int(time.time() * 1000))
    rand_part = ''.join([str(random.randint(0, 9)) for _ in range(32 - len(ts))])
    return ts + rand_part
def build_dynamic_headers() -> Dict[str, str]:
    from utils.config import get_config
    request_headers_config = get_config('llm.default.request_headers', {})
    if not request_headers_config.get('enabled', False):
        return {}
    headers = {
        'globalBusiTrackNo': generate_trace_id(),
        'sendSysOrCmptNo': request_headers_config.get('send_sys_or_cmpt_no', '99714490000'),
        'startSysOrCmptNo': request_headers_config.get('start_sys_or_cmpt_no', '99714490000'),
        'sceneId': request_headers_config.get('scene_id', '0060'),
    }
    logger.debug(f"[Headers] trace={headers['globalBusiTrackNo']}")
    return headers
async def call_llm(model, messages: list[BaseMessage], **kwargs):
    headers = build_dynamic_headers()
    if hasattr(model, 'default_headers'):
        try:
            model = model.model_copy(update={"default_headers": headers})
        except Exception:
            logger.warning("[call_llm] model_copy  headers ")
    response = await model.ainvoke(messages, **kwargs)
    content = response.content if hasattr(response, 'content') else str(response)
    _, cleaned_content = extract_reasoning_from_content(content)
    return response.model_copy(update={"content": cleaned_content})
def wrap_llm_with_headers(model):
    return _DynamicHeadersModelProxy(model)
class _DynamicHeadersModelProxy:
    def __init__(self, model):
        self._model = model
    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self._model, name)
    async def ainvoke(self, *args, **kwargs):
        headers = build_dynamic_headers()
        if hasattr(self._model, 'default_headers'):
            try:
                new_model = self._model.model_copy(update={"default_headers": headers})
                return await new_model.ainvoke(*args, **kwargs)
            except Exception:
                logger.warning("[wrap_llm] model_copy  headers ")
        return await self._model.ainvoke(*args, **kwargs)
    async def astream(self, *args, **kwargs):
        headers = build_dynamic_headers()
        if hasattr(self._model, 'default_headers'):
            try:
                new_model = self._model.model_copy(update={"default_headers": headers})
                async for chunk in new_model.astream(*args, **kwargs):
                    yield chunk
                return
            except Exception:
                logger.warning("[wrap_llm] model_copy  headers ")
        async for chunk in self._model.astream(*args, **kwargs):
            yield chunk