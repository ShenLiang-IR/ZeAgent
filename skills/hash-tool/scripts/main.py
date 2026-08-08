#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""哈希计算工具。"""
import argparse, hashlib, json, sys
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")

def main():
    p = argparse.ArgumentParser(description="哈希工具")
    p.add_argument("--text", default="", help="输入文本")
    p.add_argument("--file", default="", help="输入文件")
    p.add_argument("--algo", default="sha256", choices=["md5", "sha1", "sha256", "sha512"], help="算法")
    args = p.parse_args()

    h = hashlib.new(args.algo)
    if args.file:
        import os
        if not os.path.exists(args.file):
            print(json.dumps({"error": f"文件不存在: {args.file}"}, ensure_ascii=False)); sys.exit(1)
        with open(args.file, "rb") as f:
            while chunk := f.read(8192): h.update(chunk)
        size = os.path.getsize(args.file)
        print(json.dumps({"algo": args.algo, "hash": h.hexdigest(), "file": args.file, "size": size}, ensure_ascii=False, indent=2))
    elif args.text:
        h.update(args.text.encode("utf-8"))
        print(json.dumps({"algo": args.algo, "hash": h.hexdigest(), "input_length": len(args.text)}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"error": "需要 --text 或 --file"}, ensure_ascii=False)); sys.exit(1)

if __name__ == "__main__": main()
