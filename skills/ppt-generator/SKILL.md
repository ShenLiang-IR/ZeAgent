---
name: ppt-generator
description: 生成 PowerPoint 演示文稿。根据标题列表和内容生成 .pptx 文件，支持标题页、内容页、图片页。
version: "1.0"
enabled: true
category: office
author: system
---

# PPT 生成工具

根据 JSON 格式的幻灯片数据生成 .pptx 文件。

## 使用方式

```bash
python skills/ppt-generator/scripts/main.py --slides '{"slides":[{"title":"标题页","content":"副标题"},{"title":"内容页","bullets":["要点1","要点2"]}]}' --output data/presentation.pptx
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--slides` | JSON 格式幻灯片数据（必填） |
| `--output` | 输出 .pptx 文件路径（必填） |
| `--template` | 模板文件路径（可选） |

## 依赖

- python-pptx（pip install python-pptx）
