#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 文本提取工具 — 从 PDF 提取文本内容。"""
import argparse, json, sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="PDF 文本提取工具")
    parser.add_argument("--file", required=True, help="PDF 文件路径")
    parser.add_argument("--output", default="", help="输出文件路径")
    parser.add_argument("--format", default="text", choices=["text", "json"], help="输出格式")
    parser.add_argument("--page-start", type=int, default=0, help="起始页码")
    parser.add_argument("--page-end", type=int, default=-1, help="结束页码")
    args = parser.parse_args()

    try:
        import fitz  # PyMuPDF
    except ImportError:
        print(json.dumps({"error": "需要 PyMuPDF: pip install pymupdf"}, ensure_ascii=False))
        sys.exit(1)

    try:
        doc = fitz.open(args.file)
        total_pages = len(doc)
        end = args.page_end if args.page_end >= 0 else total_pages
        pages = []
        for i in range(args.page_start, min(end, total_pages)):
            page = doc[i]
            text = page.get_text()
            pages.append({"page": i + 1, "text": text})

        if args.format == "json":
            result = json.dumps({"file": args.file, "total_pages": total_pages, "pages": pages}, ensure_ascii=False, indent=2)
        else:
            result = "\n\n--- Page Break ---\n\n".join(p["text"] for p in pages)

        if args.output:
            Path(args.output).write_text(result, encoding="utf-8")
            print(json.dumps({"success": True, "pages_extracted": len(pages), "output_file": args.output}, ensure_ascii=False))
        else:
            print(result)
    except FileNotFoundError:
        print(json.dumps({"error": f"文件不存在: {args.file}"}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
