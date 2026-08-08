---
name: finance-market-monitor
description: 金融市场监控技能。监控股票/指数/外汇/加密货币行情，技术指标计算，异常波动预警。触发词：行情监控、股票行情、大盘走势、涨跌幅、K线分析。
version: "1.0"
enabled: true
category: data
author: system
tags:
  - finance
  - market
  - stock
  - trading
domain: finance
allowed-tools: read_file, http-request
---

# 金融市场监控技能

实时监控金融市场行情，计算技术指标，异常波动预警。支持 A股/港股/美股/外汇/加密货币多市场。

## 使用方式

```bash
python skills/finance-market-monitor/scripts/main.py --symbols "000001.SZ,600519.SH" --indicators "MA,MACD,RSI"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--symbols` | 股票/品种代码（逗号分隔，必填） |
| `--indicators` | 技术指标：MA/MACD/RSI/BOLL/KDJ/VOL（默认 MA,MACD） |
| `--period` | K线周期：1d/1w/1m（默认 1d） |
| `--lookback` | 回溯天数（默认 30） |
| `--alert` | 预警阈值配置（JSON，可选） |
| `--output` | 输出文件路径（可选） |

### 支持的指标

| 指标 | 说明 |
|---|---|
| MA | 移动平均线（5/10/20/60日） |
| MACD | 指数平滑异同移动平均线 |
| RSI | 相对强弱指标（14日） |
| BOLL | 布林带（20日，2倍标准差） |
| KDJ | 随机指标 |
| VOL | 成交量分析 |

### 预警配置

```json
{
  "price_change_pct": 5.0,
  "volume_spike": 2.0,
  "rsi_overbought": 80,
  "rsi_oversold": 20
}
```

### 示例

```bash
python skills/finance-market-monitor/scripts/main.py --symbols "000001.SZ,600519.SH,TSLA" --indicators "MA,MACD,RSI" --alert '{"price_change_pct": 3.0}'
```

## 输出格式

```json
{
  "symbols": [
    {
      "code": "000001.SZ",
      "name": "平安银行",
      "price": 12.45,
      "change_pct": 2.3,
      "indicators": {
        "MA5": 12.20,
        "MA20": 11.85,
        "MACD": {"DIF": 0.35, "DEA": 0.28, "BAR": 0.07},
        "RSI": 62.5
      },
      "alerts": ["RSI接近超买区域"]
    }
  ]
}
```

## 依赖

- Python 3.11+（标准库）
- 数据接入：在 Agent 运行时由 LLM 通过 http-request 调用行情 API
