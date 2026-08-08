#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Base64 编码/解码工具。"""
import argparse, base64, json, sys
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")

def main():
    p = argparse.ArgumentParser(description="Base64 工具")
    p.add_argument("--action", required=True, choices=["encode", "decode"], help="操作")
    p.add_argument("--text", default="", help="输入文本")
    p.add_argument("--file", default="", help="输入文件")
    p.add_argument("--output", default="", help="输出文件")
    args = p.parse_args()

    if args.file:
        with open(args.file, "rb") as f:
            data = f.read()
    elif args.text:
        data = args.text.encode("utf-8")
    else:
        print(json.dumps({"error": "需要 --text 或 --file"}, ensure_ascii=False)); sys.exit(1)

    if args.action == "encode":
        result = base64.b64encode(data).decode("ascii")
    else:
        try:
            result = base64.b64decode(data).decode("utf-8", errors="replace")
        except Exception as e:
            print(json.dumps({"error": f"解码失败: {e}"}, ensure_ascii=False)); sys.exit(1)

    if args.output:
        from pathlib import Path; Path(args.output).write_text(result, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(json.dumps({"result": result}, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
