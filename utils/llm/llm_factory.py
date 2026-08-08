import uuid
from typing import Optional, Dict, Union, Any
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from loguru import logger
def _llm_cache_key(base_url: str, model_name: str, provider: Optional[str]) -> str:
    return f"llm_instance_{base_url}_{model_name}_{provider or 'default'}"
def _get_llm_cache():
    from utils.common.cache import get_query_cache
    return get_query_cache()
def _build_business_headers(headers: Dict[str, str]) -> Dict[str, str]:
    from loguru import logger
    from utils.config import get_config
    request_headers_config = get_config('llm.default.request_headers', {})
    if not request_headers_config.get('enabled', False):
        logger.debug("[]  (request_headers.enabled=false)")
        return headers
    result_headers = dict(headers) if headers else {}
    result_headers.update({
        'globalBusiTrackNo': uuid.uuid4().hex,
        'sendSysOrCmptNo': request_headers_config.get('send_sys_or_cmpt_no', '99714490000'),
        'startSysOrCmptNo': request_headers_config.get('start_sys_or_cmpt_no', '99714490000'),
        'sceneId': request_headers_config.get('scene_id', '0060'),
    })
    logger.info(f"[] LLM: globalBusiTrackNo={result_headers['globalBusiTrackNo']}, "
                f"sendSysOrCmptNo={result_headers['sendSysOrCmptNo']}, "
                f"startSysOrCmptNo={result_headers['startSysOrCmptNo']}, "
                f"sceneId={result_headers['sceneId']}")
    return result_headers
def is_ollama_provider(provider: Optional[str] = None) -> bool:
    if provider:
        return provider.lower() == 'ollama'
    return False
def create_llm_model(
    base_url: str,
    model_name: str,
    api_key: Optional[str],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    provider: Optional[str] = None,
    default_headers: Optional[Dict[str, str]] = None,
    enable_thinking: Optional[bool] = None,
    parallel_tool_calls: Optional[bool] = None
) -> Union[ChatOpenAI, ChatOllama]:
    cache = _get_llm_cache()
    cache_key = _llm_cache_key(base_url, model_name, provider)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    is_ollama = is_ollama_provider(provider)
    headers = default_headers or {}
    headers = _build_business_headers(headers)
    if is_ollama:
        use_openai_compatible = base_url and '/v1' in base_url
        actual_model = model_name
        model_kwargs = {
            "temperature": temperature
        }
        if max_tokens:
            if use_openai_compatible:
                model_kwargs["max_tokens"] = max_tokens
            else:
                model_kwargs["num_predict"] = max_tokens
        if use_openai_compatible:
            extra_body = {}
            if enable_thinking is not None:
                extra_body["enable_thinking"] = enable_thinking
            if parallel_tool_calls is not None:
                model_kwargs["parallel_tool_calls"] = parallel_tool_calls
            llm = ChatOpenAI(
                model=actual_model,
                base_url=base_url,
                api_key=api_key or "ollama",
                default_headers=headers if headers else None,
                streaming=True,
                extra_body=extra_body if extra_body else None,
                **model_kwargs
            )
        else:
            llm = ChatOllama(
                model=actual_model,
                **model_kwargs
            )
    else:
        model_kwargs = {
            "temperature": temperature
        }
        if max_tokens:
            model_kwargs["max_tokens"] = max_tokens
        if parallel_tool_calls is not None:
            model_kwargs["parallel_tool_calls"] = parallel_tool_calls
        extra_body = {}
        if enable_thinking is not None:
            extra_body["enable_thinking"] = enable_thinking
        llm = ChatOpenAI(
            model=model_name,
            base_url=base_url,
            api_key=api_key,
            default_headers=headers if headers else None,
            streaming=True,
            extra_body=extra_body if extra_body else None,
            **model_kwargs
        )
    cache.set(cache_key, llm)
    return llm
def get_default_llm_config() -> Dict[str, Any]:
    from utils.config import get_config
    return {
        'base_url': get_config('llm.default.base_url'),
        'model_name': get_config('llm.default.model'),
        'api_key': get_config('llm.default.api_key'),
        'temperature': get_config('llm.default.temperature', 0.7),
        'max_tokens': get_config('llm.default.max_tokens'),
        'provider': get_config('llm.default.provider'),
        'default_headers': get_config('llm.default.headers', {}),
        'enable_thinking': get_config('llm.default.enable_thinking'),
        'parallel_tool_calls': get_config('llm.default.parallel_tool_calls', True),
        'request_headers': get_config('llm.default.request_headers', {}),
    }
def get_default_llm(
    from_db: bool = False,
    model_type: Optional[str] = None
) -> Union[ChatOpenAI, ChatOllama]:
    if from_db and not model_type:
        raise ValueError(" `from_db`  True `model_type`")
    if not from_db and model_type:
        raise ValueError(" `model_type` `from_db`  True")
    config = get_default_llm_config()
    if from_db:
        from infrastructure.database.repositories import SysModelResMgmtRepository
        repo = SysModelResMgmtRepository()
        logger.info(f"[get_default_llm] : model_type={model_type}")
        db_models = repo.get_by_model_type(model_tp_cls=model_type, return_dict=True)
        if db_models:
            logger.info(f"[get_default_llm] : {db_models[0].get('model_name')}")
            return create_llm_from_db_config(db_models[0])
    headers = config.get('default_headers', {})
    has_auth_in_headers = headers and 'Authorization' in headers
    effective_api_key = None if has_auth_in_headers else config.get('api_key')
    return create_llm_model(
        base_url=config['base_url'],
        model_name=config['model_name'],
        api_key=effective_api_key,
        temperature=config.get('temperature', 0.7),
        max_tokens=config.get('max_tokens'),
        provider=config.get('provider'),
        default_headers=headers if isinstance(headers, dict) else None,
        enable_thinking=config.get('enable_thinking'),
        parallel_tool_calls=config.get('parallel_tool_calls')
    )
def create_llm_from_db_config(db_config: Dict[str, Any]) -> Union[ChatOpenAI, ChatOllama]:
    extra_config = db_config.get('extra_config', {})
    logger.info(f"[create_llm_from_db_config] LLM: "
                f"model={db_config.get('model_name')}, "
                f"base_url={db_config.get('base_url')}")
    # DB 路径 api_key 解密：sgnt_pwfatt_info 字段可能存 enc: 密文，明文原样返回（向下兼容）
    from utils.crypto.secret_store import decrypt_secret
    raw_api_key = db_config.get('api_key')
    decrypted_api_key = decrypt_secret(raw_api_key) if raw_api_key else raw_api_key
    return create_llm_model(
        base_url=db_config.get('base_url'),
        model_name=db_config.get('model_name'),
        api_key=decrypted_api_key,
        temperature=db_config.get('temperature', 0.7),
        max_tokens=db_config.get('max_tokens'),
        provider=extra_config.get('provider'),
        default_headers=extra_config.get('default_headers'),
        enable_thinking=extra_config.get('enable_thinking'),
        parallel_tool_calls=extra_config.get('parallel_tool_calls'),
    )
def resolve_llm_by_model_id(subagent_config: Dict[str, Any], default_llm: Any) -> Any:
    from utils.config import get_config_db
    model_id = subagent_config.get('model_id') if subagent_config else None
    if not model_id:
        return default_llm
    try:
        config_db = get_config_db()
        db_model_config = config_db.model_res.get_available_model_by_id(model_id)
        if db_model_config:
            agent_name = subagent_config.get('agent_name', 'unknown')
            logger.info(f"[resolve_llm_by_model_id] : "
                        f"{db_model_config.get('model_name')} (model_id={model_id}, agent={agent_name})")
            return create_llm_from_db_config(db_model_config)
        else:
            logger.warning(f"[resolve_llm_by_model_id] : "
                           f"model_id={model_id}, ")
    except Exception as e:
        logger.error(f"[resolve_llm_by_model_id] : "
                     f"model_id={model_id}, : {e}")
    return default_llm