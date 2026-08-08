#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金融风险计算工具 — VaR/CVaR、波动率、夏普比率、最大回撤、Beta 等。

在实际部署中，此脚本配合 LLM 完成风险分析报告生成；
本脚本提供风险指标计算框架。
"""
import argparse
import json
import math
import sys
from pathlib import Path
from statistics import mean, stdev, quantiles
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TRADING_DAYS = 252  # 年化交易日


def annualize_return(daily_returns: list) -> float:
    """年化收益率。"""
    if not daily_returns:
        return 0.0
    cum_return = 1.0
    for r in daily_returns:
        cum_return *= (1 + r)
    total_days = len(daily_returns)
    return (cum_return ** (TRADING_DAYS / total_days)) - 1 if total_days > 0 else 0


def annualize_volatility(daily_returns: list) -> float:
    """年化波动率。"""
    if len(daily_returns) < 2:
        return 0.0
    return stdev(daily_returns) * math.sqrt(TRADING_DAYS)


def calc_var(returns: list, confidence: float = 0.95) -> float:
    """计算 Value at Risk（历史模拟法）。"""
    if len(returns) < 2:
        return 0.0
    sorted_returns = sorted(returns)
    index = int(len(sorted_returns) * (1 - confidence))
    return sorted_returns[max(0, index)]


def calc_cvar(returns: list, confidence: float = 0.95) -> float:
    """计算 Conditional VaR（Expected Shortfall）。"""
    if len(returns) < 2:
        return 0.0
    var = calc_var(returns, confidence)
    tail_losses = [r for r in returns if r <= var]
    return mean(tail_losses) if tail_losses else var


def calc_sharpe(returns: list, risk_free: float = 0.02) -> float:
    """计算夏普比率。"""
    ann_ret = annualize_return(returns)
    ann_vol = annualize_volatility(returns)
    if ann_vol == 0:
        return 0.0
    return (ann_ret - risk_free) / ann_vol


def calc_sortino(returns: list, risk_free: float = 0.02) -> float:
    """计算索提诺比率（下行风险）。"""
    ann_ret = annualize_return(returns)
    # 只计算负收益的标准差
    negative_returns = [r for r in returns if r < 0]
    if len(negative_returns) < 2:
        return 0.0
    downside_dev = stdev(negative_returns) * math.sqrt(TRADING_DAYS)
    if downside_dev == 0:
        return 0.0
    return (ann_ret - risk_free) / downside_dev


def calc_max_drawdown(prices: list) -> dict:
    """计算最大回撤。"""
    if len(prices) < 2:
        return {"max_drawdown": 0.0, "peak": 0, "trough": 0}

    peak = prices[0]
    max_dd = 0.0
    peak_idx = 0
    trough_idx = 0

    for i, price in enumerate(prices):
        if price > peak:
            peak = price
            peak_idx = i
        dd = (peak - price) / peak
        if dd > max_dd:
            max_dd = dd
            trough_idx = i

    return {
        "max_drawdown": round(-max_dd, 4),
        "peak_idx": peak_idx,
        "trough_idx": trough_idx,
    }


def calc_drawdown_from_returns(returns: list) -> float:
    """从收益率序列计算最大回撤。"""
    prices = [1.0]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    return calc_max_drawdown(prices)["max_drawdown"]


def calc_beta(returns: list, benchmark_returns: list) -> float:
    """计算 Beta 系数。"""
    if len(returns) < 2 or len(benchmark_returns) < 2:
        return 0.0

    n = min(len(returns), len(benchmark_returns))
    r = returns[:n]
    b = benchmark_returns[:n]

    mean_r = mean(r)
    mean_b = mean(b)

    covariance = sum((r[i] - mean_r) * (b[i] - mean_b) for i in range(n)) / (n - 1)
    variance = sum((x - mean_b) ** 2 for x in b) / (n - 1)

    return covariance / variance if variance != 0 else 0.0


def calc_alpha(returns: list, benchmark_returns: list, risk_free: float = 0.02) -> float:
    """计算 Alpha（Jensen's Alpha）。"""
    beta = calc_beta(returns, benchmark_returns)
    ann_ret = annualize_return(returns)
    ann_bench = annualize_return(benchmark_returns)
    return ann_ret - (risk_free + beta * (ann_bench - risk_free))


def calc_calmar(returns: list) -> float:
    """计算卡尔玛比率。"""
    ann_ret = annualize_return(returns)
    max_dd = calc_drawdown_from_returns(returns)
    if max_dd == 0:
        return 0.0
    return ann_ret / abs(max_dd)


def calc_win_rate(returns: list) -> float:
    """计算胜率。"""
    if not returns:
        return 0.0
    wins = sum(1 for r in returns if r > 0)
    return wins / len(returns)


def assess_risk_level(metrics: dict) -> str:
    """综合评估风险等级。"""
    vol = metrics.get("annualized_volatility", 0)
    dd = metrics.get("max_drawdown", 0)

    if vol > 0.40 or abs(dd) > 0.25:
        return "high"
    elif vol > 0.20 or abs(dd) > 0.10:
        return "medium"
    else:
        return "low"


def main():
    parser = argparse.ArgumentParser(description="金融风险计算工具")
    parser.add_argument("--returns", default="", help="日收益率序列（JSON数组）")
    parser.add_argument("--prices", default="", help="价格序列（JSON数组，自动计算收益率）")
    parser.add_argument("--benchmark", default="", help="基准收益率序列")
    parser.add_argument("--metrics", default="all", help="计算指标")
    parser.add_argument("--confidence", type=float, default=0.95, help="VaR置信水平")
    parser.add_argument("--risk_free", type=float, default=0.02, help="无风险利率")
    parser.add_argument("--output", default="", help="输出文件路径")
    args = parser.parse_args()

    # 解析数据
    returns = []
    if args.returns:
        try:
            returns = json.loads(args.returns) if isinstance(args.returns, str) else args.returns
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"收益率数据格式错误: {e}"}, ensure_ascii=False))
            sys.exit(1)
    elif args.prices:
        try:
            prices = json.loads(args.prices) if isinstance(args.prices, str) else args.prices
            returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"价格数据格式错误: {e}"}, ensure_ascii=False))
            sys.exit(1)
    else:
        print(json.dumps({"error": "需要 --returns 或 --prices 参数"}, ensure_ascii=False))
        sys.exit(1)

    if not returns:
        print(json.dumps({"error": "收益率数据为空"}, ensure_ascii=False))
        sys.exit(1)

    # 解析基准
    benchmark_returns = []
    if args.benchmark:
        try:
            benchmark_returns = json.loads(args.benchmark) if isinstance(args.benchmark, str) else args.benchmark
        except json.JSONDecodeError:
            pass

    req_metrics = args.metrics.split(",")
    result = {
        "data_points": len(returns),
        "period_days": len(returns),
    }

    # 基础统计
    result["mean_daily_return"] = round(mean(returns), 6) if returns else 0
    result["annualized_return"] = round(annualize_return(returns), 4)

    if "all" in req_metrics or "volatility" in req_metrics:
        result["annualized_volatility"] = round(annualize_volatility(returns), 4)

    if "all" in req_metrics or "var" in req_metrics:
        result[f"var_{int(args.confidence*100)}"] = round(calc_var(returns, args.confidence), 4)

    if "all" in req_metrics or "cvar" in req_metrics:
        result[f"cvar_{int(args.confidence*100)}"] = round(calc_cvar(returns, args.confidence), 4)

    if "all" in req_metrics or "sharpe" in req_metrics:
        result["sharpe_ratio"] = round(calc_sharpe(returns, args.risk_free), 4)

    if "all" in req_metrics or "sortino" in req_metrics:
        result["sortino_ratio"] = round(calc_sortino(returns, args.risk_free), 4)

    if "all" in req_metrics or "drawdown" in req_metrics:
        result["max_drawdown"] = round(calc_drawdown_from_returns(returns), 4)

    if "all" in req_metrics or "calmar" in req_metrics:
        result["calmar_ratio"] = round(calc_calmar(returns), 4)

    if ("all" in req_metrics or "beta" in req_metrics or "alpha" in req_metrics) and benchmark_returns:
        if "all" in req_metrics or "beta" in req_metrics:
            result["beta"] = round(calc_beta(returns, benchmark_returns), 4)
        if "all" in req_metrics or "alpha" in req_metrics:
            result["alpha"] = round(calc_alpha(returns, benchmark_returns, args.risk_free), 4)

    result["win_rate"] = round(calc_win_rate(returns), 4)
    result["risk_level"] = assess_risk_level(result)
    result["calculated_at"] = datetime.now().isoformat()
    result["disclaimer"] = "本计算结果仅供参考，不构成投资建议。"

    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(output_json)


if __name__ == "__main__":
    main()
