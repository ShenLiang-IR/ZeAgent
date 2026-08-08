---
name: datetime-tool
description: 日期时间工具。获取当前时间、时间格式转换、时间差计算。支持多种时区。
version: "1.0"
enabled: true
category: utility
author: system
---

# 日期时间工具

获取当前时间、时间戳转换、时间差计算。

## 使用方式

```bash
# 获取当前时间
python skills/datetime-tool/scripts/main.py --action now

# 时间戳转日期
python skills/datetime-tool/scripts/main.py --action from-timestamp --value 1693526400

# 日期转时间戳
python skills/datetime-tool/scripts/main.py --action to-timestamp --value "2024-09-01 12:00:00"

# 计算时间差
python skills/datetime-tool/scripts/main.py --action diff --start "2024-01-01" --end "2024-12-31"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--action` | now / from-timestamp / to-timestamp / diff |
| `--value` | 输入值（时间戳或日期字符串） |
| `--start` | 开始日期（仅 diff） |
| `--end` | 结束日期（仅 diff） |
| `--format` | 输出格式（strftime 格式，默认 %Y-%m-%d %H:%M:%S） |
| `--timezone` | 时区（如 Asia/Shanghai，默认本地） |

## 依赖

- Python 3.11+（标准库 datetime）
