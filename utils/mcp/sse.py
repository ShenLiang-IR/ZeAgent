"""MCP 工具集 - SSE/HTTP 传输（fetch server info / tools list / tool call）。"""
import json
import asyncio
import httpx
from loguru import logger
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from .common import resolve_env_vars, extract_params_from_url, build_url_with_params, parse_json_from_sse_text


async def fetch_mcp_server_info(url: str, headers: Optional[Dict[str, str]] = None, url_params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    try:
        actual_url_params = url_params or extract_params_from_url(url)
        final_url = build_url_with_params(url, actual_url_params)
        actual_headers = resolve_env_vars(headers) if headers else {}
        base_headers = {"Accept": "text/event-stream"}
        base_headers.update(actual_headers)
        def parse_server_info(data):
            if not data: return None
            res_obj = data.get("result") or data
            if not isinstance(res_obj, dict): return None
            server_info = res_obj.get("serverInfo", {})
            if not isinstance(server_info, dict) or not server_info.get("name"):
                if res_obj.get("name"):
                    server_info = res_obj
                else:
                    return None
            return {
                "name": server_info.get("name"),
                "version": server_info.get("version", "1.0.0"),
                "description": res_obj.get("instructions", "") or server_info.get("description", "")
            }
        async with httpx.AsyncClient(timeout=30.0) as client:
            post_url = None
            try:
                async with client.stream("GET", final_url, headers=base_headers) as sse_response:
                    if sse_response.status_code == 200 and "text/event-stream" in sse_response.headers.get("Content-Type", ""):
                        from httpx_sse import EventSource
                        event_source = EventSource(sse_response)
                        sse_iter = event_source.aiter_sse()
                        async for event in sse_iter:
                            if event.event == "endpoint":
                                post_url = urljoin(url, event.data)
                                if actual_url_params:
                                    post_url = build_url_with_params(post_url, actual_url_params)
                                break
                        if post_url:
                            actual_post_headers = {
                                "Content-Type": "application/json",
                                "Accept": "application/json, text/event-stream"
                            }
                            actual_post_headers.update(actual_headers)
                            resp = await client.post(post_url, json={
                                "jsonrpc": "2.0", "method": "initialize", "id": 1,
                                "params": {
                                    "protocolVersion": "2024-11-05",
                                    "capabilities": {},
                                    "clientInfo": {"name": "InvRes-Agent", "version": "1.0.0"}
                                }
                            }, headers=actual_post_headers)
                            if resp.status_code in (200, 201):
                                info = parse_server_info(resp.json())
                                if info: return info
                            elif resp.status_code == 202:
                                logger.info(" initialize  202 Accepted SSE ...")
                                async for event in sse_iter:
                                    if event.data:
                                        try:
                                            data = json.loads(event.data)
                                            info = parse_server_info(data)
                                            if info: return info
                                        except Exception: continue
            except Exception as e:
                logger.debug(f"SSE : {e}")
            if not post_url:
                post_url = final_url
                actual_post_headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                }
                actual_post_headers.update(actual_headers)
                try:
                    resp = await client.post(post_url, json={
                        "jsonrpc": "2.0", "method": "initialize", "id": 1,
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "InvRes-Agent", "version": "1.0.0"}
                        }
                    }, headers=actual_post_headers)
                    if resp.status_code in (200, 201):
                        info = parse_server_info(resp.json())
                        if info: return info
                    elif resp.status_code == 202:
                        await asyncio.sleep(1.0)
                        retry_resp = await client.get(post_url, headers=actual_post_headers)
                        if retry_resp.status_code == 200:
                            info = parse_server_info(retry_resp.json())
                            if info: return info
                except Exception as e:
                    logger.debug(f" POST initialize : {e}")
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                path_parts = [p for p in parsed.path.split('/') if p]
                if path_parts:
                    inferred_name = path_parts[-1]
                    if inferred_name and inferred_name.lower() != 'mcp':
                        logger.info(f" URL : {inferred_name}")
                        return {
                            "name": inferred_name,
                            "version": "1.0.0",
                            "description": f"MCP  ( URL : {url})"
                        }
            except Exception as e:
                logger.debug(f" URL : {e}")
            return {}
    except Exception as e:
        logger.error(f"SSE 请求失败: {e}")
        return {}


async def fetch_mcp_tools_from_url(url: str, headers: Optional[Dict[str, str]] = None, url_params: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    try:
        actual_url_params = url_params or extract_params_from_url(url)
        final_url = build_url_with_params(url, actual_url_params)
        actual_headers = resolve_env_vars(headers) if headers else {}
        base_headers = {"Accept": "text/event-stream"}
        base_headers.update(actual_headers)
        async with httpx.AsyncClient(timeout=30.0) as client:
            post_url = None
            session_id = None
            async def initialize_session(target_url: str, post_headers: Dict[str, str]) -> Optional[str]:
                try:
                    current_headers = post_headers.copy()
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
                    init_response = await client.post(target_url, json=init_payload, headers=current_headers)
                    if init_response.status_code in (200, 201):
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
                            logger.info(f" session ID: {sid}")
                            notif_headers = current_headers.copy()
                            notif_headers["mcp-session-id"] = sid
                            await client.post(target_url, json={
                                "jsonrpc": "2.0",
                                "method": "notifications/initialized"
                            }, headers=notif_headers)
                            return sid
                except Exception as e:
                    logger.warning(f" (): {e}")
                return None
            try:
                async with client.stream("GET", final_url, headers=base_headers) as sse_response:
                    if sse_response.status_code == 200 and "text/event-stream" in sse_response.headers.get("Content-Type", ""):
                        from httpx_sse import EventSource
                        event_source = EventSource(sse_response)
                        sse_iter = event_source.aiter_sse()
                        async for event in sse_iter:
                            if event.event == "endpoint":
                                post_url = urljoin(url, event.data)
                                if actual_url_params:
                                    post_url = build_url_with_params(post_url, actual_url_params)
                                logger.info(f" SSE  endpoint: {post_url}")
                                break
                        if post_url:
                            actual_post_headers = {
                                "Content-Type": "application/json",
                                "Accept": "application/json, text/event-stream"
                            }
                            actual_post_headers.update(actual_headers)
                            session_id = await initialize_session(post_url, actual_post_headers)
                            if session_id:
                                actual_post_headers["mcp-session-id"] = session_id
                            tools_payload = {
                                "jsonrpc": "2.0",
                                "method": "tools/list",
                                "id": 1
                            }
                            response_tools = await client.post(post_url, json=tools_payload, headers=actual_post_headers)
                            if response_tools.status_code in (200, 201):
                                try:
                                    resp_tools_text = response_tools.text
                                    if "data:" in resp_tools_text:
                                        data = parse_json_from_sse_text(resp_tools_text)
                                    else:
                                        data = response_tools.json()
                                    return data.get("result", {}).get("tools", [])
                                except (json.JSONDecodeError, ValueError) as e:
                                    logger.warning(f"SSE  JSON : {e}, : {response_tools.text[:500]}")
                                    raise
                            elif response_tools.status_code == 202:
                                logger.info(" 202 Accepted SSE ...")
                                async for event in sse_iter:
                                    if event.data:
                                        try:
                                            data = json.loads(event.data)
                                            tools = data.get("result", {}).get("tools") or data.get("tools")
                                            if isinstance(tools, list):
                                                return tools
                                        except Exception: continue
            except Exception as sse_err:
                logger.warning(f"SSE  POST: {sse_err}")
            if not post_url:
                post_url = final_url
            actual_post_headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
            actual_post_headers.update(actual_headers)
            if not session_id:
                session_id = await initialize_session(post_url, actual_post_headers)
                if session_id:
                    actual_post_headers["mcp-session-id"] = session_id
            tools_payload = {
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": 1
            }
            response_tools = await client.post(post_url, json=tools_payload, headers=actual_post_headers)
            if response_tools.status_code == 400:
                try:
                    resp_400_text = response_tools.text
                    if "data:" in resp_400_text:
                        error_data = parse_json_from_sse_text(resp_400_text)
                    else:
                        error_data = response_tools.json()
                    error_msg = str(error_data.get("error", {})).lower()
                    if "session" in error_msg and not session_id:
                        logger.info(" session ID...")
                        session_id = await initialize_session(post_url, actual_post_headers)
                        if session_id:
                            actual_post_headers["mcp-session-id"] = session_id
                            response_tools = await client.post(post_url, json=tools_payload, headers=actual_post_headers)
                except Exception:
                    pass
            if response_tools.status_code not in (200, 201, 202):
                raise Exception(f" (HTTP {response_tools.status_code}, URL: {post_url}): {response_tools.text[:200]}")
            resp_text = response_tools.text
            if not resp_text.strip() and response_tools.status_code == 202:
                location = response_tools.headers.get("Location")
                if location:
                    redirect_response = await client.get(location, headers=actual_post_headers)
                    resp_text = redirect_response.text
                else:
                    await asyncio.sleep(2.0)
                    get_response = await client.get(post_url, headers=actual_post_headers)
                    resp_text = get_response.text
            if not resp_text or not resp_text.strip():
                logger.warning(f" (HTTP {response_tools.status_code}, URL: {post_url})")
                if response_tools.status_code == 202:
                    await asyncio.sleep(1.0)
                    retry_response = await client.get(post_url, headers=actual_post_headers)
                    resp_text = retry_response.text
                    if not resp_text or not resp_text.strip():
                        raise Exception(f"MCP  (HTTP {response_tools.status_code}, URL: {post_url})")
            try:
                if "data:" in resp_text:
                    sse_data = parse_json_from_sse_text(resp_text)
                    if sse_data:
                        result = sse_data
                    else:
                        result = json.loads(resp_text)
                else:
                    result = json.loads(resp_text)
            except json.JSONDecodeError as e:
                logger.error(f"JSON : {e}, : {resp_text[:500]}")
                raise Exception(f"MCP  JSON  (HTTP {response_tools.status_code}, URL: {post_url}): {resp_text[:200]}")
            if "error" in result:
                raise Exception(f"MCP : {result['error']}")
            tools = result.get("result", {}).get("tools", [])
            return tools
    except Exception as e:
        logger.error(f"获取 MCP 工具列表失败: {str(e)}")
        raise Exception(f"获取 MCP 工具列表异常: {str(e)}")


async def _call_mcp_tool_sse(url: str, tool_name: str, arguments: Dict[str, Any], headers: Optional[Dict[str, str]] = None, url_params: Optional[Dict[str, str]] = None):
    try:
        actual_url_params = url_params or extract_params_from_url(url)
        final_url = build_url_with_params(url, actual_url_params)
        actual_headers = resolve_env_vars(headers) if headers else {}
        base_headers = {"Accept": "text/event-stream"}
        base_headers.update(actual_headers)
        async with httpx.AsyncClient(timeout=60.0) as client:
            post_url = None
            session_id = None
            async def initialize_session(target_url: str, post_headers: Dict[str, str]) -> Optional[str]:
                try:
                    current_headers = post_headers.copy()
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
                    init_response = await client.post(target_url, json=init_payload, headers=current_headers)
                    if init_response.status_code in (200, 201):
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
                            logger.info(f" session ID: {sid}")
                            notif_headers = current_headers.copy()
                            notif_headers["mcp-session-id"] = sid
                            await client.post(target_url, json={
                                "jsonrpc": "2.0",
                                "method": "notifications/initialized"
                            }, headers=notif_headers)
                            return sid
                except Exception as e:
                    logger.warning(f" (): {e}")
                return None
            try:
                async with client.stream("GET", final_url, headers=base_headers) as sse_response:
                    if sse_response.status_code == 200 and "text/event-stream" in sse_response.headers.get("Content-Type", ""):
                        from httpx_sse import EventSource
                        event_source = EventSource(sse_response)
                        sse_iter = event_source.aiter_sse()
                        async for event in sse_iter:
                            if event.event == "endpoint":
                                post_url = urljoin(url, event.data)
                                if actual_url_params:
                                    post_url = build_url_with_params(post_url, actual_url_params)
                                break
                        if post_url:
                            actual_post_headers = {
                                "Content-Type": "application/json",
                                "Accept": "application/json, text/event-stream"
                            }
                            actual_post_headers.update(actual_headers)
                            session_id = await initialize_session(post_url, actual_post_headers)
                            if session_id:
                                actual_post_headers["mcp-session-id"] = session_id
                            response_call = await client.post(post_url, json={
                                "jsonrpc": "2.0", "method": "tools/call", "id": 1,
                                "params": {"name": tool_name, "arguments": arguments}
                            }, headers=actual_post_headers)
                            if response_call.status_code in (200, 201):
                                try:
                                    resp_call_text = response_call.text
                                    if "data:" in resp_call_text:
                                        result = parse_json_from_sse_text(resp_call_text)
                                    else:
                                        result = response_call.json()
                                    content = result.get("result", {}).get("content", [])
                                    return "\n".join([c.get("text", "") for c in content if c.get("type") == "text"])
                                except (json.JSONDecodeError, ValueError) as e:
                                    logger.warning(f"SSE  JSON : {e}, : {response_call.text[:500]}")
                                    raise
                            elif response_call.status_code == 202:
                                async for event in sse_iter:
                                    if event.data:
                                        try:
                                            data = json.loads(event.data)
                                            res = data.get("result") or data
                                            if "content" in res:
                                                content = res.get("content", [])
                                                return "\n".join([c.get("text", "") for c in content if c.get("type") == "text"])
                                        except Exception: continue
            except Exception as e:
                logger.warning(f"SSE  POST: {e}")
            if not post_url:
                post_url = final_url
            actual_post_headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
            actual_post_headers.update(actual_headers)
            if not session_id:
                session_id = await initialize_session(post_url, actual_post_headers)
                if session_id:
                    actual_post_headers["mcp-session-id"] = session_id
            response_call = await client.post(post_url, json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {"name": tool_name, "arguments": arguments}
            }, headers=actual_post_headers)
            if response_call.status_code == 400:
                try:
                    resp_400_text = response_call.text
                    if "data:" in resp_400_text:
                        error_data = parse_json_from_sse_text(resp_400_text)
                    else:
                        error_data = response_call.json()
                    error_msg = str(error_data.get("error", {})).lower()
                    if "session" in error_msg and not session_id:
                        logger.info(" session ID...")
                        session_id = await initialize_session(post_url, actual_post_headers)
                        if session_id:
                            actual_post_headers["mcp-session-id"] = session_id
                            response_call = await client.post(post_url, json={
                                "jsonrpc": "2.0",
                                "method": "tools/call",
                                "id": 1,
                                "params": {"name": tool_name, "arguments": arguments}
                            }, headers=actual_post_headers)
                except Exception:
                    pass
            if response_call.status_code not in (200, 201, 202):
                raise Exception(f" (HTTP {response_call.status_code}, URL: {post_url}): {response_call.text[:200]}")
            resp_text = response_call.text
            if not resp_text.strip() and response_call.status_code == 202:
                location = response_call.headers.get("Location")
                if location:
                    redirect_response = await client.get(location, headers=actual_post_headers)
                    resp_text = redirect_response.text
                else:
                    await asyncio.sleep(1.0)
                    get_response = await client.get(post_url, headers=actual_post_headers)
                    resp_text = get_response.text
            if not resp_text or not resp_text.strip():
                logger.warning(f" (HTTP {response_call.status_code}, URL: {post_url})")
                if response_call.status_code == 202:
                    await asyncio.sleep(1.0)
                    retry_response = await client.get(post_url, headers=actual_post_headers)
                    resp_text = retry_response.text
                    if not resp_text or not resp_text.strip():
                        raise Exception(f"MCP  (HTTP {response_call.status_code}, URL: {post_url})")
            try:
                if "data:" in resp_text:
                    sse_data = parse_json_from_sse_text(resp_text)
                    if sse_data:
                        result = sse_data
                    else:
                        result = json.loads(resp_text)
                else:
                    result = json.loads(resp_text)
            except json.JSONDecodeError as e:
                logger.error(f"JSON : {e}, : {resp_text[:500]}")
                raise Exception(f"MCP  JSON  (HTTP {response_call.status_code}, URL: {post_url}): {resp_text[:200]}")
            if "error" in result:
                raise Exception(f"MCP : {result['error']}")
            content = result.get("result", {}).get("content", [])
            return "\n".join([c.get("text", "") for c in content if c.get("type") == "text"])
    except Exception as e:
        logger.error(f" MCP  (SSE): {str(e)}")
        return f"Error: {str(e)}"
