from __future__ import annotations
import asyncio
import json
from typing import Any, Dict, Optional
import httpx
from loguru import logger
async def initialize_session(
    client: httpx.AsyncClient,
    url: str,
    headers: Dict[str, str],
) -> Optional[str]:
    from utils.mcp_util import parse_json_from_sse_text
    try:
        current_headers = headers.copy()
        current_headers["Accept"] = "application/json, text/event-stream"
        init_payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "InvRes-Agent", "version": "1.0.0"}
            }
        }
        init_response = await client.post(url, json=init_payload, headers=current_headers)
        if init_response.status_code not in (200, 201):
            return None
        sid = (
            init_response.headers.get("Mcp-Session-Id") or
            init_response.headers.get("mcp-session-id")
        )
        if not sid:
            resp_text = init_response.text
            data = None
            if "data:" in resp_text:
                data = parse_json_from_sse_text(resp_text)
            else:
                try:
                    data = init_response.json()
                except Exception:
                    pass
            if data:
                sid = data.get("result", {}).get("sessionId") or data.get("sessionId")
        if sid:
            notif_headers = current_headers.copy()
            notif_headers["mcp-session-id"] = sid
            await client.post(url, json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            }, headers=notif_headers)
        return sid
    except Exception as e:
        logger.warning(f"[MCP SSE] : {e}")
        return None
def parse_mcp_response(resp_text: str) -> Dict[str, Any]:
    from utils.mcp_util import parse_json_from_sse_text
    if "data:" in resp_text:
        result = parse_json_from_sse_text(resp_text)
        if result:
            return result
    return json.loads(resp_text)
def extract_content(result: Dict[str, Any]) -> str:
    if "error" in result:
        raise Exception(f"MCP : {result['error']}")
    content = result.get("result", {}).get("content", [])
    return "\n".join([c.get("text", "") for c in content if c.get("type") == "text"])
async def call_mcp_sse(
    url: str,
    tool_name: str,
    arguments: Dict[str, Any],
    timeout: float = 60.0,
    headers: Optional[Dict[str, str]] = None,
    url_params: Optional[Dict[str, str]] = None,
) -> Any:
    from utils.mcp_util import resolve_env_vars
    actual_headers = resolve_env_vars(headers) if headers else {}
    base_headers = {"Accept": "text/event-stream"}
    base_headers.update(actual_headers)
    async with httpx.AsyncClient(timeout=timeout + 5) as client:
        post_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        post_headers.update(actual_headers)
        session_id = await initialize_session(client, url, post_headers)
        if session_id:
            post_headers["mcp-session-id"] = session_id
        response = await client.post(
            url,
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {"name": tool_name, "arguments": arguments}
            },
            headers=post_headers,
            timeout=timeout
        )
        if response.status_code not in (200, 201, 202):
            raise Exception(f" (HTTP {response.status_code}): {response.text[:200]}")
        resp_text = response.text
        if not resp_text.strip() and response.status_code == 202:
            await asyncio.sleep(1.0)
            get_response = await client.get(url, headers=post_headers)
            resp_text = get_response.text
        result = parse_mcp_response(resp_text)
        return extract_content(result)