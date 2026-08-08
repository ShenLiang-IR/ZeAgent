#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法律文书生成工具 — 根据参数生成标准格式的法律文书初稿。

在实际部署中，此脚本配合 LLM 完成内容填充；
本脚本提供文书模板框架和格式化输出。
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 文书模板
DOC_TEMPLATES = {
    "complaint": {
        "title": "民事起诉状",
        "sections": [
            {"name": "原告信息", "fields": ["姓名/名称", "性别", "出生日期", "民族", "住址", "联系方式"]},
            {"name": "被告信息", "fields": ["姓名/名称", "住址", "联系方式"]},
            {"name": "诉讼请求", "placeholder": "1. \n2. \n3. "},
            {"name": "事实与理由", "placeholder": ""},
            {"name": "证据和证据来源", "placeholder": "1. \n2. "},
        ],
        "footer": "此致\nXXXX人民法院\n\n具状人：\n年  月  日",
    },
    "answer": {
        "title": "民事答辩状",
        "sections": [
            {"name": "答辩人信息", "fields": ["姓名/名称", "住址", "联系方式"]},
            {"name": "被答辩人信息", "fields": ["姓名/名称", "住址"]},
            {"name": "答辩请求", "placeholder": "1. 驳回原告诉讼请求\n2. "},
            {"name": "事实与理由", "placeholder": ""},
        ],
        "footer": "此致\nXXXX人民法院\n\n答辩人：\n年  月  日",
    },
    "application": {
        "title": "申请书",
        "sections": [
            {"name": "申请人信息", "fields": ["姓名/名称", "住址", "联系方式"]},
            {"name": "申请事项", "placeholder": ""},
            {"name": "事实与理由", "placeholder": ""},
        ],
        "footer": "此致\nXXXX人民法院\n\n申请人：\n年  月  日",
    },
    "opinion": {
        "title": "法律意见书",
        "sections": [
            {"name": "委托方", "placeholder": ""},
            {"name": "审查事项", "placeholder": ""},
            {"name": "基本事实", "placeholder": ""},
            {"name": "法律分析", "placeholder": ""},
            {"name": "法律意见与建议", "placeholder": ""},
            {"name": "声明与保留", "placeholder": "本意见书仅供委托方内部参考，不构成正式法律意见。具体决策请结合实际情况综合判断。"},
        ],
        "footer": "出具人：\n日  期：",
    },
    "notice": {
        "title": "律 师 函",
        "sections": [
            {"name": "致", "placeholder": ""},
            {"name": "委托方", "placeholder": ""},
            {"name": "事实陈述", "placeholder": ""},
            {"name": "法律依据", "placeholder": ""},
            {"name": "律师意见与要求", "placeholder": ""},
            {"name": "后果提示", "placeholder": "如贵方未在规定期限内履行义务，本所将依据委托人授权采取包括诉讼在内的一切法律手段。"},
        ],
        "footer": "XXXX律师事务所\n律师：\n联系电话：\n年  月  日",
    },
    "contract": {
        "title": "合同模板",
        "sections": [
            {"name": "合同各方", "placeholder": "甲方：\n乙方："},
            {"name": "鉴于条款", "placeholder": "鉴于..."},
            {"name": "第一条 合同标的", "placeholder": ""},
            {"name": "第二条 价款与支付方式", "placeholder": ""},
            {"name": "第三条 双方权利义务", "placeholder": ""},
            {"name": "第四条 违约责任", "placeholder": ""},
            {"name": "第五条 争议解决", "placeholder": ""},
            {"name": "第六条 其他约定", "placeholder": ""},
        ],
        "footer": "甲方（盖章）：          乙方（盖章）：\n授权代表：              授权代表：\n日期：                  日期：",
    },
}


def generate_document(doc_type: str, parties: dict, facts: str, claims: str = "") -> str:
    """生成法律文书。"""
    template = DOC_TEMPLATES.get(doc_type, DOC_TEMPLATES["complaint"])

    lines = []
    lines.append(f"\n{'='*50}")
    lines.append(f"  {template['title']}")
    lines.append("="*50)
    lines.append("")

    for section in template["sections"]:
        lines.append(f"\n## {section['name']}")
        lines.append("")

        if "fields" in section:
            for field in section["fields"]:
                value = parties.get(field, "")
                lines.append(f"- **{field}**: {value if value else '（待填写）'}")
        elif "placeholder" in section:
            if section["name"] == "诉讼请求" and claims:
                lines.append(claims)
            elif section["name"] == "事实与理由" and facts:
                lines.append(facts)
            elif section["placeholder"]:
                lines.append(f"（{section['placeholder']}）")
        lines.append("")

    lines.append("\n---")
    lines.append(f"\n{template['footer']}")

    return "\n".join(lines)


def generate_markdown(doc_type: str, parties: dict, facts: str, claims: str = "") -> str:
    """生成 Markdown 格式文书。"""
    template = DOC_TEMPLATES.get(doc_type, DOC_TEMPLATES["complaint"])

    lines = []
    # 文书标题
    lines.append(f"# {template['title']}\n")
    lines.append(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 本文书由 AI 辅助生成，请律师审阅后使用\n")

    for section in template["sections"]:
        lines.append(f"## {section['name']}\n")

        filled = False
        if "fields" in section:
            for field in section["fields"]:
                value = parties.get(field, "")
                if value:
                    lines.append(f"- **{field}**：{value}")
                    filled = True
            if not filled:
                lines.append("（信息待补充）")
        elif "placeholder" in section:
            if section["name"] == "诉讼请求" and claims:
                lines.append(claims)
                filled = True
            elif section["name"] == "事实与理由" and facts:
                lines.append(facts)
                filled = True
            elif section["placeholder"]:
                lines.append(f"*{section['placeholder']}*")

        if not filled and "placeholder" in section:
            lines.append("（待填写）")

        lines.append("")

    lines.append("---\n")
    footer_lines = template["footer"].split("\n")
    for fl in footer_lines:
        if fl.strip():
            lines.append(f"**{fl.strip()}**  ")
        else:
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="法律文书生成工具")
    parser.add_argument("--type", required=True,
                        choices=["complaint", "answer", "application", "opinion", "notice", "contract"],
                        help="文书类型")
    parser.add_argument("--parties", default="{}", help="当事人信息（JSON字符串）")
    parser.add_argument("--facts", default="", help="案件事实描述")
    parser.add_argument("--claims", default="", help="诉讼请求/申请事项")
    parser.add_argument("--output", default="", help="输出文件路径")
    parser.add_argument("--format", default="md", choices=["md", "txt", "docx"], help="输出格式")
    args = parser.parse_args()

    # 解析当事人信息
    try:
        parties = json.loads(args.parties) if isinstance(args.parties, str) else args.parties
    except json.JSONDecodeError:
        parties = {}

    # 生成文书
    if args.format == "md":
        doc_content = generate_markdown(args.type, parties, args.facts, args.claims)
    else:
        doc_content = generate_document(args.type, parties, args.facts, args.claims)

    result = {
        "doc_type": args.type,
        "title": DOC_TEMPLATES.get(args.type, {}).get("title", ""),
        "content": doc_content,
        "generated_at": datetime.now().isoformat(),
        "disclaimer": "本文书由 AI 辅助生成，仅供参考，请律师审阅后使用。",
    }

    if args.output:
        output_path = Path(args.output)
        if not output_path.suffix:
            output_path = output_path.with_suffix(f".{args.format}")
        output_path.write_text(doc_content, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": str(output_path),
                          "doc_type": args.type, "title": result["title"]}, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
