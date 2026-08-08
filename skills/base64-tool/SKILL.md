---
name: base64-tool
description: Base64 编码/解码工具，支持文本和文件。编码时输出 Base64 字符串，解码时还原原始内容。
version: "1.0"
enabled: true
category: utility
author: system
---

# Base64 工具

对文本或文件进行 Base64 编码/解码。

## 使用方式

```bash
python skills/base64-tool/scripts/main.py --action encode --text "hello"
python skills/base64-tool/scripts/main.py --action decode --text "aGVsbG8="
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--action` | encode（编码）或 decode（解码） |
| `--text` | 输入文本 |
| `--file` | 输入文件路径（与 --text 二选一） |
| `--output` | 输出文件路径（可选） |

## 依赖

- Python 3.11+（标准库）
