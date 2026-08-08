"""MCP 工具集 - 通用基础函数（URL 解析 / 环境变量替换 / SSE 文本解析）。"""
import json
import os
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

ENV_VAR_PATTERN = re.compile(r'\${(\w+)}')


def resolve_env_vars(data: Any) -> Any:
    if isinstance(data, str):
        def replace(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        return ENV_VAR_PATTERN.sub(replace, data).strip()
    elif isinstance(data, dict):
        return {
            (k.strip() if isinstance(k, str) else k): resolve_env_vars(v)
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [resolve_env_vars(i) for i in data]
    return data


def extract_params_from_url(url: str) -> Dict[str, str]:
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        return {k: v[0] for k, v in params.items() if v}
    except Exception:
        return {}


def parse_json_from_sse_text(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    matches = re.findall(r'^\s*data:\s*(.*)$', text, re.MULTILINE)
    for data_content in matches:
        data_content = data_content.strip()
        if not data_content:
            continue
        try:
            return json.loads(data_content)
        except Exception:
            continue
    return None


def build_url_with_params(base_url: str, url_params: Optional[Dict[str, str]] = None) -> str:
    if not url_params:
        return base_url
    resolved_params = resolve_env_vars(url_params) if url_params else {}
    if not resolved_params:
        return base_url
    parsed = urlparse(base_url)
    existing_params = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in resolved_params.items():
        existing_params[key] = [value]
    new_query = urlencode(existing_params, doseq=True)
    new_parsed = parsed._replace(query=new_query)
    return urlunparse(new_parsed)
