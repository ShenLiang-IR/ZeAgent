---
name: medical-drug-query
description: 药品信息查询技能。查询药品说明书、适应症、用法用量、不良反应、药物相互作用等信息。触发词：药品查询、说明书、适应症、用法用量、药物相互作用、禁忌症。
version: "1.0"
enabled: true
category: search
author: system
tags:
  - medical
  - pharmacy
  - drug
  - medication
domain: medical
allowed-tools: read_file
---

# 药品信息查询技能

查询和解析药品说明书信息，提供适应症、用法用量、不良反应、禁忌症、药物相互作用等结构化数据。

## 使用方式

```bash
python skills/medical-drug-query/scripts/main.py --drug "阿莫西林" --info "all"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--drug` | 药品名称（通用名/商品名，必填） |
| `--info` | 查询信息类型：all/indication/dosage/adverse/interaction/contraindication |
| `--output` | 输出文件路径（可选） |

### 查询维度

| 类型 | 说明 |
|---|---|
| indication | 适应症 |
| dosage | 用法用量 |
| adverse | 不良反应 |
| interaction | 药物相互作用 |
| contraindication | 禁忌症 |
| precautions | 注意事项 |
| pharmacology | 药理作用 |

### 示例

**查询完整药品信息**
```bash
python skills/medical-drug-query/scripts/main.py --drug "阿莫西林胶囊"
```

**查询药物相互作用**
```bash
python skills/medical-drug-query/scripts/main.py --drug "华法林" --info interaction
```

## 输出格式

```json
{
  "drug_name": "阿莫西林胶囊",
  "generic_name": "Amoxicillin",
  "category": "抗生素/青霉素类",
  "indications": ["呼吸道感染", "泌尿道感染", ...],
  "dosage": {"adult": "...", "children": "...", "elderly": "..."},
  "adverse_reactions": [...],
  "interactions": [...],
  "contraindications": [...]
}
```

## 依赖

- Python 3.11+（标准库）
- 药品数据接入：在实际部署中，药品数据由 LLM 通过搜索或知识库获取
