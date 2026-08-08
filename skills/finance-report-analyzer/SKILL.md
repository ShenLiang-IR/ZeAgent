---
name: finance-report-analyzer
description: 财报分析技能。解析资产负债表、利润表、现金流量表，计算关键财务指标，生成分析报告。触发词：财报分析、财务报表、杜邦分析、财务指标、盈利能力。
version: "1.0"
enabled: true
category: analysis
author: system
tags:
  - finance
  - report
  - accounting
  - investment
domain: finance
allowed-tools: read_file
---

# 财报分析技能

解析企业财务报表，自动计算关键财务指标，支持同比/环比分析，生成结构化分析报告。

## 使用方式

```bash
python skills/finance-report-analyzer/scripts/main.py --file "财报数据.json" --period "2024Q4"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--file` | 财务数据文件（JSON/CSV，必填） |
| `--period` | 分析期间（如 2024Q4） |
| `--compare` | 对比期间（如 2023Q4，同比分析） |
| `--metrics` | 分析指标（逗号分隔，默认 all） |
| `--output` | 输出报告路径（可选） |

### 分析指标

| 类别 | 指标 |
|---|---|
| 盈利能力 | 毛利率、净利率、ROE、ROA、EBITDA利润率 |
| 偿债能力 | 流动比率、速动比率、资产负债率、利息保障倍数 |
| 运营效率 | 存货周转率、应收账款周转率、总资产周转率 |
| 成长能力 | 营收增长率、净利润增长率、总资产增长率 |
| 现金流 | 经营现金流/营收比、自由现金流 |

### 输入数据格式

```json
{
  "company": "某某科技",
  "period": "2024Q4",
  "balance_sheet": {
    "total_assets": 1000000000,
    "total_liabilities": 450000000,
    "equity": 550000000,
    "current_assets": 350000000,
    "current_liabilities": 200000000
  },
  "income_statement": {
    "revenue": 250000000,
    "cost_of_revenue": 140000000,
    "operating_expenses": 50000000,
    "net_income": 38000000,
    "ebitda": 60000000
  },
  "cash_flow": {
    "operating_cf": 42000000,
    "investing_cf": -25000000,
    "financing_cf": -10000000
  }
}
```

### 示例

```bash
python skills/finance-report-analyzer/scripts/main.py --file "financials_2024.json" --period 2024Q4 --compare 2023Q4 --metrics profitability,leverage
```

## 输出格式

```json
{
  "company": "某某科技",
  "period": "2024Q4",
  "metrics": {
    "gross_margin": 44.0,
    "net_margin": 15.2,
    "roe": 6.91,
    "current_ratio": 1.75,
    "debt_to_equity": 0.82
  },
  "comparison": {
    "revenue_growth": 15.3,
    "net_income_growth": 22.1
  },
  "summary": "公司盈利能力良好，偿债能力稳健，营收同比增长15.3%"
}
```

## 依赖

- Python 3.11+（标准库）
