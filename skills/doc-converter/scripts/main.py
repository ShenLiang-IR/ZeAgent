#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档格式转换工具。"""
import argparse, csv, json, sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def csv_to_json(content: str) -> str:
    import io
    reader = csv.DictReader(io.StringIO(content))
    rows = [dict(r) for r in reader]
    return json.dumps(rows, ensure_ascii=False, indent=2)


def json_to_csv(content: str) -> str:
    data = json.loads(content)
    if not isinstance(data, list) or not data:
        return ""
    import io
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(data[0].keys()))
    writer.writeheader()
    writer.writerows(data)
    return out.getvalue()


def md_to_html(content: str) -> str:
    lines = content.split("\n")
    html = []
    for line in lines:
        import re
        m = re.match(r"^(#{1,6})\s+(.+)", line)
        if m:
            html.append(f"<h{len(m.group(1))}>{m.group(2)}</h{len(m.group(1))}>")
        elif line.strip():
            l = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            html.append(f"<p>{l}</p>")
        else:
            html.append("")
    return "\n".join(html)


def main():
    parser = argparse.ArgumentParser(description="文档格式转换工具")
    parser.add_argument("--input", required=True, help="输入文件路径")
    parser.add_argument("--from", dest="from_fmt", required=True, help="输入格式")
    parser.add_argument("--to", dest="to_fmt", required=True, help="输出格式")
    parser.add_argument("--output", default="", help="输出文件路径")
    args = parser.parse_args()

    content = Path(args.input).read_text(encoding="utf-8")

    convert_map = {
        ("csv", "json"): csv_to_json,
        ("json", "csv"): json_to_csv,
        ("markdown", "html"): md_to_html,
    }
    converter = convert_map.get((args.from_fmt.lower(), args.to_fmt.lower()))
    if not converter:
        print(json.dumps({"error": f"不支持 {args.from_fmt} → {args.to_fmt} 转换"}, ensure_ascii=False))
        sys.exit(1)

    try:
        result = converter(content)
        if args.output:
            Path(args.output).write_text(result, encoding="utf-8")
            print(json.dumps({"success": True, "output_file": args.output, "size": len(result)}, ensure_ascii=False))
        else:
            print(result)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
