"""MCP 工具集 - stdio 传输（进程握手 / tools/list / tools/call + 错误格式化）。"""
import json
import asyncio
import os
import re
from loguru import logger
from typing import Any, Dict, List
from .common import resolve_env_vars


def _format_mcp_error(command: str, args: List[str], stderr_text: str, base_msg: str = "MCP ") -> str:
    error_msg = f"{base_msg}\n"
    error_msg += f": {command} {' '.join(args)}\n"
    if stderr_text:
        error_msg += f": {stderr_text[:500]}\n"
        if "ModuleNotFoundError" in stderr_text or "No module named" in stderr_text:
            module_match = re.search(r"No module named ['\"]([^'\"]+)['\"]", stderr_text)
            module_name = module_match.group(1) if module_match else ""
            python_path = None
            path_match = re.search(r"^([^\s:]+python[^\s:]*):", stderr_text, re.MULTILINE)
            if path_match:
                python_path = path_match.group(1)
            else:
                file_match = re.search(r"File \"([^\"]+python[^\"]*)\"", stderr_text)
                if file_match:
                    python_path = file_match.group(1)
            error_msg += f"\n💡  Python  '{module_name}'\n"
            if python_path and (".venv" in python_path or "venv" in python_path):
                error_msg += f"    Python: {python_path}\n"
                error_msg += f"   \n"
                if "bin/python" in python_path:
                    pip_path = python_path.replace("bin/python", "bin/pip")
                    error_msg += f"   1. {pip_path} install {module_name}\n"
                else:
                    error_msg += f"   1. {python_path} -m pip install {module_name}\n"
                error_msg += f"   2.  Python command  Python  /usr/bin/python3  python3\n"
                error_msg += f"   3.  MCP "
            elif python_path:
                error_msg += f"    Python: {python_path}\n"
                error_msg += f"    Python {python_path} -m pip install {module_name}"
            else:
                error_msg += f"   pip install {module_name}\n"
                error_msg += f"    Python "
        elif "can't find '__main__' module" in stderr_text:
            error_msg += f"\n💡  Python \n"
            error_msg += f"    .py  server.py"
        elif "FileNotFoundError" in stderr_text or "No such file or directory" in stderr_text:
            error_msg += f"\n💡 \n"
            error_msg += f"   "
    return error_msg


async def fetch_mcp_tools_from_command(command: str, args: List[str], env: Dict[str, str]) -> List[Dict[str, Any]]:
    try:
        full_env = os.environ.copy()
        if env:
            resolved_env = resolve_env_vars(env)
            full_env.update(resolved_env)
        process = await asyncio.create_subprocess_exec(
            command, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env
        )
        request = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1
        }
        process.stdin.write((json.dumps(request) + "\n").encode())
        await process.stdin.drain()
        timeout = 60.0
        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError:
            process.terminate()
            await process.wait()
            raise Exception(f"MCP {timeout} npx ")
        if not line or not line.strip():
            await asyncio.sleep(0.5)
            stderr_data = b""
            while True:
                chunk = await process.stderr.read(1024)
                if not chunk:
                    break
                stderr_data += chunk
            try:
                process.terminate()
                await process.wait()
            except Exception:
                pass
            stderr_text = stderr_data.decode('utf-8', errors='ignore') if stderr_data else ""
            error_msg = _format_mcp_error(command, args, stderr_text)
            raise Exception(error_msg)
        line_text = line.decode('utf-8', errors='ignore').strip()
        if not line_text:
            stderr_data = await process.stderr.read()
            stderr_text = stderr_data.decode('utf-8', errors='ignore') if stderr_data else ""
            try:
                process.terminate()
                await process.wait()
            except Exception:
                pass
            error_msg = _format_mcp_error(command, args, stderr_text, "MCP ")
            raise Exception(error_msg)
        try:
            result = json.loads(line_text)
        except json.JSONDecodeError as e:
            stderr_data = await process.stderr.read()
            stderr_text = stderr_data.decode('utf-8', errors='ignore') if stderr_data else ""
            try:
                process.terminate()
                await process.wait()
            except Exception:
                pass
            error_msg = f"MCP  JSON \n"
            error_msg += f": {command} {' '.join(args)}\n"
            error_msg += f": {line_text[:200]}\n"
            if stderr_text:
                error_msg += f": {stderr_text[:500]}"
            raise Exception(error_msg)
        try:
            process.terminate()
            await process.wait()
        except Exception:
            pass
        if "error" in result:
            raise Exception(f"MCP : {result['error']}")
        return result.get("result", {}).get("tools", [])
    except FileNotFoundError as e:
        error_msg = f" '{command}'\n"
        error_msg += f"1.  /usr/bin/python3\n"
        error_msg += f"2.  PATH \n"
        error_msg += f"3. \n"
        error_msg += f": {str(e)}"
        logger.error(f" (Command): {error_msg}")
        raise Exception(error_msg)
    except Exception as e:
        logger.error(f" (Command): {str(e)}")
        raise


async def _call_mcp_tool_stdio(command: str, args: List[str], env: Dict[str, str], tool_name: str, arguments: Dict[str, Any]):
    """通过进程池调用 MCP stdio 工具（复用已握手的连接）。

    优先走 McpProcessPool（长连接 + 复用握手），异常时降级到旧的短连接逻辑。
    """
    try:
        from tools.data_providers.mcp_client.process_pool import McpProcessPool
        pool = McpProcessPool.get_instance()
        return await pool.call_tool(command, args, env, tool_name, arguments)
    except Exception as pool_err:
        logger.debug(f"[MCP stdio] pool call failed, fallback to short-lived: {pool_err}")
        return await _call_mcp_tool_stdio_shortlived(command, args, env, tool_name, arguments)


async def _call_mcp_tool_stdio_shortlived(command: str, args: List[str], env: Dict[str, str], tool_name: str, arguments: Dict[str, Any]):
    """旧的短连接逻辑（每次 fork + terminate），作为进程池的降级 fallback。"""
    try:
        full_env = os.environ.copy()
        if env:
            resolved_env = resolve_env_vars(env)
            full_env.update(resolved_env)
        process = await asyncio.create_subprocess_exec(
            command, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env
        )
        # 1. MCP 协议要求：先发 initialize 握手
        init_request = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 0,
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "InvRes-Agent", "version": "1.0.0"}
            }
        }
        process.stdin.write((json.dumps(init_request) + "\n").encode())
        await process.stdin.drain()
        # 读 initialize 响应
        init_line = await asyncio.wait_for(process.stdout.readline(), timeout=60.0)
        if init_line and init_line.strip():
            try:
                init_result = json.loads(init_line.decode('utf-8', errors='ignore').strip())
                logger.debug(f"[MCP stdio] initialize OK: {init_result.get('result', {}).get('serverInfo', {})}")
            except Exception:
                pass
        # 2. 发 initialized 通知（MCP 协议要求，通知握手完成）
        initialized_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        process.stdin.write((json.dumps(initialized_notification) + "\n").encode())
        await process.stdin.drain()
        # 3. 发 tools/call 请求
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        process.stdin.write((json.dumps(request) + "\n").encode())
        await process.stdin.drain()
        timeout = 60.0
        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError:
            process.terminate()
            await process.wait()
            raise Exception(f"MCP {timeout}")
        if not line or not line.strip():
            await asyncio.sleep(0.5)
            stderr_data = b""
            while True:
                chunk = await process.stderr.read(1024)
                if not chunk:
                    break
                stderr_data += chunk
            try:
                process.terminate()
                await process.wait()
            except Exception:
                pass
            stderr_text = stderr_data.decode('utf-8', errors='ignore') if stderr_data else ""
            error_msg = _format_mcp_error(command, args, stderr_text)
            raise Exception(error_msg)
        line_text = line.decode('utf-8', errors='ignore').strip()
        if not line_text:
            stderr_data = await process.stderr.read()
            stderr_text = stderr_data.decode('utf-8', errors='ignore') if stderr_data else ""
            try:
                process.terminate()
                await process.wait()
            except Exception:
                pass
            error_msg = _format_mcp_error(command, args, stderr_text, "MCP ")
            raise Exception(error_msg)
        try:
            result = json.loads(line_text)
        except json.JSONDecodeError as e:
            stderr_data = await process.stderr.read()
            stderr_text = stderr_data.decode('utf-8', errors='ignore') if stderr_data else ""
            try:
                process.terminate()
                await process.wait()
            except Exception:
                pass
            error_msg = f"MCP  JSON \n"
            error_msg += f": {command} {' '.join(args)}\n"
            error_msg += f": {line_text[:200]}\n"
            if stderr_text:
                error_msg += f": {stderr_text[:500]}"
            raise Exception(error_msg)
        try:
            process.terminate()
            await process.wait()
        except Exception:
            pass
        if "error" in result:
            raise Exception(f"MCP : {result['error']}")
        content = result.get("result", {}).get("content", [])
        return "\n".join([c.get("text", "") for c in content if c.get("type") == "text"])
    except FileNotFoundError as e:
        error_msg = f" '{command}': {str(e)}"
        logger.error(f" MCP  (Stdio): {error_msg}")
        return f"Error: {error_msg}"
    except Exception as e:
        logger.error(f" MCP  (Stdio): {str(e)}")
        return f"Error: {str(e)}"
