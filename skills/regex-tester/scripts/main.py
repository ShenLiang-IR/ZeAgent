#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正则表达式测试器。"""
import argparse, json, re, sys
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")

def main():
    p = argparse.ArgumentParser(description="正则表达式测试器")
    p.add_argument("--pattern", required=True, help="正则表达式")
    p.add_argument("--text", required=True, help="输入文本")
    p.add_argument("--action", default="match", choices=["match", "replace", "split"], help="操作")
    p.add_argument("--replacement", default="", help="替换字符串")
    args = p.parse_args()

    try:
        pattern = re.compile(args.pattern)
    except re.error as e:
        print(json.dumps({"error": f"正则编译失败: {e}"}, ensure_ascii=False)); sys.exit(1)

    if args.action == "match":
        matches = [{"match": m.group(), "groups": m.groups(), "span": list(m.span())} for m in pattern.finditer(args.text)]
        print(json.dumps({"matches": matches, "count": len(matches)}, ensure_ascii=False, indent=2))
    elif args.action == "replace":
        result = pattern.sub(args.replacement, args.text)
        print(json.dumps({"result": result}, ensure_ascii=False, indent=2))
    elif args.action == "split":
        parts = pattern.split(args.text)
        print(json.dumps({"parts": parts, "count": len(parts)}, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
