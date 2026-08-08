---
name: daily-trading
description: 查看今日交易行情技能。当用户询问"今日行情"、"交易行情"、"今日交易"、"债券行情"时触发。Triggers on queries about "今日", "行情", "交易数据", "trading", "market".
enabled: true
metadata:
  author: aries-agent
  version: "1.0"
  domain: investment-research
allowed-tools: read_file
---

# Daily Trading Skill

## Instructions

当用户询问今日交易行情时，执行以下步骤：

1. 使用 `read_file` 读取文件 `skills/daily-trading/references/market_data.md`
2. 将内容格式化为表格展示给用户

### 输出格式

使用 Markdown 表格呈现行情数据，包含债券代码、名称、最新价、涨跌幅、成交量等字段。

如果读取失败，回复用户："今日行情数据暂不可用，请稍后重试。"
