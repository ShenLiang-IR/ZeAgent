---
name: hash-tool
description: 哈希计算工具。计算文本或文件的 MD5/SHA1/SHA256/SHA512 哈希值。
version: "1.0"
enabled: true
category: utility
author: system
---

# 哈希工具

计算文本或文件的哈希值。

## 使用方式

```bash
# 文本哈希
python skills/hash-tool/scripts/main.py --text "hello" --algo sha256

# 文件哈希
python skills/hash-tool/scripts/main.py --file data/file.zip --algo md5
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--text` | 输入文本（与 --file 二选一） |
| `--file` | 输入文件路径 |
| `--algo` | 哈希算法：md5/sha1/sha256/sha512（默认 sha256） |

## 依赖

- Python 3.11+（标准库 hashlib）
