---
name: doc-converter
description: 文档格式转换工具。支持 Markdown↔HTML、TXT→JSON、JSON→CSV、CSV→JSON 等常见格式互转。
version: "1.0"
enabled: true
category: office
author: system
---

# 文档格式转换工具

在常见文档格式之间互转。

## 使用方式

```bash
# CSV 转 JSON
python skills/doc-converter/scripts/main.py --input data.csv --from csv --to json --output data.json

# JSON 转 CSV
python skills/doc-converter/scripts/main.py --input data.json --from json --to csv --output data.csv
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--input` | 输入文件路径（必填） |
| `--from` | 输入格式：csv/json/txt/markdown |
| `--to` | 输出格式：csv/json/txt/html |
| `--output` | 输出文件路径（可选，不指定则输出 stdout） |

## 依赖

- Python 3.11+（标准库）
