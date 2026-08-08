---
name: medical-record-summarizer
description: 病历摘要生成技能。从病历文本中提取关键诊疗信息，生成结构化摘要，包括主诉、现病史、诊断、治疗建议等。触发词：病历摘要、病史总结、诊断分析、病历整理、出院小结。
version: "1.0"
enabled: true
category: analysis
author: system
tags:
  - medical
  - healthcare
  - clinical
  - record
domain: medical
allowed-tools: read_file
---

# 病历摘要生成技能

从病历文本中提取关键诊疗信息，自动生成结构化病历摘要。

## 使用方式

```bash
python skills/medical-record-summarizer/scripts/main.py --text "病历文本内容" --format "soap"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--text` | 病历文本内容（必填） |
| `--file` | 病历文件路径（txt/md，与 --text 二选一） |
| `--format` | 摘要格式：soap/structured/brief（默认 structured） |
| `--extract` | 提取内容：all/diagnosis/treatment/lab（默认 all） |
| `--output` | 输出文件路径（可选） |

### 摘要格式

| 格式 | 说明 |
|---|---|
| soap | SOAP格式（Subjective/Objective/Assessment/Plan） |
| structured | 结构化格式（基本信息/主诉/现病史/诊断/治疗/建议） |
| brief | 简洁格式（一句话摘要 + 关键信息列表） |

### 提取维度

| 维度 | 内容 |
|---|---|
| 基本信息 | 患者基本信息（匿名化处理） |
| 主诉 | 主要症状、持续时间 |
| 现病史 | 发病过程、诊疗经过 |
| 既往史 | 既往疾病、手术、过敏史 |
| 诊断 | 主要诊断、次要诊断、鉴别诊断 |
| 检查结果 | 实验室检查、影像学发现 |
| 治疗方案 | 用药方案、手术建议、康复计划 |
| 随访建议 | 复查时间、注意事项 |

### 示例

```bash
python skills/medical-record-summarizer/scripts/main.py --text "患者男45岁，因胸痛3小时入院..." --format soap

python skills/medical-record-summarizer/scripts/main.py --file "病历.txt" --extract diagnosis,treatment
```

## 输出格式

```json
{
  "summary": {
    "format": "soap",
    "subjective": {"chief_complaint": "胸痛3小时", ...},
    "objective": {"vital_signs": {...}, "lab_results": [...]},
    "assessment": {"primary_diagnosis": "急性心肌梗死", ...},
    "plan": {"medications": [...], "follow_up": "..."}
  },
  "key_findings": ["..."],
  "disclaimer": "本摘要由AI辅助生成，仅供参考，不能替代专业医疗判断。"
}
```

## 依赖

- Python 3.11+（标准库）
