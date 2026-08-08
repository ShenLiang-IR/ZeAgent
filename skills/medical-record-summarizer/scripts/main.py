#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""病历摘要生成工具 — 从病历文本提取关键信息，生成结构化摘要。

在实际部署中，此脚本配合 LLM 完成语义理解和医学知识推理；
本脚本提供结构化提取框架和关键信息识别。
"""
import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 常见医学实体模式
MEDICAL_PATTERNS = {
    "age_gender": r"(患者|病人)[:：]?\s*([\u4e00-\u9fff]{1,4})[,，]?\s*(\d{1,3})\s*岁",
    "chief_complaint": r"(主诉|因)[:：]?\s*([\u4e00-\u9fff，,，、\d]{2,50})",
    "diagnosis": r"(诊断|确诊)[:：]?\s*([\u4e00-\u9fff，,；;、\d\s\+\-\.]{2,100})",
    "medication": r"([\u4e00-\u9fff]{2,8}(片|胶囊|注射液|颗粒|口服液|滴丸|分散片|缓释片))\s*(\d+\.?\d*)\s*(mg|g|ml|片|粒|支)",
    "vital_sign": r"(体温|血压|心率|呼吸)[:：]?\s*(\d+\.?\d*)\s*[°℃]?\s*[\/／]?\s*(\d+\.?\d*)?",
    "lab_value": r"([\u4e00-\u9fff()（）]{2,10})[:：]?\s*(\d+\.?\d*)\s*([\u4e00-\u9fff\/／μL]+/?)",
    "surgery": r"([\u4e00-\u9fff]{3,8}(术|切除术|修补术|置换术|移植术|成形术|吻合术))",
    "allergy": r"(过敏)[:：]?\s*([\u4e00-\u9fff，,；;、\d]{2,30})",
    "date_event": r"(\d{4}[-年]\d{1,2}[-月]\d{1,2}[日]?)",
}

# SOAP 结构模板
SOAP_TEMPLATE = {
    "subjective": {"chief_complaint": "", "history_present": "", "past_history": ""},
    "objective": {"vital_signs": {}, "physical_exam": "", "lab_results": [], "imaging": ""},
    "assessment": {"primary_diagnosis": "", "differential": [], "severity": ""},
    "plan": {"medications": [], "procedures": [], "follow_up": "", "patient_education": ""},
}


def extract_basic_info(text: str) -> dict:
    """提取基本信息。"""
    info = {}
    match = re.search(MEDICAL_PATTERNS["age_gender"], text)
    if match:
        info["gender"] = match.group(2)
        info["age"] = int(match.group(3))
    return info


def extract_chief_complaint(text: str) -> str:
    """提取主诉。"""
    match = re.search(MEDICAL_PATTERNS["chief_complaint"], text)
    if match:
        return match.group(2).strip()
    # 尝试从前两句话提取
    sentences = re.split(r"[。；;]", text)
    for sent in sentences[:3]:
        if any(kw in sent for kw in ["痛", "不适", "发热", "咳嗽", "呕吐", "头晕", "乏力"]):
            return sent.strip()[:100]
    return ""


def extract_diagnosis(text: str) -> list:
    """提取诊断信息。"""
    diagnoses = []
    matches = re.findall(MEDICAL_PATTERNS["diagnosis"], text)
    for match in matches:
        diag_text = match[1] if isinstance(match, tuple) else match
        # 分割多个诊断
        parts = re.split(r"[；;,，、]", diag_text)
        for part in parts:
            part = part.strip()
            if part and len(part) >= 2:
                diagnoses.append(part)
    return diagnoses[:5]


def extract_medications(text: str) -> list:
    """提取药物信息。"""
    meds = []
    matches = re.findall(MEDICAL_PATTERNS["medication"], text)
    for match in matches:
        name = match[0]
        dosage = match[2] if len(match) > 2 else ""
        unit = match[3] if len(match) > 3 else ""
        if name:
            meds.append({"name": name, "dosage": f"{dosage}{unit}" if dosage else "未指定"})
    return meds[:10]


def extract_vital_signs(text: str) -> dict:
    """提取生命体征。"""
    vitals = {}
    matches = re.findall(MEDICAL_PATTERNS["vital_sign"], text)
    for match in matches:
        name = match[0]
        value = match[1]
        extra = match[2] if len(match) > 2 else ""
        if name == "血压" and extra:
            vitals[name] = f"{value}/{extra} mmHg"
        elif name == "体温":
            vitals[name] = f"{value}°C"
        elif name == "心率":
            vitals[name] = f"{value} 次/分"
        elif name == "呼吸":
            vitals[name] = f"{value} 次/分"
        else:
            vitals[name] = value
    return vitals


def extract_lab_results(text: str) -> list:
    """提取实验室检查结果。"""
    labs = []
    matches = re.findall(MEDICAL_PATTERNS["lab_value"], text)
    seen = set()
    for match in matches:
        name = match[0]
        value = match[1]
        unit = match[2] if len(match) > 2 else ""
        if name not in seen:
            labs.append({"test": name, "value": f"{value}{unit}", "flag": ""})
            seen.add(name)
    return labs[:10]


def extract_surgeries(text: str) -> list:
    """提取手术信息。"""
    surgeries = re.findall(MEDICAL_PATTERNS["surgery"], text)
    return list(set(surgeries))[:5]


def extract_allergies(text: str) -> list:
    """提取过敏信息。"""
    match = re.search(MEDICAL_PATTERNS["allergy"], text)
    if match:
        return [a.strip() for a in re.split(r"[,，、]", match.group(2)) if a.strip()]
    return []


def generate_soap(text: str) -> dict:
    """生成 SOAP 格式摘要。"""
    soap = {
        "subjective": {
            "chief_complaint": extract_chief_complaint(text),
            "history_present": "",
            "past_history": "",
        },
        "objective": {
            "vital_signs": extract_vital_signs(text),
            "lab_results": extract_lab_results(text),
        },
        "assessment": {
            "primary_diagnosis": ", ".join(extract_diagnosis(text)[:3]),
            "differential": [],
            "severity": "",
        },
        "plan": {
            "medications": extract_medications(text),
            "procedures": extract_surgeries(text),
            "follow_up": "",
            "patient_education": "",
        },
    }
    return soap


def generate_structured(text: str) -> dict:
    """生成结构化摘要。"""
    return {
        "basic_info": extract_basic_info(text),
        "chief_complaint": extract_chief_complaint(text),
        "diagnosis": extract_diagnosis(text),
        "medications": extract_medications(text),
        "vital_signs": extract_vital_signs(text),
        "lab_results": extract_lab_results(text),
        "surgeries": extract_surgeries(text),
        "allergies": extract_allergies(text),
    }


def generate_brief(text: str) -> dict:
    """生成简洁摘要。"""
    diagnoses = extract_diagnosis(text)
    meds = extract_medications(text)
    complaint = extract_chief_complaint(text)

    summary = f"患者{'，'.join(f'{k}={v}' for k,v in extract_basic_info(text).items())}。"
    if complaint:
        summary += f"主诉：{complaint}。"
    if diagnoses:
        summary += f"诊断：{'、'.join(diagnoses[:3])}。"
    if meds:
        summary += f"用药：{'、'.join(m['name'] for m in meds[:3])}。"

    return {"summary": summary, "key_points": diagnoses + [m["name"] for m in meds]}


def main():
    parser = argparse.ArgumentParser(description="病历摘要生成工具")
    parser.add_argument("--text", default="", help="病历文本内容")
    parser.add_argument("--file", default="", help="病历文件路径")
    parser.add_argument("--format", default="structured", choices=["soap", "structured", "brief"], help="摘要格式")
    parser.add_argument("--extract", default="all", help="提取内容")
    parser.add_argument("--output", default="", help="输出文件路径")
    args = parser.parse_args()

    # 读取文本
    if args.text:
        text = args.text
    elif args.file:
        try:
            text = Path(args.file).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            print(json.dumps({"error": f"文件不存在: {args.file}"}, ensure_ascii=False))
            sys.exit(1)
    else:
        print(json.dumps({"error": "需要 --text 或 --file 参数"}, ensure_ascii=False))
        sys.exit(1)

    # 生成摘要
    if args.format == "soap":
        summary = generate_soap(text)
    elif args.format == "brief":
        summary = generate_brief(text)
    else:
        summary = generate_structured(text)

    result = {
        "format": args.format,
        "summary": summary,
        "text_length": len(text),
        "generated_at": datetime.now().isoformat(),
        "disclaimer": "本摘要由AI辅助生成，仅供参考，不能替代专业医疗判断。请以临床医生诊断为准。",
    }

    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(output_json)


if __name__ == "__main__":
    main()
