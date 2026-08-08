"""Embedding 模型工厂 — 从 memory/storage.py 和 hybrid_search.py 抽取

消除 33 行逐字复制的 embedding 初始化逻辑。
模块级缓存 _EMBEDDING_MODEL：避免每个 HybridMemorySearch/VectorStorage 实例重复加载模型，
配合 warmup_embedding() 实现冷启动预热。
"""
from typing import Any
from loguru import logger
import threading

_EMBEDDING_MODEL: Any = None
_EMBEDDING_LOCK = threading.Lock()


def create_embedding_model(log_tag: str = "Embedding") -> Any:
    """从 config 创建 embedding 模型（openai/huggingface）。

    模块级缓存：首次加载后复用，避免每实例重复加载（bge 等本地模型加载慢）。
    读取 config/agent_config.json 的 embedding 段配置。
    失败时按 OpenAI → HuggingFace → RuntimeError 降级。
    """
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL
    with _EMBEDDING_LOCK:
        if _EMBEDDING_MODEL is not None:
            return _EMBEDDING_MODEL
        model = _build_embedding_model(log_tag)
        _EMBEDDING_MODEL = model
        return model


def reset_embedding_model() -> None:
    """重置 embedding 模型单例（热重载时调用）。

    清空 _EMBEDDING_MODEL 后，下次 create_embedding_model() 会从最新 config 重建模型。
    """
    global _EMBEDDING_MODEL
    _EMBEDDING_MODEL = None
    logger.debug("[EmbeddingFactory] 单例已重置，下次调用将重建模型")


async def warmup_embedding() -> Any:
    """冷启动预热：后台加载 embedding 模型到模块缓存。

    供 MemoryManager.initialize() 或应用启动时调用（建议 asyncio.create_task 后台执行，
    不阻塞首次问答）。
    """
    return create_embedding_model("[Warmup]")


def _build_embedding_model(log_tag: str) -> Any:
    from utils.config import get_config
    provider = get_config('embedding.provider', 'openai')
    model_name = get_config('embedding.model', 'text-embedding-3-small')
    try:
        if provider == 'openai':
            from langchain_openai import OpenAIEmbeddings
            api_key = get_config('embedding.api_key') or get_config('llm.default.api_key')
            base_url = get_config('embedding.base_url') or get_config('llm.default.base_url')
            model = OpenAIEmbeddings(
                model=model_name,
                openai_api_key=api_key,
                openai_api_base=base_url,
                check_embedding_ctx_length=False,
            )
            logger.debug(f"[{log_tag}] OpenAI Embeddings: {model_name}")
            return model
        elif provider == 'ollama':
            from langchain_ollama import OllamaEmbeddings
            base_url = get_config('embedding.base_url', 'http://127.0.0.1:11434')
            model = OllamaEmbeddings(model=model_name, base_url=base_url)
            logger.debug(f"[{log_tag}] Ollama Embeddings: {model_name} @ {base_url}")
            return model
        elif provider == 'local':
            from langchain_huggingface import HuggingFaceEmbeddings
            model = HuggingFaceEmbeddings(model_name=model_name)
            logger.debug(f"[{log_tag}] Local Embeddings: {model_name}")
            return model
        elif provider == 'huggingface':
            try:
                from langchain_huggingface import HuggingFaceEmbeddings
                model = HuggingFaceEmbeddings(model_name=model_name)
                logger.debug(f"[{log_tag}] HuggingFace Embeddings: {model_name}")
                return model
            except ImportError:
                logger.warning(f"[{log_tag}] langchain-huggingface not available, fallback to OpenAI")
                from langchain_openai import OpenAIEmbeddings
                return OpenAIEmbeddings()
        else:
            from langchain_openai import OpenAIEmbeddings
            return OpenAIEmbeddings()
    except Exception as e:
        logger.warning(f"[{log_tag}] embedding init failed: {e}")
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
            model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
            logger.info(f"[{log_tag}] fallback to HuggingFace default")
            return model
        except Exception as e2:
            logger.error(f"[{log_tag}] all embedding init failed: {e2}")
            raise RuntimeError(f"embedding init failed: {e2}")
