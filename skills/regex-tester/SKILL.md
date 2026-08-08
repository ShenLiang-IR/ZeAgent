---
name: regex-tester
description: 正则表达式测试工具。匹配、提取、替换文本中的模式，返回 JSON 结果。支持分组捕获。
version: "1.0"
enabled: true
category: utility
author: system
---

# 正则表达式测试器

对文本执行正则匹配、提取或替换操作。

## 使用方式

```bash
python skills/regex-tester/scripts/main.py --pattern '\d+' --text 'abc123def456' --action match
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--pattern` | 正则表达式（必填） |
| `--text` | 输入文本（必填） |
| `--action` | match（查找全部匹配）/ replace（替换）/ split（分割），默认 match |
| `--replacement` | 替换字符串（仅 replace 使用） |

## 依赖

- Python 3.11+（标准库 re）
