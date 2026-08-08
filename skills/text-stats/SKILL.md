---
name: text-stats
description: 统计文本文件的字符数、词数、行数，支持多文件汇总
version: 1.0
enabled: true
---

# 文本统计工具

统计指定文本文件的字符数、词数、行数。

> **重要**：不要读取 Python 脚本文件本身，只需按照以下参数说明通过 `bash` 工具直接调用即可。

## 使用方式

使用 `bash` 工具执行 Python 脚本（项目根目录下，跨平台，无需依赖 wc）：

```bash
python skills/text-stats/scripts/text_stats.py data/文件名.txt
```

### 参数说明

| 参数 | 说明 |
|---|---|
| 第一个位置参数 | 要统计的文本文件路径（虚拟路径） |

### 示例

先将文本写入 `data/`，然后执行：

```bash
python skills/text-stats/scripts/text_stats.py data/sample.txt
```

支持同时统计多个文件：

```bash
python skills/text-stats/scripts/text_stats.py data/file1.txt data/file2.txt
```

执行后输出 JSON 格式的统计结果。

## 输出目录规范

| 路径 | 用途 | 权限 |
|---|---|---|
| `/mnt/workspace/` | 待统计的文本文件 | 读写 |

## 输出格式

```json
{
  "files": [
    {
      "path": "file1.txt",
      "chars": 1234,
      "words": 200,
      "lines": 30
    }
  ],
  "totals": {
    "chars": 1234,
    "words": 200,
    "lines": 30
  }
}
```

## 依赖

- bash（系统自带）
- wc 命令（系统自带）
