---
name: media-seo-analyzer
description: SEO关键词分析技能。分析内容关键词密度、推荐长尾关键词、评估搜索竞争度、生成优化建议。触发词：SEO分析、关键词挖掘、搜索优化、关键词密度、长尾词。
version: "1.0"
enabled: true
category: analysis
author: system
tags:
  - media
  - seo
  - keyword
  - content-optimization
domain: media
allowed-tools: read_file
---

# SEO关键词分析技能

分析内容的关键词策略，计算关键词密度，推荐长尾关键词，提供内容SEO优化建议。

## 使用方式

```bash
python skills/media-seo-analyzer/scripts/main.py --text "文章内容" --keywords "核心关键词1,核心关键词2"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--text` | 文章/内容文本（必填） |
| `--file` | 内容文件路径（与 --text 二选一） |
| `--keywords` | 目标关键词（逗号分隔） |
| `--mode` | 分析模式：density/suggestion/full（默认 full） |
| `--output` | 输出文件路径（可选） |

### 分析维度

| 维度 | 说明 |
|---|---|
| 关键词密度 | 目标关键词在内容中的出现频率 |
| 词频分析 | 高频词汇统计与分布 |
| 长尾词推荐 | 基于主题的长尾关键词推荐 |
| 标题优化 | 标题中关键词位置和权重建议 |
| 结构优化 | 标题层级（H1/H2/H3）中的关键词分布 |
| 竞争度评估 | 关键词搜索竞争度估算 |

### 示例

```bash
python skills/media-seo-analyzer/scripts/main.py --text "Python是一门流行的编程语言..." --keywords "Python,编程,入门教程" --mode full

python skills/media-seo-analyzer/scripts/main.py --file "article.md" --keywords "自媒体运营,内容创作" --mode suggestion
```

## 输出格式

```json
{
  "keywords": ["Python", "编程", "入门教程"],
  "density": {"Python": 2.5, "编程": 1.8, "入门教程": 0.9},
  "suggestions": ["Python基础教程", "Python入门指南", "零基础学Python"],
  "score": 72,
  "recommendations": ["建议在首段增加核心关键词", "H2标题中考虑加入长尾关键词"]
}
```

## 依赖

- Python 3.11+（标准库）
