---
name: text-diff
description: 文本差异比较工具。比较两段文本的差异，输出行级别的增删改。类似 git diff 的效果。
version: "1.0"
enabled: true
category: utility
author: system
---

# 文本差异比较

比较两段文本，输出行级别的差异。

## 使用方式

```bash
python skills/text-diff/scripts/main.py --old "line1\nline2\nline3" --new "line1\nmodified\nline3"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--old` | 旧文本（必填） |
| `--new` | 新文本（必填） |
| `--context` | 上下文行数（默认 3，设 0 为全量） |

## 输出格式

```json
{
  "diff": [
    {"type": " ", "content": "line1"},
    {"type": "-", "content": "line2"},
    {"type": "+", "content": "modified"},
    {"type": " ", "content": "line3"}
  ],
  "added": 1,
  "removed": 1,
  "unchanged": 2
}
```

## 依赖

- Python 3.11+（标准库 difflib）
