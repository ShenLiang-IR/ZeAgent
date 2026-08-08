#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""财报分析工具 — 解析财务数据，计算关键指标，生成分析报告。

在实际部署中，此脚本配合 LLM 完成深度分析和评论生成；
本脚本提供指标计算和结构化输出框架。
"""
import argparse
import csv
import json
import sys
from pathlib import Path
from datetime import datetime
from io import StringIO

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def safe_div(a, b, default=0.0):
    """安全除法。"""
    return round(a / b, 4) if b and b != 0 else default


def calc_profitability(data: dict) -> dict:
    """计算盈利能力指标。"""
    inc = data.get("income_statement", {})
    bs = data.get("balance_sheet", {})
    rev = inc.get("revenue", 0)
    cost = inc.get("cost_of_revenue", 0)
    ni = inc.get("net_income", 0)
    equity = bs.get("equity", 0)
    total_assets = bs.get("total_assets", 0)
    ebitda = inc.get("ebitda", 0)

    return {
        "gross_margin": safe_div(rev - cost, rev) * 100,
        "net_margin": safe_div(ni, rev) * 100,
        "roe": safe_div(ni, equity) * 100,
        "roa": safe_div(ni, total_assets) * 100,
        "ebitda_margin": safe_div(ebitda, rev) * 100,
    }


def calc_leverage(data: dict) -> dict:
    """计算偿债能力指标。"""
    bs = data.get("balance_sheet", {})
    inc = data.get("income_statement", {})
    ca = bs.get("current_assets", 0)
    cl = bs.get("current_liabilities", 0)
    tl = bs.get("total_liabilities", 0)
    ta = bs.get("total_assets", 0)
    ebitda = inc.get("ebitda", 0)
    interest = inc.get("interest_expense", 0)

    return {
        "current_ratio": safe_div(ca, cl),
        "quick_ratio": safe_div(ca - bs.get("inventory", 0), cl),
        "debt_ratio": safe_div(tl, ta) * 100,
        "debt_to_equity": safe_div(tl, bs.get("equity", 0)),
        "interest_coverage": safe_div(ebitda, interest, default=999),
    }


def calc_efficiency(data: dict) -> dict:
    """计算运营效率指标。"""
    inc = data.get("income_statement", {})
    bs = data.get("balance_sheet", {})
    rev = inc.get("revenue", 0)
    cost = inc.get("cost_of_revenue", 0)
    inv = bs.get("inventory", 0)
    ar = bs.get("accounts_receivable", 0)
    ta = bs.get("total_assets", 0)

    return {
        "inventory_turnover": safe_div(cost, inv, default=999),
        "receivable_turnover": safe_div(rev, ar, default=999),
        "asset_turnover": safe_div(rev, ta),
    }


def calc_growth(current: dict, compare: dict) -> dict:
    """计算同比/环比增长指标。"""
    cur_inc = current.get("income_statement", {})
    cmp_inc = compare.get("income_statement", {}) if compare else {}
    cur_bs = current.get("balance_sheet", {})
    cmp_bs = compare.get("balance_sheet", {}) if compare else {}

    cur_rev = cur_inc.get("revenue", 0)
    cmp_rev = cmp_inc.get("revenue", 0)
    cur_ni = cur_inc.get("net_income", 0)
    cmp_ni = cmp_inc.get("net_income", 0)
    cur_ta = cur_bs.get("total_assets", 0)
    cmp_ta = cmp_bs.get("total_assets", 0)

    return {
        "revenue_growth": safe_div(cur_rev - cmp_rev, cmp_rev) * 100,
        "net_income_growth": safe_div(cur_ni - cmp_ni, cmp_ni) * 100,
        "asset_growth": safe_div(cur_ta - cmp_ta, cmp_ta) * 100,
    }


def calc_cashflow(data: dict) -> dict:
    """计算现金流指标。"""
    cf = data.get("cash_flow", {})
    inc = data.get("income_statement", {})
    ocf = cf.get("operating_cf", 0)
    icf = cf.get("investing_cf", 0)
    fcf = cf.get("financing_cf", 0)
    rev = inc.get("revenue", 0)
    ni = inc.get("net_income", 0)
    capex = abs(cf.get("capex", icf)) if icf < 0 else 0

    free_cf = ocf - capex

    return {
        "ocf_to_revenue": safe_div(ocf, rev) * 100,
        "ocf_to_net_income": safe_div(ocf, ni, default=999),
        "free_cash_flow": free_cf,
        "fcf_to_revenue": safe_div(free_cf, rev) * 100,
    }


def generate_summary(metrics: dict, growth: dict) -> str:
    """生成分析摘要。"""
    parts = []

    # 盈利能力评价
    roe = metrics.get("profitability", {}).get("roe", 0)
    if roe > 15:
        parts.append("盈利能力优秀")
    elif roe > 8:
        parts.append("盈利能力良好")
    elif roe > 0:
        parts.append("盈利能力一般")
    else:
        parts.append("当前处于亏损状态")

    # 偿债能力评价
    cr = metrics.get("leverage", {}).get("current_ratio", 0)
    if cr > 2:
        parts.append("偿债能力强")
    elif cr > 1:
        parts.append("偿债能力适中")
    else:
        parts.append("短期偿债压力较大")

    # 成长性评价
    rg = growth.get("revenue_growth", 0)
    if rg > 20:
        parts.append("营收高速增长")
    elif rg > 5:
        parts.append("营收稳步增长")
    elif rg >= 0:
        parts.append("营收基本持平")
    else:
        parts.append("营收出现下滑")

    parts.append("。")
    return "，".join(parts[:-1]) + parts[-1] if len(parts) > 1 else parts[0]


def load_data(filepath: str) -> dict:
    """加载财务数据（JSON/CSV）。"""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {filepath}")

    if path.suffix.lower() == ".csv":
        text = path.read_text(encoding="utf-8-sig")
        reader = csv.DictReader(StringIO(text))
        return {"rows": list(reader), "type": "csv"}
    else:
        return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="财报分析工具")
    parser.add_argument("--file", required=True, help="财务数据文件（JSON/CSV）")
    parser.add_argument("--period", default="", help="分析期间")
    parser.add_argument("--compare", default="", help="对比数据文件（同比分析）")
    parser.add_argument("--metrics", default="all",
                        help="分析指标：profitability,leverage,efficiency,cashflow,growth,all")
    parser.add_argument("--output", default="", help="输出报告路径")
    args = parser.parse_args()

    try:
        data = load_data(args.file)
        compare_data = load_data(args.compare) if args.compare else None
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    except (json.JSONDecodeError, csv.Error) as e:
        print(json.dumps({"error": f"数据格式错误: {e}"}, ensure_ascii=False))
        sys.exit(1)

    if data.get("type") == "csv":
        print(json.dumps({
            "message": "CSV格式检测到，已加载数据行",
            "row_count": len(data.get("rows", [])),
            "columns": list(data["rows"][0].keys()) if data["rows"] else [],
            "hint": "请将数据转为JSON格式（含balance_sheet/income_statement/cash_flow）进行分析"
        }, ensure_ascii=False, indent=2))
        return

    # 计算指标
    metrics = {}
    req_metrics = args.metrics.split(",")

    if "all" in req_metrics or "profitability" in req_metrics:
        metrics["profitability"] = calc_profitability(data)
    if "all" in req_metrics or "leverage" in req_metrics:
        metrics["leverage"] = calc_leverage(data)
    if "all" in req_metrics or "efficiency" in req_metrics:
        metrics["efficiency"] = calc_efficiency(data)
    if "all" in req_metrics or "cashflow" in req_metrics:
        metrics["cashflow"] = calc_cashflow(data)

    growth = calc_growth(data, compare_data) if compare_data else {}

    result = {
        "company": data.get("company", "未知公司"),
        "period": args.period or data.get("period", ""),
        "analyzed_at": datetime.now().isoformat(),
        "metrics": metrics,
        "growth": growth,
        "summary": generate_summary(metrics, growth),
        "disclaimer": "本分析基于提供数据自动计算，仅供参考，不构成投资建议。",
    }

    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(output_json)


if __name__ == "__main__":
    main()
