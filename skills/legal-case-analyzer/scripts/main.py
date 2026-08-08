#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法律案例分析工具 — 案情结构化分析、法条匹配、裁判倾向参考。

在实际部署中，此脚本配合 LLM 完成语义分析和法条检索；
本脚本提供结构化解析和基础要素提取框架。
"""
import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 常见案由关键词映射
CASE_TYPE_KEYWORDS = {
    "合同纠纷": ["合同", "买卖", "采购", "供货", "付款", "违约金", "交付"],
    "劳动争议": ["劳动", "工资", "解雇", "开除", "社保", "工伤", "竞业"],
    "侵权纠纷": ["侵权", "损害", "赔偿", "人身", "名誉", "肖像"],
    "婚姻家庭": ["离婚", "抚养", "继承", "财产分割", "子女"],
    "公司股权": ["股权", "股东", "公司", "出资", "转让", "分红"],
    "知识产权": ["专利", "商标", "版权", "著作权", "侵权"],
    "刑事犯罪": ["诈骗", "盗窃", "贪污", "受贿", "故意伤害"],
}

# 常用法条参考库
LAW_DATABASE = {
    "civil": [
        {"law": "民法典第143条", "content": "具备下列条件的民事法律行为有效：(一)行为人具有相应的民事行为能力..."},
        {"law": "民法典第577条", "content": "当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。"},
        {"law": "民法典第584条", "content": "当事人一方不履行合同义务或者履行合同义务不符合约定，造成对方损失的，损失赔偿额应当相当于因违约所造成的损失..."},
        {"law": "民法典第585条", "content": "当事人可以约定一方违约时应当根据违约情况向对方支付一定数额的违约金..."},
        {"law": "民法典第1165条", "content": "行为人因过错侵害他人民事权益造成损害的，应当承担侵权责任。"},
    ],
    "labor": [
        {"law": "劳动合同法第39条", "content": "劳动者有下列情形之一的，用人单位可以解除劳动合同..."},
        {"law": "劳动合同法第46条", "content": "有下列情形之一的，用人单位应当向劳动者支付经济补偿..."},
        {"law": "劳动合同法第47条", "content": "经济补偿按劳动者在本单位工作的年限，每满一年支付一个月工资的标准向劳动者支付..."},
        {"law": "劳动合同法第87条", "content": "用人单位违反本法规定解除或者终止劳动合同的，应当依照本法第四十七条规定的经济补偿标准的二倍向劳动者支付赔偿金。"},
    ],
    "commercial": [
        {"law": "公司法第20条", "content": "公司股东应当遵守法律、行政法规和公司章程，依法行使股东权利，不得滥用股东权利损害公司或者其他股东的利益..."},
        {"law": "公司法第71条", "content": "有限责任公司的股东之间可以相互转让其全部或者部分股权..."},
    ],
    "criminal": [
        {"law": "刑法第266条", "content": "诈骗公私财物，数额较大的，处三年以下有期徒刑、拘役或者管制..."},
        {"law": "刑法第382条", "content": "国家工作人员利用职务上的便利，侵吞、窃取、骗取或者以其他手段非法占有公共财物的，是贪污罪。"},
    ],
}


def identify_case_type(text: str) -> str:
    """根据案情描述自动识别案件类型。"""
    scores = {}
    for case_type, keywords in CASE_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[case_type] = score
    if not scores:
        return "其他纠纷"
    return max(scores, key=scores.get)


def extract_parties(text: str) -> list:
    """提取当事人信息。"""
    patterns = [
        r"([\u4e00-\u9fff]{2,6}(公司|集团|企业|厂|店|行))",
        r"([\u4e00-\u9fff]{2,4}(先生|女士|同志))",
        r"(原告[:：]?\s*[\u4e00-\u9fff]{2,12})",
        r"(被告[:：]?\s*[\u4e00-\u9fff]{2,12})",
    ]
    parties = set()
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for m in matches:
            party = m[0] if isinstance(m, tuple) else m
            if len(party) >= 2:
                parties.add(party)
    return list(parties)[:10]


def extract_timeline(text: str) -> list:
    """提取时间线信息。"""
    date_pattern = r"(\d{4}[-年]\d{1,2}[-月]\d{1,2}[日]?)"
    dates = re.findall(date_pattern, text)
    if not dates:
        # 尝试匹配相对日期
        rel_pattern = r"(\d+)个?[月天年前]"
        dates = re.findall(rel_pattern, text)

    timeline = []
    # 尝试将日期与事件关联
    sentences = re.split(r"[。；;]", text)
    for sent in sentences:
        date_match = re.search(date_pattern, sent)
        if date_match and len(sent) > 10:
            timeline.append(f"{date_match.group(1)}: {sent.strip()[:50]}...")

    if not timeline:
        timeline = [f"待解析时间信息，原文: {text[:100]}..."]

    return timeline[:10]


def match_laws(category: str, text: str) -> list:
    """匹配相关法条。"""
    relevant = []
    laws = LAW_DATABASE.get(category, LAW_DATABASE.get("civil", []))
    for law in laws:
        # 简单关键词匹配
        law_keywords = re.findall(r"[\u4e00-\u9fff]{2,8}", law["content"])
        overlap = sum(1 for kw in law_keywords if kw in text)
        if overlap >= 2:
            relevant.append(law)
    if not relevant:
        # 默认返回该类别的基础法条
        relevant = laws[:3]
    return relevant[:5]


def extract_key_facts(text: str) -> list:
    """提取关键事实要素。"""
    facts = []

    # 金额提取
    money_pattern = r"(\d+\.?\d*)\s*(万元|元|美元|欧元|日元)"
    money_matches = re.findall(money_pattern, text)
    if money_matches:
        facts.append(f"涉及金额: {', '.join(f'{m[0]}{m[1]}' for m in money_matches[:3])}")

    # 行为关键词
    action_keywords = {
        "违约": "存在违约行为",
        "未履行": "未履行合同义务",
        "拖欠": "存在拖欠款项",
        "擅自": "存在擅自行为",
        "损害": "造成损害后果",
        "解除": "涉及合同/关系解除",
        "侵权": "涉及侵权行为",
    }
    for kw, desc in action_keywords.items():
        if kw in text:
            facts.append(desc)

    return facts[:8]


def main():
    parser = argparse.ArgumentParser(description="法律案例分析工具")
    parser.add_argument("--case", required=True, help="案情描述文本")
    parser.add_argument("--category", default="civil",
                        choices=["civil", "criminal", "administrative", "commercial", "labor"],
                        help="案件类别")
    parser.add_argument("--keywords", default="", help="检索关键词（逗号分隔）")
    parser.add_argument("--output", default="", help="输出文件路径")
    args = parser.parse_args()

    text = args.case

    # 分析
    case_type = identify_case_type(text)
    parties = extract_parties(text)
    timeline = extract_timeline(text)
    key_facts = extract_key_facts(text)
    laws = match_laws(args.category, text)

    # 争议焦点识别
    dispute_signals = {
        "违约责任": ["违约", "不履行", "延迟"],
        "赔偿金额": ["赔偿", "损失", "金额"],
        "合同效力": ["无效", "撤销", "解除"],
        "证据问题": ["证据", "证明", "举证"],
        "主体资格": ["资格", "授权", "代理"],
    }
    dispute_focus = []
    for focus, signals in dispute_signals.items():
        if any(s in text for s in signals):
            dispute_focus.append(focus)

    result = {
        "case_type": case_type,
        "category": args.category,
        "analyzed_at": datetime.now().isoformat(),
        "key_elements": {
            "parties": parties,
            "facts": key_facts,
            "timeline": timeline,
        },
        "relevant_laws": laws,
        "dispute_focus": dispute_focus or ["需进一步分析"],
        "tendency": f"本案属{case_type}，建议重点关注{'、'.join(dispute_focus[:3] if dispute_focus else ['证据收集'])}等方面。",
        "disclaimer": "本分析仅供参考，不构成法律意见。具体案件请咨询专业律师。",
    }

    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(output_json)


if __name__ == "__main__":
    main()
