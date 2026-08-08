#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 请求工具 — 发送 HTTP 请求并返回 JSON 格式响应。

支持 GET/POST/PUT/DELETE，自定义 headers/body/timeout。
使用 urllib（标准库），无第三方依赖。
"""
import argparse
import json
import sys
import urllib.request
import urllib.error

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="HTTP 请求工具")
    parser.add_argument("--url", required=True, help="请求 URL")
    parser.add_argument("--method", default="GET", help="HTTP 方法")
    parser.add_argument("--headers", default="{}", help="请求头 JSON")
    parser.add_argument("--body", default="", help="请求体 JSON")
    parser.add_argument("--timeout", type=int, default=30, help="超时秒数")
    parser.add_argument("--output", default="", help="输出文件路径")
    args = parser.parse_args()

    try:
        headers = json.loads(args.headers) if args.headers else {}
    except json.JSONDecodeError:
        print(json.dumps({"error": "headers JSON 格式错误"}, ensure_ascii=False))
        sys.exit(1)

    method = args.method.upper()
    data = None
    if args.body and method in ("POST", "PUT", "PATCH"):
        data = args.body.encode("utf-8")
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

    req = urllib.request.Request(args.url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            status = resp.status
            resp_headers = dict(resp.headers)
            body = resp.read().decode("utf-8", errors="replace")
            try:
                body_parsed = json.loads(body)
                body = body_parsed
            except (json.JSONDecodeError, ValueError):
                pass
            result = {"status_code": status, "headers": resp_headers, "body": body}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        result = {"status_code": e.code, "headers": dict(e.headers), "body": body, "error": str(e)}
    except Exception as e:
        result = {"status_code": 0, "error": f"{type(e).__name__}: {e}"}

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(output, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(output)


if __name__ == "__main__":
    main()
