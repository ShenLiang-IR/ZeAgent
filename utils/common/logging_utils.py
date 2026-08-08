import json
import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from loguru import logger
from ..config.config_loader import get_config_loader
_logging_configured = False
_logging_config_cache = None
_SENSITIVE_FIELD_KEYWORDS = (
    'api_key',
    'apikey',
    'token',
    'secret',
    'password',
    'authorization',
    'cookie',
    'session',
    'credential'
)
def _get_log_level(level_str: str) -> str:
    level_map = {
        'DEBUG': 'DEBUG',
        'INFO': 'INFO',
        'WARNING': 'WARNING',
        'ERROR': 'ERROR',
        'CRITICAL': 'CRITICAL'
    }
    return level_map.get(level_str.upper(), 'INFO')
def _get_stdlib_log_level(level_str: Optional[str]) -> int:
    if not level_str:
        return logging.INFO
    name = str(level_str).upper().strip()
    level = logging.getLevelName(name)
    return level if isinstance(level, int) else logging.INFO
def _configure_stdlib_logging(config: Optional[Dict[str, Any]] = None) -> None:
    if config is None:
        config = {}
    console_config = config.get('console', {}) if isinstance(config, dict) else {}
    enabled = console_config.get('enabled', True)
    level_str = console_config.get('level', 'INFO')
    level = _get_stdlib_log_level(level_str)
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    if not enabled:
        root.setLevel(logging.WARNING)
        logging.captureWarnings(True)
        return
    fmt = console_config.get('format') or "%(asctime)s | %(name)-30s | %(levelname)-8s | %(message)s"
    if isinstance(fmt, str) and '{' in fmt:
        fmt = "%(asctime)s | %(name)-30s | %(levelname)-8s | %(message)s"
    datefmt = console_config.get('date_format') or "%H:%M:%S"
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    root.addHandler(handler)
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).setLevel(level)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpcore._http11").setLevel(logging.WARNING)
    logging.getLogger("httpcore._h11").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)  # rust notify timeout 心跳太吵
    logging.captureWarnings(True)
def _load_logging_config() -> Dict[str, Any]:
    global _logging_config_cache
    if _logging_config_cache is not None:
        return _logging_config_cache
    try:
        config_loader = get_config_loader()
        logging_config = config_loader.get_section('logging')
        if not logging_config:
            print("[]  logging ")
            logging_config = {}
    except Exception as e:
        print(f"[] : {e}")
        logging_config = {}
    _logging_config_cache = logging_config
    return logging_config


def reset_logging_cache() -> None:
    """重置 logging 配置缓存（热重载时调用）。

    清空 _logging_config_cache 和 _logging_configured，
    下次 setup_agent_logging() 会从最新 config 重建日志配置。
    """
    global _logging_config_cache, _logging_configured
    _logging_config_cache = None
    _logging_configured = False


def _get_json_sink_config(config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """解析 logging.json 段，返回 JSON sink 配置（enabled=false/缺省 → None）。

    生产配 logging.json.enabled=true 开启结构化日志（loguru serialize=True，ELK/Loki 友好）；
    开发默认缺省 → None（文本日志，向下兼容）。
    """
    if not config:
        return None
    json_config = config.get('json', {})
    if not json_config or not json_config.get('enabled', False):
        return None
    return {
        'filename': json_config.get('filename', 'agent_structured.log'),
        'level': _get_log_level(json_config.get('level', 'INFO')),
    }


def _configure_loguru_handlers(log_dir: Path, config: Optional[Dict[str, Any]] = None):
    if config is None:
        config = {}
    console_config = config.get('console', {})
    file_config = config.get('file', {})
    logger.remove()
    # A7-II：patcher 设默认 trace_id（trace_context 未设置时为空），使 {extra[trace_id]} 始终可解析
    logger.configure(patcher=lambda record: record["extra"].setdefault("trace_id", ""))
    if console_config.get('enabled', True):
        console_level = _get_log_level(console_config.get('level', 'INFO'))
        console_format = console_config.get(
            'format',
            '<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>'
        )
        if isinstance(console_format, str) and '%(' in console_format:
            console_format = '<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>'
        # A7-II：追加 trace_id（非空时显示，空则显示空，便于全链路关联）
        console_format = console_format + ' | tid={extra[trace_id]}'
        logger.add(
            sys.stdout,
            level=console_level,
            format=console_format,
            colorize=True
        )
    if file_config.get('enabled', False):
        log_dir.mkdir(exist_ok=True)
        filename = file_config.get('filename', 'agent_execution.log')
        log_file_path = log_dir / filename
        file_level = _get_log_level(file_config.get('level', 'DEBUG'))
        file_format = file_config.get(
            'format',
            '{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name} - {message}'
        )
        if isinstance(file_format, str) and '%(' in file_format:
            file_format = '{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name} - {message}'
        file_format = file_format + ' | tid={extra[trace_id]}'
        max_bytes = file_config.get('max_bytes', 10 * 1024 * 1024)
        backup_count = file_config.get('backup_count', 5)
        if max_bytes >= 1024 * 1024 * 1024:
            size_str = f"{max_bytes // (1024 * 1024 * 1024)} GB"
        elif max_bytes >= 1024 * 1024:
            size_str = f"{max_bytes // (1024 * 1024)} MB"
        else:
            size_str = f"{max_bytes // 1024} KB"
        logger.add(
            str(log_file_path),
            level=file_level,
            format=file_format,
            rotation=size_str,
            retention=backup_count,
            encoding='utf-8'
        )
    # 结构化日志（JSON）：logging.json.enabled=true 时开启，生产用 ELK/Loki 友好
    json_config = _get_json_sink_config(config)
    if json_config:
        json_log_path = log_dir / json_config['filename']
        logger.add(
            str(json_log_path),
            level=json_config['level'],
            serialize=True,  # loguru 内置 JSON 序列化（含 record + extra[trace_id]）
            rotation="100 MB",
            retention=10,
            encoding='utf-8'
        )
def setup_agent_logging():
    global _logging_configured
    if _logging_configured:
        return
    import os
    logging_config = _load_logging_config()
    # 日志目录优先用 LOG_DIR 环境变量（容器化部署推荐显式指定）
    # 没设则 fallback 到项目根 logs/（向下兼容本地开发）
    log_dir_env = os.getenv("LOG_DIR")
    if log_dir_env:
        log_dir = Path(log_dir_env)
    else:
        # 项目根 = utils/common/logging_utils.py 的 5 层父级
        log_dir = Path(__file__).parent.parent.parent.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _configure_loguru_handlers(log_dir, logging_config)
    _configure_stdlib_logging(logging_config)
    _logging_configured = True
    console_level = logging_config.get('console', {}).get('level', 'INFO')
    file_enabled = logging_config.get('file', {}).get('enabled', False)
    file_level = logging_config.get('file', {}).get('level', 'DEBUG') if file_enabled else 'DISABLED'
    if file_enabled:
        print(f"[] Agent : ({console_level}) + ({file_level})")
    else:
        print(f"[] Agent : ({console_level})")
def get_performance_logging_config() -> Dict[str, bool]:
    logging_config = _load_logging_config()
    perf_config = logging_config.get('performance', {})
    result = {
        'enabled': perf_config.get('enabled', True)
    }
    return result
def should_log_tool_io_details() -> bool:
    logging_config = _load_logging_config()
    detailed = logging_config.get('detailed_logging', {})
    return detailed.get('enabled', True) and bool(detailed.get('log_tool_calls', False))
def should_log_llm_io_details() -> bool:
    logging_config = _load_logging_config()
    detailed = logging_config.get('detailed_logging', {})
    return detailed.get('enabled', True) and bool(detailed.get('log_llm_calls', False))
def sanitize_for_logging(data: Any, max_depth: int = 4):
    if max_depth <= 0:
        return '...'
    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            if isinstance(key, str) and any(s in key.lower() for s in _SENSITIVE_FIELD_KEYWORDS):
                sanitized[key] = "***"
            else:
                sanitized[key] = sanitize_for_logging(value, max_depth - 1)
        return sanitized
    if isinstance(data, list):
        return [sanitize_for_logging(item, max_depth - 1) for item in data]
    if isinstance(data, tuple):
        return tuple(sanitize_for_logging(item, max_depth - 1) for item in data)
    if isinstance(data, set):
        return [sanitize_for_logging(item, max_depth - 1) for item in data]
    if isinstance(data, str):
        return data if len(data) <= 2000 else f"{data[:2000]}...(truncated)"
    return data
def format_log_payload(data: Any, max_chars: int = 2000) -> str:
    sanitized = sanitize_for_logging(data)
    try:
        text = json.dumps(sanitized, ensure_ascii=False, default=str)
    except TypeError:
        text = str(sanitized)
    if len(text) > max_chars:
        return f"{text[:max_chars]}...(total {len(text)} chars)"
    return text
def get_agent_logger():
    setup_agent_logging()
    return logger.bind(name="agent.callback")