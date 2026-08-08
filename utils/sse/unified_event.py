"""统一 SSE 事件构建器（B-3）。

统一 chat stream + dispatch 的 SSE 事件 schema：
{type, task_id?, content?, reasoning_content?, agent?, done?}

前端兼容：新字段（done/agent/reasoning_content）可选，前端忽略不消费的字段不破坏。
None 字段不出现（避免前端收到 null）。

P2-2: send_sse_data / _send_execution_event 作为 SSE 格式化的唯一真相源放在此
（utils 层），消除 executor 层对 api 层的反向依赖，以及 executor/stream_helper
与 api/chat/sse_utils 的双份实现。
"""

import json
import datetime


def send_sse_data(data: dict) -> str:
    """SSE 格式化：data -> "data: {json}\\n\\n"。

    default=str 处理 datetime 等非原生 JSON 类型，避免 TypeError。
    """
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _send_execution_event(event_type: str, metadata: dict, data: dict) -> str:
    """构建 execution_event SSE（执行面板 tool/llm 事件）。"""
    ts = metadata.get('timestamp') or datetime.datetime.now().isoformat()
    return send_sse_data({
        'execution_event': {
            'event_type': event_type,
            'timestamp': ts,
            'run_id': metadata.get('run_id'),
            'parent_run_id': metadata.get('parent_id'),
            'data': data
        }
    })


def build_sse_event(
    event_type: str,
    task_id: str = None,
    content: str = None,
    reasoning_content: str = None,
    agent: str = None,
    done: bool = None,
    **extra,
) -> dict:
    """构建统一 SSE 事件 dict。

    Args:
        event_type: 事件类型（task_started/content_chunk/task_completed/task_failed/error 等）
        task_id: 关联的 task id（多 agent 调度用，chat stream 可省略）
        content: 内容（content_chunk 的文本）
        reasoning_content: 推理内容（thinking）
        agent: 关联的 agent name
        done: 是否终结事件（task_completed/task_failed 时 true）
        **extra: 额外字段（透传）

    Returns:
        统一 SSE 事件 dict，None 字段不出现。
    """
    event = {"type": event_type}
    if task_id is not None:
        event["task_id"] = task_id
    if content is not None:
        event["content"] = content
    if reasoning_content is not None:
        event["reasoning_content"] = reasoning_content
    if agent is not None:
        event["agent"] = agent
    if done is not None:
        event["done"] = done
    event.update(extra)
    return event
