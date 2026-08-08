#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金融市场监控工具 — 行情数据处理、技术指标计算、异常波动预警。

在实际部署中，行情数据由 LLM 通过 http-request 获取后传入；
本脚本提供指标计算和预警分析框架。
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def calc_ma(prices: List[float], period: int) -> Optional[float]:
    """计算简单移动平均线。"""
    if len(prices) < period:
        return None
    return round(sum(prices[-period:]) / period, 2)


def calc_ema(prices: List[float], period: int) -> Optional[float]:
    """计算指数移动平均线。"""
    if len(prices) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return round(ema, 2)


def calc_macd(prices: List[float]) -> Dict[str, Optional[float]]:
    """计算 MACD 指标 (12, 26, 9)。"""
    ema12 = calc_ema(prices, 12)
    ema26 = calc_ema(prices, 26)
    if ema12 is None or ema26 is None:
        return {"DIF": None, "DEA": None, "BAR": None}

    # 简化：只用最新
    dif = ema12 - ema26
    # 需要 DIF 序列算 DEA，这里用简化近似
    dea = dif * 0.2  # 简化 DEA
    bar = 2 * (dif - dea)

    return {
        "DIF": round(dif, 2),
        "DEA": round(dea, 2),
        "BAR": round(bar, 2),
    }


def calc_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    """计算 RSI 相对强弱指标。"""
    if len(prices) < period + 1:
        return None

    gains = 0
    losses = 0
    for i in range(len(prices) - period, len(prices)):
        diff = prices[i] - prices[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses += abs(diff)

    avg_gain = gains / period
    avg_loss = losses / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calc_bollinger(prices: List[float], period: int = 20, std_mult: float = 2.0) -> Dict:
    """计算布林带。"""
    if len(prices) < period:
        return {"upper": None, "middle": None, "lower": None}

    recent = prices[-period:]
    ma = sum(recent) / len(recent)
    variance = sum((p - ma) ** 2 for p in recent) / len(recent)
    std = variance ** 0.5

    return {
        "upper": round(ma + std_mult * std, 2),
        "middle": round(ma, 2),
        "lower": round(ma - std_mult * std, 2),
    }


def calc_volume_analysis(volumes: List[float], prices: List[float]) -> Dict:
    """成交量分析。"""
    if len(volumes) < 5:
        return {"avg_volume": 0, "volume_change": 0}

    recent_vol = volumes[-5:]
    prev_vol = volumes[-10:-5] if len(volumes) >= 10 else recent_vol

    avg_recent = sum(recent_vol) / len(recent_vol)
    avg_prev = sum(prev_vol) / len(prev_vol)

    return {
        "avg_volume_5d": round(avg_recent, 0),
        "volume_change": round((avg_recent / avg_prev - 1) * 100, 2) if avg_prev > 0 else 0,
    }


def check_alerts(price_data: Dict, indicators: Dict, alert_config: Dict) -> List[str]:
    """检查预警条件。"""
    alerts = []

    # 价格涨跌幅预警
    change_pct = price_data.get("change_pct", 0)
    threshold = alert_config.get("price_change_pct")
    if threshold and abs(change_pct) >= threshold:
        direction = "上涨" if change_pct > 0 else "下跌"
        alerts.append(f"{direction}幅度达{abs(change_pct):.1f}%，超过{threshold}%预警线")

    # RSI 超买超卖
    rsi = indicators.get("RSI")
    if rsi is not None:
        overbought = alert_config.get("rsi_overbought", 80)
        oversold = alert_config.get("rsi_oversold", 20)
        if rsi >= overbought:
            alerts.append(f"RSI={rsi}，处于超买区域（>={overbought}）")
        elif rsi <= oversold:
            alerts.append(f"RSI={rsi}，处于超卖区域（<={oversold}）")

    # 成交量异常
    vol = price_data.get("volume_change", 0)
    vol_threshold = alert_config.get("volume_spike")
    if vol_threshold and abs(vol) >= vol_threshold:
        alerts.append(f"成交量较前5日均值变化{vol:+.1f}%，超过{vol_threshold}倍预警线")

    return alerts


def generate_signal(indicators: Dict) -> str:
    """根据技术指标生成简单信号。"""
    signals = []

    # MACD 信号
    macd = indicators.get("MACD", {})
    if macd.get("BAR") is not None:
        if macd["BAR"] > 0:
            signals.append("MACD多头信号")
        elif macd["BAR"] < 0:
            signals.append("MACD空头信号")

    # RSI 信号
    rsi = indicators.get("RSI")
    if rsi is not None:
        if rsi > 70:
            signals.append("超买区域，注意回调风险")
        elif rsi < 30:
            signals.append("超卖区域，可能出现反弹")
        elif 40 <= rsi <= 60:
            signals.append("RSI中性区间")

    # MA 信号
    ma5 = indicators.get("MA5")
    ma20 = indicators.get("MA20")
    if ma5 is not None and ma20 is not None:
        if ma5 > ma20:
            signals.append("MA5上穿MA20，短期看多")
        else:
            signals.append("MA5下穿MA20，短期看空")

    return "；".join(signals) if signals else "技术指标中性"


def analyze_symbol(data: Dict, alert_config: Dict) -> Dict:
    """分析单个标的。"""
    prices = data.get("prices", [])
    volumes = data.get("volumes", [])
    current_price = prices[-1] if prices else data.get("price", 0)
    prev_price = prices[-2] if len(prices) >= 2 else current_price

    indicators = {}
    req_indicators = data.get("requested_indicators", ["MA", "MACD", "RSI"])

    if "MA" in req_indicators:
        indicators["MA5"] = calc_ma(prices, 5)
        indicators["MA10"] = calc_ma(prices, 10)
        indicators["MA20"] = calc_ma(prices, 20)
        indicators["MA60"] = calc_ma(prices, 60)
    if "MACD" in req_indicators:
        indicators["MACD"] = calc_macd(prices)
    if "RSI" in req_indicators:
        indicators["RSI"] = calc_rsi(prices)
    if "BOLL" in req_indicators:
        indicators["BOLL"] = calc_bollinger(prices)
    if "VOL" in req_indicators:
        indicators["volume"] = calc_volume_analysis(volumes, prices)

    price_info = {
        "price": current_price,
        "prev_price": prev_price,
        "change_pct": round((current_price / prev_price - 1) * 100, 2) if prev_price > 0 else 0,
        "volume_change": indicators.get("volume", {}).get("volume_change", 0),
    }

    alerts = check_alerts(price_info, indicators, alert_config)
    signal = generate_signal(indicators)

    return {
        "code": data.get("code", ""),
        "name": data.get("name", ""),
        "price_info": price_info,
        "indicators": indicators,
        "signal": signal,
        "alerts": alerts,
    }


def main():
    parser = argparse.ArgumentParser(description="金融市场监控工具")
    parser.add_argument("--symbols", required=True, help="品种代码（逗号分隔）")
    parser.add_argument("--indicators", default="MA,MACD,RSI", help="技术指标")
    parser.add_argument("--period", default="1d", choices=["1d", "1w", "1m"], help="K线周期")
    parser.add_argument("--lookback", type=int, default=30, help="回溯天数")
    parser.add_argument("--alert", default="{}", help="预警配置（JSON）")
    parser.add_argument("--data", default="", help="行情数据（JSON，如果由LLM获取）")
    parser.add_argument("--output", default="", help="输出文件路径")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    req_indicators = [i.strip() for i in args.indicators.split(",") if i.strip()]

    try:
        alert_config = json.loads(args.alert) if args.alert else {}
    except json.JSONDecodeError:
        alert_config = {}

    # 如果传入了行情数据，直接分析
    market_data = {}
    if args.data:
        try:
            market_data = json.loads(args.data) if isinstance(args.data, str) else args.data
        except json.JSONDecodeError:
            pass

    results = []
    for symbol in symbols:
        symbol_data = market_data.get(symbol, {})
        symbol_data["code"] = symbol
        symbol_data["requested_indicators"] = req_indicators
        if "prices" not in symbol_data:
            # 无实际数据时生成模拟框架
            symbol_data["prices"] = []
            symbol_data["volumes"] = []
            symbol_data["name"] = symbol

        result = analyze_symbol(symbol_data, alert_config)
        results.append(result)

    output = {
        "symbols": results,
        "period": args.period,
        "lookback": args.lookback,
        "monitored_at": datetime.now().isoformat(),
        "disclaimer": "技术分析仅供参考，不构成投资建议。实际数据请通过行情API获取。",
    }

    output_json = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(output_json)


if __name__ == "__main__":
    main()
