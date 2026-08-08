from __future__ import annotations
import asyncio
import json
import os
from typing import Any, Dict, List
async def call_mcp_stdio(
    command: str,
    args: List[str],
    tool_name: str,
    arguments: Dict[str, Any],
    timeout: float = 60.0,
    env: Dict[str, str] = None,
) -> Any:
    full_env = os.environ.copy()
    if env:
        from utils.mcp_util import resolve_env_vars
        full_env.update(resolve_env_vars(env))
    process = await asyncio.create_subprocess_exec(
        command, *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=full_env
    )
    try:
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {"name": tool_name, "arguments": arguments}
        }
        process.stdin.write((json.dumps(request) + "\n").encode())
        await process.stdin.drain()
        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError:
            raise Exception(f"MCP {timeout}")
        if not line or not line.strip():
            stderr_text = await _read_stderr(process)
            raise Exception(f"MCP : {stderr_text[:500]}")
        line_text = line.decode('utf-8', errors='ignore').strip()
        try:
            result = json.loads(line_text)
        except json.JSONDecodeError:
            stderr_text = await _read_stderr(process)
            raise Exception(f"MCP  JSON: {line_text[:200]}: {stderr_text[:500]}")
        if "error" in result:
            raise Exception(f"MCP : {result['error']}")
        content = result.get("result", {}).get("content", [])
        return "\n".join([c.get("text", "") for c in content if c.get("type") == "text"])
    except FileNotFoundError as e:
        raise Exception(f" '{command}': {e}")
    finally:
        await _cleanup_process(process)
async def _read_stderr(process: asyncio.subprocess.Process) -> str:
    stderr_data = await process.stderr.read()
    return stderr_data.decode('utf-8', errors='ignore') if stderr_data else ""
async def _cleanup_process(process: asyncio.subprocess.Process) -> None:
    try:
        process.terminate()
        await process.wait()
    except Exception:
        pass