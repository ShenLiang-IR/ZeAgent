#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""医学报告解析工具 — 解析化验单/影像报告/体检报告，提取异常指标。

在实际部署中，报告内容由 OCR/LLM 提取后传入本脚本；
本脚本提供指标解析和异常判定框架。
"""
import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 常见化验指标参考范围（成人，不同实验室可能有差异）
LAB_REFERENCE = {
    # 血常规
    "WBC": {"name": "白细胞计数", "unit": "×10⁹/L", "low": 3.5, "high": 9.5},
    "RBC": {"name": "红细胞计数", "unit": "×10¹²/L", "low": 4.3, "high": 5.8},
    "HGB": {"name": "血红蛋白", "unit": "g/L", "low": 130, "high": 175},
    "PLT": {"name": "血小板计数", "unit": "×10⁹/L", "low": 125, "high": 350},
    "NEUT": {"name": "中性粒细胞百分比", "unit": "%", "low": 40, "high": 75},
    "LYMPH": {"name": "淋巴细胞百分比", "unit": "%", "low": 20, "high": 50},
    # 肝功能
    "ALT": {"name": "丙氨酸氨基转移酶", "unit": "U/L", "low": 0, "high": 40},
    "AST": {"name": "天门冬氨酸氨基转移酶", "unit": "U/L", "low": 0, "high": 40},
    "GGT": {"name": "γ-谷氨酰转移酶", "unit": "U/L", "low": 0, "high": 50},
    "TBIL": {"name": "总胆红素", "unit": "μmol/L", "low": 3.4, "high": 17.1},
    "ALB": {"name": "白蛋白", "unit": "g/L", "low": 35, "high": 55},
    # 肾功能
    "Cr": {"name": "肌酐", "unit": "μmol/L", "low": 44, "high": 133},
    "BUN": {"name": "尿素氮", "unit": "mmol/L", "low": 2.9, "high": 8.2},
    "UA": {"name": "尿酸", "unit": "μmol/L", "low": 150, "high": 420},
    # 血脂
    "TC": {"name": "总胆固醇", "unit": "mmol/L", "low": 2.8, "high": 5.2},
    "TG": {"name": "甘油三酯", "unit": "mmol/L", "low": 0.56, "high": 1.7},
    "HDL": {"name": "高密度脂蛋白胆固醇", "unit": "mmol/L", "low": 1.0, "high": 1.9},
    "LDL": {"name": "低密度脂蛋白胆固醇", "unit": "mmol/L", "low": 0, "high": 3.4},
    # 血糖
    "GLU": {"name": "空腹血糖", "unit": "mmol/L", "low": 3.9, "high": 6.1},
    "HbA1c": {"name": "糖化血红蛋白", "unit": "%", "low": 4.0, "high": 6.0},
    # 肿瘤标志物
    "CEA": {"name": "癌胚抗原", "unit": "ng/mL", "low": 0, "high": 5.0},
    "AFP": {"name": "甲胎蛋白", "unit": "ng/mL", "low": 0, "high": 7.0},
    "CA199": {"name": "糖类抗原19-9", "unit": "U/mL", "low": 0, "high": 27.0},
}

# 异常解读提示
INTERPRETATION_HINTS = {
    "WBC_high": "偏高，可能提示感染、炎症、应激状态或血液系统疾病",
    "WBC_low": "偏低，可能提示病毒感染、骨髓抑制或药物影响",
    "ALT_high": "偏高，可能提示肝细胞损伤、肝炎或药物性肝损伤",
    "ALT_low": "偏低，一般无临床意义",
    "AST_high": "偏高，可能提示肝细胞损伤、心肌损伤或肌肉损伤",
    "Cr_high": "偏高，可能提示肾功能减退，建议进一步检查",
    "TC_high": "偏高，心血管疾病风险增加，建议控制饮食和运动",
    "TG_high": "偏高，可能与饮食、代谢综合征相关",
    "GLU_high": "偏高，需排除糖尿病，建议复查空腹血糖和HbA1c",
    "GLU_low": "偏低，可能为低血糖，需关注饮食和用药情况",
    "HGB_low": "偏低，可能为贫血，建议进一步查明原因",
    "PLT_low": "偏低，可能提示血小板减少，需关注出血风险",
    "UA_high": "偏高，可能为高尿酸血症，增加痛风风险",
    "LDL_high": "偏高，心血管疾病风险因素，建议控制",
    "CEA_high": "偏高，需结合临床，单一指标升高不具诊断意义",
}


def parse_lab_items(text: str) -> list:
    """从文本中提取化验项目。"""
    items = []

    # 匹配模式：项目名 + 数值 + 单位 + 参考范围
    # 例如：白细胞计数(WBC)  12.5  ×10⁹/L  3.5-9.5  ↑
    patterns = [
        r"([\u4e00-\u9fff()（）a-zA-Z\d]+)\s+(\d+\.?\d*)\s*([\u4e00-\u9fffμ×\/LlgmolU·\.\%\d]+)?\s*[\u2191\u2193↑↓]?",
        r"([\u4e00-\u9fff()（）]+)[:：]\s*(\d+\.?\d*)",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            name = match[0].strip()
            value = float(match[1])
            unit = match[2].strip() if len(match) > 2 and match[2] else ""
            if name and name not in [item["name"] for item in items]:
                items.append({
                    "raw_name": name,
                    "value": value,
                    "unit": unit,
                })

    return items


def match_reference(items: list) -> list:
    """匹配参考范围并判断异常。"""
    results = []
    for item in items:
        name = item["raw_name"]
        value = item["value"]
        unit = item["unit"]

        # 尝试匹配已知指标
        ref_info = None
        matched_key = None
        for key, info in LAB_REFERENCE.items():
            if key.upper() in name.upper() or info["name"] in name:
                ref_info = info
                matched_key = key
                break

        result_item = {
            "name": name,
            "value": value,
            "unit": unit or (ref_info["unit"] if ref_info else ""),
            "reference": "",
            "flag": "",
            "interpretation": "",
        }

        if ref_info:
            low, high = ref_info["low"], ref_info["high"]
            result_item["reference"] = f"{low}-{high}{' ' + ref_info['unit'] if not unit else ''}"

            if value > high:
                result_item["flag"] = "H"
                hint_key = f"{matched_key}_high"
                result_item["interpretation"] = INTERPRETATION_HINTS.get(
                    hint_key, f"高于参考范围上限({high})"
                )
            elif value < low:
                result_item["flag"] = "L"
                hint_key = f"{matched_key}_low"
                result_item["interpretation"] = INTERPRETATION_HINTS.get(
                    hint_key, f"低于参考范围下限({low})"
                )
            else:
                result_item["flag"] = ""
                result_item["interpretation"] = "在正常范围内"

        results.append(result_item)

    return results


def generate_summary(items: list) -> str:
    """生成报告摘要。"""
    total = len(items)
    abnormal = [item for item in items if item["flag"] in ("H", "L")]
    abnormal_count = len(abnormal)

    if abnormal_count == 0:
        return f"共检测{total}项，各项指标均在正常范围内。"

    high_items = [item for item in abnormal if item["flag"] == "H"]
    low_items = [item for item in abnormal if item["flag"] == "L"]

    parts = [f"共检测{total}项，异常{abnormal_count}项。"]

    if high_items:
        parts.append(f"偏高项目：{'、'.join(item['name'] for item in high_items[:5])}")
    if low_items:
        parts.append(f"偏低项目：{'、'.join(item['name'] for item in low_items[:5])}")

    parts.append("建议咨询医生进行专业解读。")
    return "；".join(parts)


def main():
    parser = argparse.ArgumentParser(description="医学报告解析工具")
    parser.add_argument("--file", required=True, help="报告文件路径")
    parser.add_argument("--type", default="lab", choices=["lab", "imaging", "physical"], help="报告类型")
    parser.add_argument("--reference", default="true", help="是否显示参考范围")
    parser.add_argument("--output", default="", help="输出文件路径")
    args = parser.parse_args()

    try:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        print(json.dumps({"error": f"文件不存在: {args.file}"}, ensure_ascii=False))
        sys.exit(1)

    show_ref = args.reference.lower() != "false"

    items = parse_lab_items(text)
    analyzed_items = match_reference(items)
    abnormal_count = sum(1 for item in analyzed_items if item["flag"] in ("H", "L"))

    # 如果不显示参考范围，移除reference字段
    if not show_ref:
        for item in analyzed_items:
            item.pop("reference", None)

    result = {
        "report_type": args.type,
        "file": args.file,
        "analyzed_at": datetime.now().isoformat(),
        "items": analyzed_items,
        "total_count": len(analyzed_items),
        "abnormal_count": abnormal_count,
        "summary": generate_summary(analyzed_items),
        "disclaimer": "本解析结果仅供参考，不能替代专业医生诊断。请以临床医生意见为准。",
    }

    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(output_json)


if __name__ == "__main__":
    main()
