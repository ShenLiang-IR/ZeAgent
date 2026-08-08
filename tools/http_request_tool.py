"""HTTP 请求工具 — 调用 skills/http-request/scripts/main.py 执行 HTTP 请求。

作为 LangChain Tool 注册到 ToolRegistry，供 Agent 对话调用。
实际执行委托给 skills/http-request/scripts/main.py（bash subprocess）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from loguru import logger


# Skill 脚本路径
_SKILL_SCRIPT = str(Path(__file__).resolve().parent.parent / "skills" / "http-request" / "scripts" / "main.py")
_PYTHON = sys.executable


class HttpRequestInput(BaseModel):
    """HTTP 请求参数。"""
    url: str = Field(..., description="请求 URL，如 https://api.example.com/data")
    method: str = Field(default="GET", description="HTTP 方法: GET/POST/PUT/DELETE")
    headers: Optional[str] = Field(default="", description="请求头 JSON 字符串，如 {\"Content-Type\":\"application/json\"}")
    body: Optional[str] = Field(default="", description="请求体 JSON 字符串（POST/PUT 时使用）")
    timeout: int = Field(default=30, description="超时秒数")


def _execute_http_request(url: str, method: str = "GET", headers: str = "", body: str = "", timeout: int = 30) -> str:
    """同步执行 HTTP 请求 skill 脚本。"""
    cmd = [_PYTHON, _SKILL_SCRIPT, "--url", url, "--method", method, "--timeout", str(timeout)]
    if headers:
        cmd.extend(["--headers", headers])
    if body:
        cmd.extend(["--body", body])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 10,  # 给脚本本身多点余量
            encoding="utf-8",
        )
        if result.returncode != 0:
            logger.warning(f"[http-request] script failed: {result.stderr[:200]}")
            return json.dumps({"error": result.stderr[:500]}, ensure_ascii=False)
        return result.stdout
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"执行超时（{timeout}s）"}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[http-request] execution error: {e}", exc_info=True)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# 构建为 LangChain StructuredTool
http_request = StructuredTool.from_function(
    func=_execute_http_request,
    name="http_request",
    description=(
        "发送 HTTP 请求到指定 URL，支持 GET/POST/PUT/DELETE 方法。"
        "可自定义请求头和请求体。返回 JSON 格式响应，包含 status_code、headers、body。"
        "参数: url(必填), method(默认GET), headers(JSON字符串), body(JSON字符串), timeout(默认30秒)"
    ),
    args_schema=HttpRequestInput,
)
