---
name: uuid-generator
description: UUID 生成工具。生成 UUID v4/v5，支持批量生成和格式化输出。
version: "1.0"
enabled: true
category: utility
author: system
---

# UUID 生成器

生成 UUID，支持 v4（随机）和 v5（命名空间+名称）。

## 使用方式

```bash
# 单个 UUID v4
python skills/uuid-generator/scripts/main.py --version 4

# 批量生成 10 个
python skills/uuid-generator/scripts/main.py --version 4 --count 10

# UUID v5（命名空间+名称）
python skills/uuid-generator/scripts/main.py --version 5 --namespace dns --name "example.com"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--version` | UUID 版本：4 或 5（默认 4） |
| `--count` | 生成数量（默认 1） |
| `--namespace` | 命名空间：dns/url/oid/x500 或自定义 UUID（仅 v5） |
| `--name` | 名称（仅 v5） |
| `--uppercase` | 输出大写（默认小写） |

## 依赖

- Python 3.11+（标准库 uuid）
