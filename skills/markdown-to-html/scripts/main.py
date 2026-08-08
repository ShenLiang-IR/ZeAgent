#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 转 HTML — 纯标准库实现。"""
import argparse, json, re, sys
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")

def md_to_html(text: str) -> str:
    lines = text.split("\n")
    html = []
    in_code = False
    in_list = False
    for line in lines:
        if line.strip().startswith("```"):
            if in_code:
                html.append("</code></pre>"); in_code = False
            else:
                lang = line.strip()[3:]
                html.append(f'<pre><code class="{lang}">'); in_code = True
            continue
        if in_code:
            html.append(line.replace("<", "&lt;").replace(">", "&gt;")); continue
        # 表格（简单处理）
        if "|" in line and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            row = "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
            html.append(row); continue
        # 标题
        m = re.match(r"^(#{1,6})\s+(.+)", line)
        if m:
            level = len(m.group(1))
            html.append(f"<h{level}>{m.group(2)}</h{level}>"); continue
        # 列表
        m = re.match(r"^[\-\*]\s+(.+)", line)
        if m:
            if not in_list: html.append("<ul>"); in_list = True
            html.append(f"<li>{m.group(1)}</li>"); continue
        elif in_list:
            html.append("</ul>"); in_list = False
        # 空行
        if not line.strip():
            html.append(""); continue
        # 普通段落
        l = line
        l = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", l)
        l = re.sub(r"\*(.+?)\*", r"<em>\1</em>", l)
        l = re.sub(r"`(.+?)`", r"<code>\1</code>", l)
        l = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', l)
        html.append(f"<p>{l}</p>")
    if in_list: html.append("</ul>")
    if in_code: html.append("</code></pre>")
    return "\n".join(html)

def main():
    p = argparse.ArgumentParser(description="Markdown 转 HTML")
    p.add_argument("--text", default="", help="Markdown 文本")
    p.add_argument("--file", default="", help="输入文件")
    p.add_argument("--output", default="", help="输出文件")
    p.add_argument("--full-page", action="store_true", help="完整 HTML 页面")
    args = p.parse_args()

    if args.file:
        from pathlib import Path
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        print(json.dumps({"error": "需要 --text 或 --file"}, ensure_ascii=False)); sys.exit(1)

    html = md_to_html(text)
    if args.full_page:
        html = f"<!DOCTYPE html>\n<html>\n<head><meta charset=\"utf-8\"></head>\n<body>\n{html}\n</body>\n</html>"
    if args.output:
        from pathlib import Path; Path(args.output).write_text(html, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(html)

if __name__ == "__main__": main()
