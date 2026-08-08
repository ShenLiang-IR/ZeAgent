---
name: word-frequency
description: 统计文本文件中词频，支持中英文分词，输出 Top N 高频词
version: 1.0
enabled: true
category: analysis
---

# 词频分析工具

统计指定文本文件中每个词的出现频率，支持中英文混合文本，输出 JSON 格式的词频统计结果。

## 使用方式

使用 `bash` 工具执行 Python 脚本（项目根目录下）：

```bash
python skills/word-frequency/scripts/word_frequency.py data/文件名.txt --top 20
```

### 参数说明

| 参数 | 说明 |
|---|---|
| 第一个位置参数 | 要分析的文本文件路径（必填） |
| `--top` | 返回前 N 个高频词，默认 20 |
| `--min-length` | 最小词长度过滤，默认 1（中文按字符，英文按单词） |

### 示例

先将文本写入 `data/`，然后执行：

```bash
python skills/word-frequency/scripts/word_frequency.py data/sample.txt --top 10
```

输出示例：

```json
{
  "file": "/mnt/workspace/sample.txt",
  "total_words": 500,
  "unique_words": 120,
  "top_words": [
    {"word": "数据", "count": 35, "frequency": "7.00%"},
    {"word": "分析", "count": 28, "frequency": "5.60%"},
    {"word": "the", "count": 20, "frequency": "4.00%"}
  ]
}
```

## 输出目录规范

| 路径 | 用途 | 权限 |
|---|---|---|
| `/mnt/workspace/` | 待分析的文本文件 | 读写 |

## 依赖

- Python 3.8+（系统自带）
- 无额外 pip 依赖（使用标准库 re + collections）
