#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合同审查工具 — 分析合同条款、识别风险、提供修改建议。

支持 txt/md 文件读取，docx 需安装 python-docx。
在实际部署中，此脚本配合 LLM 完成语义分析；本脚本提供结构化解析框架。
"""
import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 常见合同风险模式
RISK_PATTERNS = {
    "penalty": {
        "patterns": [
            r"违约金.*?(\d+)%",
            r"罚款.*?(\d+\.?\d*)万元",
            r"赔偿.*?(\d+)倍",
        ],
        "label": "违约金条款",
        "advice": "违约金比例建议不超过实际损失的20%-30%，过高可能被法院调减",
    },
    "unilateral": {
        "patterns": [
            r"甲方(有权|可以).*?单方面",
            r"乙方(不得|无权).*?异议",
            r"最终解释权归.*?所有",
        ],
        "label": "单方权利条款",
        "advice": "单方权利条款可能被认定为格式条款无效，建议增加双方协商机制",
    },
    "jurisdiction": {
        "patterns": [
            r"管辖.*?法院.*?甲方.*?所在地",
            r"仲裁.*?委员会",
        ],
        "label": "争议解决条款",
        "advice": "管辖约定应公平合理，建议选择合同履行地或被告所在地",
    },
    "ip_ownership": {
        "patterns": [
            r"知识产权.*?归.*?(甲方|委托方)",
            r"所有.*?成果.*?归属",
        ],
        "label": "知识产权归属",
        "advice": "知识产权归属条款需明确约定权利范围、使用限制和转让条件",
    },
    "confidentiality": {
        "patterns": [
            r"保密.*?期限.*?(\d+)年",
            r"保密.*?义务.*?永久",
        ],
        "label": "保密条款",
        "advice": "保密期限应合理设定，永久保密条款执行难度大",
    },
    "force_majeure": {
        "patterns": [
            r"(不可抗力|免责).*?不包括",
            r"无论.*?任何.*?原因.*?均应",
        ],
        "label": "不可抗力/免责条款",
        "advice": "免责条款不应排除法定不可抗力情形",
    },
}

CONTRACT_TYPE_HINTS = {
    "sales": ["买卖", "采购", "销售", "供货", "货物", "价款"],
    "lease": ["租赁", "出租", "承租", "租金", "押金"],
    "labor": ["劳动", "聘用", "雇佣", "工资", "社保", "竞业"],
    "service": ["服务", "委托", "开发", "咨询", "外包"],
    "nda": ["保密", "机密", "NDA", "商业秘密", "非披露"],
    "partnership": ["合伙", "合资", "合作", "股权", "投资"],
}


def detect_contract_type(text: str) -> str:
    """自动识别合同类型。"""
    scores = {}
    text_lower = text.lower()
    for ctype, keywords in CONTRACT_TYPE_HINTS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[ctype] = score
    if not scores:
        return "general"
    return max(scores, key=scores.get)


def scan_risks(text: str, focus: str = "all") -> list:
    """扫描合同文本中的风险点。"""
    results = []
    for risk_key, risk_config in RISK_PATTERNS.items():
        if focus not in ("all", "risk") and risk_key != focus:
            continue
        matches = []
        for pattern in risk_config["patterns"]:
            found = re.findall(pattern, text, re.IGNORECASE)
            matches.extend(found)
        if matches:
            results.append({
                "clause": risk_config["label"],
                "risk_score": min(len(matches) * 2, 10),
                "issues": [f"匹配到 {len(matches)} 处潜在风险模式"],
                "suggestions": [risk_config["advice"]],
                "matched_texts": matches[:3],
            })
    return results


def calculate_risk_level(risks: list) -> str:
    """计算整体风险等级。"""
    if not risks:
        return "low"
    avg_score = sum(r["risk_score"] for r in risks) / len(risks)
    if avg_score >= 7:
        return "high"
    elif avg_score >= 4:
        return "medium"
    return "low"


def read_file_content(filepath: str) -> str:
    """读取文件内容，支持 txt/md/docx。"""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {filepath}")

    suffix = path.suffix.lower()
    if suffix == ".docx":
        try:
            from docx import Document
            doc = Document(filepath)
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            return path.read_text(encoding="utf-8", errors="replace")
    else:
        return path.read_text(encoding="utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description="合同审查工具")
    parser.add_argument("--file", required=True, help="合同文件路径（txt/md/docx）")
    parser.add_argument("--type", default="auto", help="合同类型：auto/sales/lease/labor/service/nda/partnership")
    parser.add_argument("--focus", default="all", choices=["all", "risk", "compliance", "balance"], help="审查重点")
    parser.add_argument("--output", default="", help="输出报告路径（可选）")
    args = parser.parse_args()

    try:
        content = read_file_content(args.file)
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": f"读取文件失败: {e}"}, ensure_ascii=False))
        sys.exit(1)

    # 识别合同类型
    contract_type = args.type if args.type != "auto" else detect_contract_type(content)

    # 扫描风险
    risks = scan_risks(content, args.focus)
    risk_level = calculate_risk_level(risks)

    # 统计基本信息
    clauses_count = len(re.findall(r"第[一二三四五六七八九十\d]+条", content))
    char_count = len(content)

    result = {
        "contract_type": contract_type,
        "risk_level": risk_level,
        "file_path": args.file,
        "stats": {
            "char_count": char_count,
            "clauses_detected": clauses_count,
            "risks_found": len(risks),
        },
        "sections": risks,
        "summary": f"合同类型：{contract_type}，整体风险等级：{risk_level}，共发现 {len(risks)} 处需关注条款。",
    }

    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(output_json)


if __name__ == "__main__":
    main()
