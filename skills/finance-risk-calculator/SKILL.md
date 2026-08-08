---
name: finance-risk-calculator
description: 金融风险计算技能。计算 VaR/CVaR、波动率、夏普比率、最大回撤、Beta 系数等风控指标，辅助投资组合风险评估。触发词：风险评估、VaR、波动率、夏普比率、最大回撤、投资组合分析。
version: "1.0"
enabled: true
category: analysis
author: system
tags:
  - finance
  - risk
  - portfolio
  - quant
domain: finance
allowed-tools: read_file
---

# 金融风险计算技能

计算投资组合和单资产的风险指标，支持 VaR（风险价值）、CVaR、波动率、夏普比率、最大回撤、Beta 等指标。

## 使用方式

```bash
python skills/finance-risk-calculator/scripts/main.py --returns "[0.02,-0.01,0.03,...]" --metrics "var,sharpe,drawdown"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--returns` | 日收益率序列（JSON数组字符串） |
| `--prices` | 价格序列（JSON数组，自动计算收益率） |
| `--benchmark` | 基准收益率序列（计算 Beta/Alpha 时必填） |
| `--metrics` | 计算指标：var/cvar/volatility/sharpe/drawdown/beta/alpha/all |
| `--confidence` | VaR 置信水平（默认 0.95） |
| `--risk_free` | 无风险利率（默认 0.02，即2%） |
| `--output` | 输出文件路径（可选） |

### 支持的指标

| 指标 | 说明 |
|---|---|
| var | Value at Risk（风险价值） |
| cvar | Conditional VaR（条件风险价值） |
| volatility | 年化波动率 |
| sharpe | 夏普比率 |
| drawdown | 最大回撤 |
| beta | Beta 系数（相对基准） |
| alpha | Alpha 收益（相对基准） |
| sortino | 索提诺比率（下行风险调整） |
| calmar | 卡尔玛比率（回撤调整收益） |

### 示例

```bash
python skills/finance-risk-calculator/scripts/main.py --returns "[0.015,-0.008,0.022,-0.003,0.019,...]" --metrics "var,sharpe,drawdown,volatility"

python skills/finance-risk-calculator/scripts/main.py --returns "[0.015,...]" --benchmark "[0.008,...]" --metrics "beta,alpha"
```

## 输出格式

```json
{
  "metrics": {
    "annualized_return": 0.18,
    "annualized_volatility": 0.22,
    "sharpe_ratio": 0.73,
    "var_95": -0.025,
    "cvar_95": -0.038,
    "max_drawdown": -0.15,
    "beta": 1.12,
    "alpha": 0.04
  },
  "risk_level": "medium",
  "summary": "组合年化收益18%，波动率22%，夏普比率0.73，最大回撤15%，整体风险中等"
}
```

## 依赖

- Python 3.11+（标准库，math/statistics）
