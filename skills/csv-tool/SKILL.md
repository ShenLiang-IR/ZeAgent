---
name: csv-tool
description: CSV 文件处理工具。读取、筛选、转换 CSV 数据为 JSON，支持列选择和条件过滤。
version: "1.0"
enabled: true
category: data
author: system
---

# CSV 工具

读取 CSV 文件，支持列选择、条件过滤，输出 JSON 格式结果。

## 使用方式

```bash
python skills/csv-tool/scripts/main.py --file data.csv --columns name,age --where "age>18"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--file` | CSV 文件路径（必填） |
| `--columns` | 要输出的列名（逗号分隔，不指定则全部） |
| `--where` | 过滤条件，如 `age>18` 或 `name=张三` |
| `--limit` | 返回行数限制 |
| `--delimiter` | CSV 分隔符（默认逗号） |

## 依赖

- Python 3.11+（标准库 csv）
