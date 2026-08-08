#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文本差异比较工具。"""
import argparse, difflib, json, sys
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")

def main():
    p = argparse.ArgumentParser(description="文本差异比较")
    p.add_argument("--old", required=True, help="旧文本")
    p.add_argument("--new", required=True, help="新文本")
    args = p.parse_args()

    old_lines = args.old.splitlines(keepends=False)
    new_lines = args.new.splitlines(keepends=False)

    diff = []
    added = removed = unchanged = 0
    for line in difflib.unified_diff(old_lines, new_lines, lineterm="", n=3):
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            diff.append({"type": "+", "content": line[1:]}); added += 1
        elif line.startswith("-"):
            diff.append({"type": "-", "content": line[1:]}); removed += 1
        elif line.startswith(" "):
            diff.append({"type": " ", "content": line[1:]}); unchanged += 1

    print(json.dumps({"diff": diff, "added": added, "removed": removed, "unchanged": unchanged}, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
