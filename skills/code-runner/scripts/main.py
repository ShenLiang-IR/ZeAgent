#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""代码执行器 — 执行 Python 代码片段，返回 stdout/stderr。

在子进程中执行，有超时保护。
"""
import argparse
import json
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="代码执行器")
    parser.add_argument("--code", required=True, help="Python 代码")
    parser.add_argument("--stdin", default="", help="stdin 输入")
    parser.add_argument("--timeout", type=int, default=10, help="超时秒数")
    args = parser.parse_args()

    start = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", args.code],
            input=args.stdin,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            encoding="utf-8",
        )
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        result = {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode,
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        result = {
            "stdout": "",
            "stderr": f"执行超时（{args.timeout}s）",
            "exit_code": -1,
            "duration_ms": duration_ms,
        }
    except Exception as e:
        result = {"stdout": "", "stderr": f"{type(e).__name__}: {e}", "exit_code": -1, "duration_ms": 0}

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
