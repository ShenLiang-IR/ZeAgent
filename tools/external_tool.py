import json
import httpx
from loguru import logger
from typing import Any, Dict, Optional, List
from langchain_core.tools import tool, ToolException, StructuredTool
from pydantic import Field, create_model
from utils.config import get_config_db
from utils.common.logging_utils import should_log_tool_io_details, format_log_payload
PARAM_TYPE_LABELS = {
    'string':        '',
    'number':        '',
    'boolean':       '',
    'array':         '',
    'array-string':  '',
    'array-number':  '',
    'object':        '',
    'array-object':  '',
}
PARAM_TYPE_TO_PYTHON = {
    'string': str,
    'number': float,
    'boolean': bool,
    'array': list,
    'array-string': list,
    'array-number': list,
    'object': dict,
    'array-object': list,
}
from .registry import format_tool_description
from infrastructure.reranking import RerankingProcessor
_current_authorization: Optional[str] = None
_logged_tools: set = set()
def set_current_authorization(auth: Optional[str] = None):
    global _current_authorization
    _current_authorization = auth
def get_current_authorization() -> Optional[str]:
    global _current_authorization
    return _current_authorization
class ExternalTool:
    def __init__(self, config: Dict[str, Any]):
        self.name = config.get('name')
        self.display_name = config.get('display_name', '')
        self.description = config.get('description', '')
        self.return_description = config.get('return_description', '')
        self.examples = config.get('examples', [])
        api_base_url = config.get('api_base_url', '').strip()
        headers = config.get('headers', {})
        config_data = config.get('config', {})
        if isinstance(config_data, dict) and not api_base_url:
            api_base_url = config_data.get('api_base_url', '').strip()
            endpoint = config_data.get('api_endpoint', '').strip()
            if not api_base_url:
                full_url = config_data.get('url', '').strip()
                if full_url:
                    api_base_url = full_url
                    logger.debug(
                        f"[URL] {self.name} -  config.url URL: {full_url}"
                    )
        if not api_base_url:
            http_config_name = config.get('http_config_name')
            if http_config_name:
                try:
                    config_db = get_config_db()
                    http_config = config_db.http_configs.get_by_name(http_config_name)
                    if http_config:
                        api_base_url = http_config.get('api_base_url', '').strip()
                        if not headers:
                            headers = http_config.get('headers', {})
                        logger.debug(
                            f"[] {self.name} - HTTP '{http_config_name}' api_base_url: {api_base_url}"
                        )
                    else:
                        logger.warning(
                            f"[] {self.name} - HTTP: {http_config_name}"
                        )
                except Exception as e:
                    logger.warning(
                        f"[] {self.name} - HTTP: {str(e)}"
                    )
        endpoint = config.get('api_endpoint', '') or config.get('config', {}).get('api_endpoint', '')
        endpoint = endpoint.lstrip('/')
        if api_base_url:
            parts = api_base_url.rstrip('/').split('/')
            if len(parts) > 3:
                if endpoint:
                    logger.warning(
                        f"[] {self.name} - "
                        f"api_base_url '{api_base_url}'"
                        f" endpoint='{endpoint}' endpoint "
                    )
                endpoint = ''
        base_path_count = api_base_url.rstrip('/').count('/') - 2
        has_full_url = base_path_count >= 1 and not endpoint
        if has_full_url:
            self.api_base_url = api_base_url.rstrip('/')
            self.api_endpoint = ''
        else:
            self.api_base_url = api_base_url.rstrip('/')
            self.api_endpoint = endpoint
        method = config.get('method') or config.get('config', {}).get('method', 'POST')
        self.method = str(method).upper()
        self.headers = headers
        self.enabled = config.get('enabled', True)
        self.api_parameters = {}
        config_data = config.get('config', {})
        if isinstance(config_data, dict):
            self.api_parameters = config_data.get('parameters', {})
        self.enable_reranking = config.get('enable_reranking', False)
        self.reranking_config = config.get('reranking_config')
        self.reranking_processor = None
        if self.enable_reranking and self.reranking_config:
            try:
                self.reranking_processor = RerankingProcessor(self.reranking_config)
            except Exception as e:
                logger.warning(f"[] {self.name} -  reranking : {str(e)}")
        self.parameter_list = config.get('parameter_list', [])
        self.header_params_from_db = {}
        if not self.name:
            raise ValueError("")
        if not self.api_base_url:
            raise ValueError("API")
        if not self.api_endpoint:
            raise ValueError("API")
        if not self.parameter_list:
            try:
                config_db = get_config_db()
                # 按工具名（intfc_name）查参数；旧代码传 config['id']（pr_key_id）与
                # get_tool_parameters 签名不匹配，已统一为按名查询
                if self.name:
                    params_result = config_db.external_tools.get_tool_parameters(self.name)
                    if isinstance(params_result, dict):
                        self.parameter_list = params_result.get('body_params', [])
                        self.header_params_from_db = params_result.get('header_params', {})
                    else:
                        self.parameter_list = params_result if params_result else []
            except Exception as e:
                logger.debug(f"[] {self.name} - : {str(e)}")
                self.parameter_list = []
                self.header_params_from_db = {}
        merged_headers = {**self.headers, **self.header_params_from_db}
        self.headers = merged_headers
        param_descriptions_for_llm = {}
        if self.parameter_list:
            for param in self.parameter_list:
                param_name = param.get('param_name')
                param_desc = param.get('description', '')
                required = param.get('required', False)
                param_type = (param.get('param_type') or 'string').lower().strip()
                if param_name:
                    type_label = PARAM_TYPE_LABELS.get(param_type, param_type)
                    required_label = "" if required else ""
                    param_descriptions_for_llm[param_name] = f"{param_desc} [{type_label}, {required_label}]"
        if self.description:
            desc_prefix = f"{self.display_name}" if self.display_name else ""
            self.formatted_description = format_tool_description(
                description=desc_prefix + self.description,
                parameter_descriptions=None,
                return_description=self.return_description,
                examples=self.examples,
                dependencies=None
            )
        else:
            self.formatted_description = self.description
        global _logged_tools
        if self.name not in _logged_tools:
            _logged_tools.add(self.name)
            logger.info(f"[LLM] {self.name} - : {len(param_descriptions_for_llm)}")
            for param_name, param_desc in param_descriptions_for_llm.items():
                logger.info(f"[LLM] {self.name} - : {param_name} = {param_desc}")
            logger.debug(f"[LLM] {self.name} - :\n{self.formatted_description}")
    def _log_tool_io(self, stage: str, payload: Any):
        if not should_log_tool_io_details():
            return
        try:
            formatted_payload = format_log_payload(payload)
        except Exception as exc:
            logger.debug(f"[IO] {self.name} - : {exc}")
            formatted_payload = str(payload)
        logger.info(f"[IO] : {self.name} | {stage}: {formatted_payload}")
    def _build_error_response(self, error_msg: str) -> str:
        error_payload = {
            "error": error_msg,
            "results": []
        }
        self._log_tool_io("", error_payload)
        return json.dumps(error_payload, ensure_ascii=False)
    def _apply_reranking(self, result: Any) -> Any:
        if not self.reranking_processor:
            return result
        try:
            logger.debug(f"[] {self.name} -  reranking ")
            result = self.reranking_processor.process(result)
            logger.debug(f"[] {self.name} - reranking ")
            return result
        except Exception as e:
            logger.error(f"[] {self.name} - reranking : {str(e)}", exc_info=True)
            return result
    def _build_api_request_params(self, tool_params: Dict[str, Any]) -> tuple:
        query_params = {}
        body_params = {}
        header_params = {}
        if self.parameter_list:
            for param_def in self.parameter_list:
                param_name = param_def.get('param_name')
                param_location = param_def.get('param_location', 'body')
                required = param_def.get('required', False)
                default_value = param_def.get('default_value')
                param_type = param_def.get('param_type', 'string')
                param_value = None
                if param_name in tool_params:
                    param_value = tool_params[param_name]
                elif default_value is not None:
                    try:
                        import json
                        param_value = json.loads(default_value)
                    except (json.JSONDecodeError, TypeError):
                        param_value = default_value
                if required and param_value is None:
                    logger.warning(
                        f"[] {self.name} - : {param_name}"
                    )
                    continue
                if param_value is None:
                    continue
                try:
                    if param_type == 'number':
                        if isinstance(param_value, str):
                            if '.' in param_value:
                                param_value = float(param_value)
                            else:
                                param_value = int(param_value)
                    elif param_type == 'boolean':
                        if isinstance(param_value, str):
                            param_value = param_value.lower() in ('true', '1', 'yes', 'on')
                    elif param_type == 'array' or param_type == 'object':
                        if isinstance(param_value, str):
                            import json
                            param_value = json.loads(param_value)
                except (ValueError, TypeError, json.JSONDecodeError) as e:
                    logger.warning(
                        f"[] {self.name} -  {param_name}: {str(e)}"
                    )
                if param_location == 'query':
                    query_params[param_name] = param_value
                elif param_location == 'header':
                    header_params[param_name] = str(param_value)
                else:
                    body_params[param_name] = param_value
            return query_params, body_params, header_params
        filtered_params = {k: v for k, v in tool_params.items() if v is not None}
        return {}, filtered_params, {}
    def _normalize_parameters(self, tool_params: Dict[str, Any]) -> Dict[str, Any]:
        if 'kwargs' in tool_params and len(tool_params) == 1:
            kwargs_value = tool_params['kwargs']
            if isinstance(kwargs_value, dict):
                logger.debug(
                    f"[] {self.name} -  kwargs : "
                    f"keys={list(kwargs_value.keys())}"
                )
                return kwargs_value
        return tool_params
    async def _send_http_request_async(self, url: str, query_params: Dict[str, Any], 
                                      body_params: Dict[str, Any], request_headers: Dict[str, str]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if self.method == "GET":
                return await client.get(url, params=query_params, headers=request_headers)
            elif self.method == "POST":
                try:
                    json.dumps(body_params, ensure_ascii=False)
                except (TypeError, ValueError) as e:
                    logger.error(
                        f"[] {self.name} - JSON: {str(e)}. "
                        f": {body_params}",
                        exc_info=True
                    )
                    raise ValueError(f"外部工具执行失败: {str(e)}")
                logger.debug(f"[] {self.name} - POST: {query_params}, : {body_params}")
                return await client.post(url, params=query_params, json=body_params, headers=request_headers)
            elif self.method == "PUT":
                try:
                    json.dumps(body_params, ensure_ascii=False)
                except (TypeError, ValueError) as e:
                    logger.error(
                        f"[] {self.name} - JSON: {str(e)}. "
                        f": {body_params}",
                        exc_info=True
                    )
                    raise ValueError(f"外部工具执行失败: {str(e)}")
                logger.debug(f"[] {self.name} - PUT: {query_params}, : {body_params}")
                return await client.put(url, params=query_params, json=body_params, headers=request_headers)
            elif self.method == "DELETE":
                logger.debug(f"[] {self.name} - DELETE: {query_params}")
                return await client.delete(url, params=query_params, headers=request_headers)
            else:
                error_msg = f"HTTP: {self.method}"
                logger.error(f"[] {self.name} - {error_msg}", exc_info=True)
                raise ValueError(error_msg)
    def _send_http_request(self, url: str, query_params: Dict[str, Any], 
                          body_params: Dict[str, Any], request_headers: Dict[str, str]) -> httpx.Response:
        with httpx.Client(timeout=30.0) as client:
            if self.method == "GET":
                logger.debug(f"[] {self.name} - GET: {query_params}")
                return client.get(url, params=query_params, headers=request_headers)
            elif self.method == "POST":
                try:
                    json.dumps(body_params, ensure_ascii=False)
                except (TypeError, ValueError) as e:
                    logger.error(
                        f"[] {self.name} - JSON: {str(e)}. "
                        f": {body_params}",
                        exc_info=True
                    )
                    raise ValueError(f"外部工具执行失败: {str(e)}")
                logger.debug(f"[] {self.name} - POST: {query_params}, : {body_params}")
                return client.post(url, params=query_params, json=body_params, headers=request_headers)
            elif self.method == "PUT":
                try:
                    json.dumps(body_params, ensure_ascii=False)
                except (TypeError, ValueError) as e:
                    logger.error(
                        f"[] {self.name} - JSON: {str(e)}. "
                        f": {body_params}",
                        exc_info=True
                    )
                    raise ValueError(f"外部工具执行失败: {str(e)}")
                logger.debug(f"[] {self.name} - PUT: {query_params}, : {body_params}")
                return client.put(url, params=query_params, json=body_params, headers=request_headers)
            elif self.method == "DELETE":
                logger.debug(f"[] {self.name} - DELETE: {query_params}")
                return client.delete(url, params=query_params, headers=request_headers)
            else:
                error_msg = f"HTTP: {self.method}"
                logger.error(f"[] {self.name} - {error_msg}", exc_info=True)
                raise ValueError(error_msg)
    def _prepare_request(self, kwargs):
        """Build request params (URL, query/body/header). Shared by invoke and ainvoke."""
        normalized_params = self._normalize_parameters(kwargs)
        if normalized_params != kwargs:
            logger.debug(f"[] {self.name} - normalized: {normalized_params}")
        query_params, body_params, header_params = self._build_api_request_params(normalized_params)
        if not query_params and not body_params:
            logger.warning(f"[] {self.name} - API params empty: {kwargs}")
        if self.api_endpoint:
            url = f"{self.api_base_url}/{self.api_endpoint}"
        else:
            url = self.api_base_url
        logger.debug(f"[] {self.name} - {self.method} {url}")
        request_headers = {
            "Content-Type": "application/json",
            **self.headers,
            **header_params
        }
        current_auth = get_current_authorization()
        if current_auth:
            request_headers["Authorization"] = current_auth
            from utils.config.config_loader import get_config
            if not get_config("auth.enable_permission_check", True):
                logger.debug(f"[HTTP] {self.name} - using token")
        return url, query_params, body_params, request_headers

    def _process_response(self, response, start_time, request_start):
        """Process HTTP response: raise_for_status + JSON parse + reranking + logging."""
        import time as _time
        request_duration = _time.time() - request_start
        logger.info(f"[HTTP] {self.name} - HTTP duration: {request_duration:.3f}")
        logger.debug(f"[] {self.name} - HTTP status: {response.status_code}")
        response.raise_for_status()
        result = response.json()
        self._log_tool_io("response", result)
        if self.enable_reranking:
            result = self._apply_reranking(result)
        total_duration = _time.time() - start_time
        result_str = json.dumps(result, ensure_ascii=False)
        result_preview = result_str[:500] + "..." if len(result_str) > 500 else result_str
        logger.debug(f"[] {self.name} - result: {result_preview}")
        logger.debug(f"[] {self.name} - result length: {len(result_str)}")
        logger.info(f"[] {self.name} - total: {total_duration:.3f} (HTTP: {request_duration:.3f})")
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _handle_request_error(self, exc, start_time, url, body_params, kwargs):
        """Handle exceptions from invoke/ainvoke. Returns error JSON or raises ToolException.

        - ValueError: returns error response JSON (no raise)
        - httpx.HTTPStatusError: parse detail, raise ToolException
        - httpx.RequestError: raise ToolException
        - Other: raise ToolException
        """
        import time as _time
        total_duration = _time.time() - start_time
        if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError):
            error_msg = str(exc)
            logger.error(f"[] {self.name} - error: {total_duration:.3f} - {error_msg}", exc_info=True)
            return self._build_error_response(error_msg)
        if isinstance(exc, httpx.HTTPStatusError):
            error_msg = f"HTTP error: {exc.response.status_code}"
            try:
                response_text = exc.response.text
                logger.debug(f"[HTTP] {self.name} - error body: {response_text[:500]}")
                try:
                    error_json = json.loads(response_text)
                    if "detail" in error_json:
                        detail = error_json["detail"]
                        if isinstance(detail, str):
                            error_msg = f"API error: {detail}"
                        elif isinstance(detail, list):
                            error_details = []
                            for item in detail:
                                if isinstance(item, dict):
                                    loc = item.get('loc', [])
                                    msg = item.get('msg', '')
                                    type_ = item.get('type', '')
                                    error_details.append(f"{'.'.join(str(l) for l in loc)}: {msg} ({type_})")
                                else:
                                    error_details.append(str(item))
                            error_msg = f"API error: {'; '.join(error_details)}"
                        elif isinstance(detail, dict):
                            error_msg = f"API error: {json.dumps(detail, ensure_ascii=False)}"
                except json.JSONDecodeError:
                    error_msg += f" - {response_text[:200]}"
            except Exception:
                pass
            logger.error(f"[HTTP] {self.name} - {total_duration:.3f} - {error_msg}", exc_info=True)
            logger.error(f"[HTTP] {self.name} - URL: {url}, method: {self.method}")
            logger.error(f"[HTTP] {self.name} - body: {body_params}")
            raise ToolException(error_msg)
        if isinstance(exc, httpx.RequestError):
            error_msg = f"Request error: {str(exc)}"
            logger.error(f"[] {self.name} - {total_duration:.3f} - {error_msg}", exc_info=True)
            logger.error(f"[] {self.name} - URL: {url}, method: {self.method}")
            raise ToolException(error_msg)
        if isinstance(exc, (KeyError, json.JSONDecodeError)):
            error_msg = f"Parse error: {str(exc)}"
            logger.error(f"[] {self.name} - {total_duration:.3f} - {error_msg}", exc_info=True)
            if isinstance(exc, KeyError):
                logger.error(f"[] {self.name} - kwargs: {kwargs}")
            raise ToolException(error_msg)
        if isinstance(exc, ToolException):
            raise
        error_msg = f"Unexpected error: {str(exc)}"
        logger.error(f"[] {self.name} - {total_duration:.3f} - {error_msg}", exc_info=True)
        raise ToolException(error_msg)

    def invoke(self, **kwargs) -> str:
        """Sync invoke: prepare request, send HTTP, process response."""
        import time
        start_time = time.time()
        logger.debug(f"[] invoking: {self.name}")
        logger.debug(f"[] {self.name} - kwargs: {kwargs}")
        self._log_tool_io("input", kwargs)
        if not self.enabled:
            warning_msg = f"Tool '{self.name}' is disabled"
            logger.warning(f"[] {self.name} - disabled")
            return self._build_error_response(warning_msg)
        try:
            url, query_params, body_params, request_headers = self._prepare_request(kwargs)
            request_start = time.time()
            response = self._send_http_request(url, query_params, body_params, request_headers)
            return self._process_response(response, start_time, request_start)
        except Exception as e:
            return self._handle_request_error(e, start_time, url, body_params, kwargs)

    async def ainvoke(self, **kwargs) -> str:
        """Async invoke: prepare request, send HTTP async, process response."""
        import time
        start_time = time.time()
        logger.debug(f"[] invoking async: {self.name}")
        logger.debug(f"[] {self.name} - kwargs: {kwargs}")
        self._log_tool_io("input", kwargs)
        if not self.enabled:
            warning_msg = f"Tool '{self.name}' is disabled"
            logger.warning(f"[] {self.name} - disabled")
            return self._build_error_response(warning_msg)
        try:
            url, query_params, body_params, request_headers = self._prepare_request(kwargs)
            request_start = time.time()
            response = await self._send_http_request_async(url, query_params, body_params, request_headers)
            return self._process_response(response, start_time, request_start)
        except Exception as e:
            return self._handle_request_error(e, start_time, url, body_params, kwargs)

    def _get_param_names(self) -> List[str]:
        if self.parameter_list:
            seen = set()
            param_names = []
            for param in self.parameter_list:
                name = param.get('param_name')
                if name and name not in seen:
                    seen.add(name)
                    param_names.append(name)
            if param_names:
                return param_names
        return []
    def _build_pydantic_schema(self) -> Optional[type]:
        if not self.parameter_list:
            return None
        fields = {}
        for param in self.parameter_list:
            param_name = param.get('param_name')
            if not param_name:
                continue
            param_type_str = (param.get('param_type') or 'string').lower().strip()
            py_type = PARAM_TYPE_TO_PYTHON.get(param_type_str, str)
            required = param.get('required', False)
            param_desc = param.get('description', '')
            if required:
                fields[param_name] = (py_type, Field(..., description=param_desc))
            else:
                fields[param_name] = (Optional[py_type], Field(default=None, description=param_desc))
        if not fields:
            return None
        return create_model(f'{self.name}Input', **fields)
    def _create_tool_func_with_signature(self, param_names: List[str]):
        def tool_func(*args, **kwargs):
            if args and param_names:
                for i, arg in enumerate(args):
                    if i < len(param_names):
                        param_name = param_names[i]
                        if param_name not in kwargs:
                            kwargs[param_name] = arg
            return self.invoke(**kwargs)
        import inspect
        sig_params = [
            inspect.Parameter(
                param_name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=None
            )
            for param_name in param_names
        ]
        tool_func.__signature__ = inspect.Signature(sig_params)
        return tool_func
    def to_langchain_tool(self):
        description = self.formatted_description or self.description or ""
        args_schema = self._build_pydantic_schema()
        if args_schema:
            def tool_func(**kwargs):
                return self.invoke(**kwargs)
            langchain_tool = StructuredTool.from_function(
                func=tool_func,
                name=self.name,
                description=description,
                args_schema=args_schema,
            )
            return langchain_tool
        param_names = self._get_param_names()
        if param_names:
            tool_func = self._create_tool_func_with_signature(param_names)
        else:
            def tool_func(**kwargs):
                if not kwargs:
                    logger.warning(
                        f"[] {self.name} - kwargs"
                        f"LangChain"
                    )
                return self.invoke(**kwargs)
        tool_func.__doc__ = description
        langchain_tool = tool(tool_func, description=description)
        langchain_tool.name = self.name
        return langchain_tool
def create_external_tool_from_config(tool_name: str) -> Optional[ExternalTool]:
    try:
        config_db = get_config_db()
        config = config_db.get_external_tool_config(tool_name)
        if not config:
            return None
        if not config.get('enabled', True):
            return None
        return ExternalTool(config)
    except (ValueError, KeyError) as e:
        logger.warning(f"加载外部工具配置 {tool_name} 失败: {e}")
        return None
    except Exception as e:
        logger.error(f"加载外部工具 {tool_name} 异常: {e}", exc_info=True)
        return None
def load_all_external_tools() -> Dict[str, ExternalTool]:
    tools = {}
    try:
        config_db = get_config_db()
        configs = config_db.external_tools.get_all(return_format='external_tool')
        logger.info(f"[]  {len(configs)} ")
        for config in configs:
            if config is None:
                logger.warning("[]  None  intfc_name ")
                continue
            tool_name = config.get('intfc_name') or config.get('name', 'unknown')
            enabled = config.get('enabled', True)
            if enabled:
                try:
                    tool_instance = ExternalTool(config)
                    tools[tool_instance.name] = tool_instance
                    logger.info(f"[] : {tool_instance.name}")
                except Exception as e:
                    logger.error(f"[]  {tool_name}: {str(e)}", exc_info=True)
        logger.info(f"[]  {len(tools)} : {', '.join(tools.keys())}")
    except Exception as e:
        logger.error(f"[] : {str(e)}", exc_info=True)
    return tools