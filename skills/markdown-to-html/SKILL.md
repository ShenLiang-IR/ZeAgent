---
name: markdown-to-html
description: 将 Markdown 转换为 HTML。支持标题、列表、代码块、表格、链接、图片等常用语法。
version: "1.0"
enabled: true
category: content
author: system
---

# Markdown 转 HTML

将 Markdown 文本转换为 HTML。

## 使用方式

```bash
python skills/markdown-to-html/scripts/main.py --text "# Hello\n\nThis is **bold**"
python skills/markdown-to-html/scripts/main.py --file input.md --output result.html
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--text` | Markdown 文本 |
| `--file` | 输入 Markdown 文件路径 |
| `--output` | 输出 HTML 文件路径（可选） |
| `--full-page` | 输出完整 HTML 页面（含 `<html><body>` 包裹） |

## 依赖

- Python 3.11+（标准库，无第三方依赖）
