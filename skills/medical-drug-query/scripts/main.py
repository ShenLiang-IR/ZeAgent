#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""药品信息查询工具 — 结构化药品信息检索和格式化输出。

在实际部署中，药品数据由 LLM 通过搜索或 RAG 知识库获取后传入；
本脚本提供结构化解析和格式化输出框架。
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 常用药品基础信息库（示例数据，实际需对接药典/说明书数据库）
DRUG_DATABASE = {
    "阿莫西林": {
        "generic_name": "Amoxicillin",
        "category": "抗生素 / 青霉素类",
        "indications": [
            "上呼吸道感染（咽炎、扁桃体炎）",
            "下呼吸道感染（支气管炎、肺炎）",
            "泌尿生殖道感染",
            "皮肤软组织感染",
            "幽门螺杆菌感染（联合用药）"
        ],
        "dosage": {
            "adult": "每次0.5g，每6-8小时1次",
            "children": "按体重20-40mg/kg/日，分3次服用",
            "elderly": "同成人剂量，肾功能不全者需调整"
        },
        "adverse_reactions": [
            "胃肠道反应（恶心、呕吐、腹泻）",
            "皮疹、荨麻疹等过敏反应",
            "偶见肝功能异常",
            "罕见：过敏性休克、伪膜性肠炎"
        ],
        "contraindications": [
            "青霉素过敏者禁用",
            "传染性单核细胞增多症患者禁用"
        ],
        "interactions": [
            "丙磺舒可升高阿莫西林血药浓度",
            "与甲氨蝶呤合用可增加毒性",
            "与口服避孕药合用可能降低避孕效果"
        ],
        "category": "处方药（部分剂型为非处方药）"
    },
    "布洛芬": {
        "generic_name": "Ibuprofen",
        "category": "非甾体抗炎药 (NSAID)",
        "indications": [
            "轻至中度疼痛（头痛、牙痛、痛经、肌肉痛）",
            "发热",
            "关节炎、类风湿性关节炎"
        ],
        "dosage": {
            "adult": "每次200-400mg，每4-6小时1次，每日不超过2.4g",
            "children": "按体重5-10mg/kg，每6-8小时1次"
        },
        "adverse_reactions": [
            "胃肠道不适（胃痛、恶心）",
            "头晕、头痛",
            "长期使用可能增加心血管风险",
            "肾功能损害风险"
        ],
        "contraindications": [
            "活动性消化道溃疡患者禁用",
            "严重肝肾功能不全者禁用",
            "妊娠晚期禁用",
            "对阿司匹林或其他NSAID过敏者禁用"
        ],
        "interactions": [
            "与抗凝药合用增加出血风险",
            "与ACEI/ARB类降压药合用可能降低降压效果",
            "与锂剂合用可增加锂血药浓度"
        ],
        "category": "非处方药（部分规格为处方药）"
    },
    "二甲双胍": {
        "generic_name": "Metformin",
        "category": "口服降糖药 / 双胍类",
        "indications": [
            "2型糖尿病（首选药物）",
            "多囊卵巢综合征（超说明书用药）"
        ],
        "dosage": {
            "adult": "起始每次0.5g，每日2次，最大每日2.55g",
            "children": "10岁以上2型糖尿病：起始0.5g每日2次"
        },
        "adverse_reactions": [
            "胃肠道反应（腹泻、恶心、食欲减退）",
            "罕见：乳酸性酸中毒（严重但罕见）",
            "长期使用可能影响维生素B12吸收"
        ],
        "contraindications": [
            "严重肾功能不全（eGFR<30）禁用",
            "严重肝功能不全禁用",
            "造影剂检查前48小时暂停使用",
            "严重感染、手术等应激状态"
        ],
        "interactions": [
            "含碘造影剂增加乳酸性酸中毒风险",
            "与酒精合用增加低血糖和乳酸性酸中毒风险",
            "与利尿剂合用可能影响肾功能"
        ],
        "category": "处方药"
    }
}


def search_drug(drug_name: str) -> dict:
    """搜索药品信息。"""
    drug_name_clean = drug_name.strip().replace("胶囊", "").replace("片", "").replace("颗粒", "")
    drug_name_clean = drug_name_clean.replace("注射液", "").replace("口服液", "").replace("滴丸", "")

    for key, info in DRUG_DATABASE.items():
        if key in drug_name_clean or drug_name_clean in key:
            return {"found": True, "data": info, "matched_name": key}

    return {"found": False, "data": None, "message": f"未找到药品 '{drug_name}' 的信息，请确认药品名称"}


def format_drug_info(drug_name: str, info: dict, query_type: str) -> dict:
    """格式化药品信息。"""
    result = {
        "drug_name": drug_name,
        "query_type": query_type,
        "queried_at": datetime.now().isoformat(),
    }

    if info.get("found"):
        data = info["data"]
        result["matched_name"] = info["matched_name"]
        result["category"] = data.get("category", "")

        if query_type in ("all", "indication"):
            result["indications"] = data.get("indications", [])
        if query_type in ("all", "dosage"):
            result["dosage"] = data.get("dosage", {})
        if query_type in ("all", "adverse"):
            result["adverse_reactions"] = data.get("adverse_reactions", [])
        if query_type in ("all", "contraindication"):
            result["contraindications"] = data.get("contraindications", [])
        if query_type in ("all", "interaction"):
            result["interactions"] = data.get("interactions", [])
    else:
        result["error"] = info.get("message", "未找到")

    result["disclaimer"] = "本药品信息仅供参考，不能替代药品说明书和医生/药师指导。用药前请咨询专业医师。"
    return result


def main():
    parser = argparse.ArgumentParser(description="药品信息查询工具")
    parser.add_argument("--drug", required=True, help="药品名称")
    parser.add_argument("--info", default="all",
                        choices=["all", "indication", "dosage", "adverse", "interaction", "contraindication"],
                        help="查询信息类型")
    parser.add_argument("--data", default="", help="外部传入的药品数据（JSON）")
    parser.add_argument("--output", default="", help="输出文件路径")
    args = parser.parse_args()

    # 如果外部传入了数据，直接使用
    if args.data:
        try:
            external_data = json.loads(args.data) if isinstance(args.data, str) else args.data
            info = {"found": True, "data": external_data, "matched_name": args.drug}
        except json.JSONDecodeError:
            info = search_drug(args.drug)
    else:
        info = search_drug(args.drug)

    result = format_drug_info(args.drug, info, args.info)

    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(output_json)


if __name__ == "__main__":
    main()
