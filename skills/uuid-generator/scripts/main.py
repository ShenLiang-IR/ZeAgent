#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UUID 生成工具。"""
import argparse, json, sys, uuid
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")

NAMESPACES = {
    "dns": uuid.NAMESPACE_DNS, "url": uuid.NAMESPACE_URL,
    "oid": uuid.NAMESPACE_OID, "x500": uuid.NAMESPACE_X500,
}

def main():
    p = argparse.ArgumentParser(description="UUID 生成器")
    p.add_argument("--version", type=int, default=4, choices=[4, 5], help="UUID 版本")
    p.add_argument("--count", type=int, default=1, help="生成数量")
    p.add_argument("--namespace", default="", help="命名空间")
    p.add_argument("--name", default="", help="名称（v5）")
    p.add_argument("--uppercase", action="store_true", help="大写输出")
    args = p.parse_args()

    uuids = []
    for _ in range(args.count):
        if args.version == 4:
            u = uuid.uuid4()
        elif args.version == 5:
            if not args.namespace or not args.name:
                print(json.dumps({"error": "v5 需要 --namespace 和 --name"}, ensure_ascii=False)); sys.exit(1)
            ns = NAMESPACES.get(args.namespace.lower())
            if ns is None:
                try: ns = uuid.UUID(args.namespace)
                except: print(json.dumps({"error": f"无效命名空间: {args.namespace}"}, ensure_ascii=False)); sys.exit(1)
            u = uuid.uuid5(ns, args.name)
        val = str(u).upper() if args.uppercase else str(u)
        uuids.append(val)

    print(json.dumps({"uuids": uuids, "count": len(uuids), "version": args.version}, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
