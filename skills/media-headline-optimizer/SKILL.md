---
name: media-headline-optimizer
description: 标题优化技能。根据平台特性和用户心理，对标题进行优化，提升点击率和阅读量。支持多平台多风格。触发词：标题优化、爆款标题、标题改写、提升点击率。
version: "1.0"
enabled: true
category: writing
author: system
tags:
  - media
  - headline
  - copywriting
  - optimization
domain: media
allowed-tools: write_file
---

# 标题优化技能

根据平台特性和文案心理学，对标题进行多维度优化，提升吸引力和点击率。

## 使用方式

```bash
python skills/media-headline-optimizer/scripts/main.py --title "原标题" --platform "xiaohongshu" --count 5
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--title` | 原标题文本（必填） |
| `--platform` | 目标平台：xiaohongshu/douyin/wechat/bilibili/zhihu/all |
| `--count` | 生成变体数量（默认 5） |
| `--style` | 风格：curiosity/digital/emotional/contrast/pain_point/all（默认 all） |
| `--analyze` | 是否分析原标题（默认 true） |
| `--output` | 输出文件路径（可选） |

### 标题风格

| 风格 | 说明 | 示例模式 |
|---|---|---|
| curiosity | 好奇心驱动 | "你不知道的XX秘密" |
| digital | 数字列举型 | "5个让XX效率翻倍的方法" |
| emotional | 情感共鸣型 | "看完我哭了，XX真的太..." |
| contrast | 对比冲突型 | "月薪3千和月薪3万的XX区别" |
| pain_point | 痛点解决型 | "别再XX了！试试这个方法" |
| urgency | 紧迫感 | "限时！XX今天截止" |

### 示例

```bash
python skills/media-headline-optimizer/scripts/main.py --title "如何提高工作效率" --platform xiaohongshu --count 5 --style all

python skills/media-headline-optimizer/scripts/main.py --title "Python编程入门教程" --platform bilibili --style curiosity,digital
```

## 输出格式

```json
{
  "original": "如何提高工作效率",
  "score": {"length": 8, "has_number": false, "has_emoji": false, "score": 65},
  "variants": [
    {
      "title": "打工人亲测！这5个效率方法让我的工作速度翻3倍",
      "style": "digitial",
      "score": 92,
      "highlights": ["数字列举", "痛点共鸣", "结果承诺"]
    }
  ],
  "recommendation": "最推荐变体#1，包含数字、情感和实用价值"
}
```

## 依赖

- Python 3.11+（标准库）
