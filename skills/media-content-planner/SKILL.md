---
name: media-content-planner
description: 自媒体内容策划技能。根据主题或行业生成内容日历、选题方向、大纲框架。触发词：内容策划、选题、内容日历、爆款选题、内容大纲、创作规划。
version: "1.0"
enabled: true
category: writing
author: system
tags:
  - media
  - content
  - planning
  - creator
domain: media
allowed-tools: write_file
---

# 自媒体内容策划技能

根据需求和行业特点，生成内容运营策略、选题日历和大纲框架。

## 使用方式

```bash
python skills/media-content-planner/scripts/main.py --topic "AI工具测评" --platform "xiaohongshu" --count 10
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--topic` | 内容主题/行业领域（必填） |
| `--platform` | 发布平台：xiaohongshu/douyin/wechat/bilibili/zhihu/all（默认 all） |
| `--count` | 生成选题数量（默认 10） |
| `--period` | 规划周期：week/month（默认 week） |
| `--audience` | 目标受众描述 |
| `--output` | 输出文件路径（可选） |

### 策划维度

| 维度 | 内容 |
|---|---|
| 选题方向 | 根据行业热点和用户需求生成选题 |
| 内容类型 | 教程/评测/观点/故事/盘点/合集 |
| 标题建议 | 针对平台特性的标题优化方向 |
| 发布时间 | 最佳发布时机建议 |
| 标签策略 | 相关话题标签推荐 |

### 示例

**小红书一周选题**
```bash
python skills/media-content-planner/scripts/main.py --topic "职场效率工具" --platform xiaohongshu --count 7 --audience "25-35岁职场白领女性"
```

**全平台月度规划**
```bash
python skills/media-content-planner/scripts/main.py --topic "个人理财入门" --platform all --count 30 --period month
```

## 输出格式

```json
{
  "topic": "AI工具测评",
  "platform": "xiaohongshu",
  "calendar": [
    {
      "day": "周一",
      "title": "打工人必备！5款免费AI工具实测",
      "type": "教程/测评",
      "tags": ["AI工具", "效率提升", "职场干货"],
      "outline": ["开头痛点引入", "逐个测评推荐", "总结对比表格"]
    }
  ],
  "content_strategy": "突出实用性、亲测体验、个人化表达"
}
```

## 依赖

- Python 3.11+（标准库）
