---
name: pdf-extractor
description: PDF 文本提取工具。从 PDF 文件中提取文本内容，支持多页、保留段落结构。输出纯文本或 JSON。
version: "1.0"
enabled: true
category: office
author: system
---

# PDF 文本提取工具

从 PDF 文件中提取文本内容。

## 使用方式

```bash
python skills/pdf-extractor/scripts/main.py --file document.pdf --output result.txt
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--file` | PDF 文件路径（必填） |
| `--output` | 输出文件路径（可选，不指定则输出到 stdout） |
| `--format` | 输出格式：text（默认）或 json（按页分段） |
| `--page-start` | 起始页码（从 0 开始，默认 0） |
| `--page-end` | 结束页码（默认全部） |

## 依赖

- PyMuPDF（pip install pymupdf）
