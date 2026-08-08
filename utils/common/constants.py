from ..config.config_loader import get_config

# ─── 静态常量（不来自配置文件，无需热重载） ───
REASONING_CHUNK_SIZE = 5
FALLBACK_REASONING_CHUNK_SIZE = 50
FALLBACK_CONTENT_CHUNK_SIZE = 10
DEFAULT_RECURSION_LIMIT = 50
DEFAULT_SESSION_ID = "default"
DEFAULT_USER_ID = "guest"
DEFAULT_DEBUG = True

# ─── 配置派生常量（导入时的初始快照，向后兼容） ───
# 优先使用下方 getter 函数，支持热重载；直接 import 常量无法热刷新
CONTENT_CHUNK_SIZE = int(get_config('stream.content_chunk_size', 32))
HEARTBEAT_INTERVAL_SECONDS = int(get_config('stream.heartbeat_interval_seconds', 15))
EVENT_QUEUE_MAX_SIZE = int(get_config('events.queue_max_size', 1000))


def get_content_chunk_size() -> int:
    """流式内容分块大小（每次调用读最新 config，支持热重载）。"""
    return int(get_config('stream.content_chunk_size', 32))


def get_heartbeat_interval() -> int:
    """心跳间隔秒数（每次调用读最新 config，支持热重载）。"""
    return int(get_config('stream.heartbeat_interval_seconds', 15))


def get_event_queue_max_size() -> int:
    """事件队列上限（每次调用读最新 config，支持热重载）。"""
    return int(get_config('events.queue_max_size', 1000))
