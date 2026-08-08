"""langfuse CallbackHandler 工厂。

读 config 创建 langfuse CallbackHandler；enabled=false/import 失败/key 缺失时返回 None（降级，不阻断主流程）。
单例缓存，避免每次 astream 重建 handler。
"""
from __future__ import annotations
from typing import Any, Optional
from loguru import logger
from utils.config.langfuse_config import get_langfuse_config


class LangfuseHandlerFactory:
    """langfuse CallbackHandler 工厂（单例缓存）。"""

    _handler: Optional[Any] = None
    _initialized: bool = False

    @classmethod
    def create(cls) -> Optional[Any]:
        """返回 langfuse CallbackHandler 实例，或 None（降级）。

        enabled=false / langfuse 未装 / key 缺失 → None。
        单例：首次调用后缓存，后续返回同一实例。
        """
        if cls._initialized:
            return cls._handler
        cls._initialized = True
        try:
            lf_config = get_langfuse_config()
            enabled = lf_config.get("enabled", False)
            if not enabled:
                logger.info("[Langfuse] observability.langfuse.enabled=false，跳过 tracing")
                return None
            public_key = lf_config.get("public_key", "")
            secret_key = lf_config.get("secret_key", "")
            host = lf_config.get("host", "")
            if not (public_key and secret_key and host):
                logger.warning("[Langfuse] 配置不完整（public_key/secret_key/host 缺失），跳过 tracing")
                return None
            # langfuse 4.x: 先创建 Langfuse 客户端实例（注册到全局），CallbackHandler 自动关联
            from langfuse import Langfuse
            from langfuse.langchain import CallbackHandler
            Langfuse(public_key=public_key, secret_key=secret_key, host=host)
            cls._handler = CallbackHandler(public_key=public_key)
            logger.info(f"[Langfuse] handler 已创建，host={host}")
        except ImportError:
            logger.warning("[Langfuse] langfuse 未安装，跳过 tracing")
            return None
        except Exception as e:
            logger.warning(f"[Langfuse] handler 创建失败: {type(e).__name__}: {e}，跳过 tracing")
            return None
        return cls._handler

    @classmethod
    def reset(cls):
        """测试用：重置单例缓存。"""
        cls._handler = None
        cls._initialized = False


def attach_callbacks(config: dict, session_id: str = None, user_id: str = None) -> dict:
    """向 config 注入 langfuse callbacks（handler 非 None 时）。

    不改原 config dict（返回新 dict）。
    handler 为 None 时原样返回 config（零影响）。
    session_id/user_id 通过 config.metadata 关联到 langfuse trace。
    """
    handler = LangfuseHandlerFactory.create()
    if handler is None:
        return config
    new_config = dict(config)
    existing = new_config.get("callbacks", [])
    new_config["callbacks"] = [*existing, handler]
    # langfuse 4.x CallbackHandler 从 metadata 的 langfuse_session_id/langfuse_user_id 读取
    if session_id or user_id:
        metadata = dict(new_config.get("metadata") or {})
        if session_id:
            metadata["langfuse_session_id"] = session_id
        if user_id:
            metadata["langfuse_user_id"] = user_id
        new_config["metadata"] = metadata
    return new_config
