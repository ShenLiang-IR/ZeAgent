---
name: medical-report-parser
description: 医学报告解析技能。解析化验单、影像报告、体检报告等医学报告，提取异常指标并生成解读。触发词：化验单解读、体检报告、异常指标、医学报告分析、检验结果。
version: "1.0"
enabled: true
category: analysis
author: system
tags:
  - medical
  - lab-report
  - diagnosis
  - health-check
domain: medical
allowed-tools: read_file
---

# 医学报告解析技能

解析化验单、影像报告、体检报告等医学报告，自动提取指标项、判断异常值、生成解读说明。

## 使用方式

```bash
python skills/medical-report-parser/scripts/main.py --file "化验单.txt" --type lab
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--file` | 报告文件路径（txt/md，必填） |
| `--type` | 报告类型：lab/imaging/physical（化验单/影像/体检报告） |
| `--reference` | 是否显示参考范围（默认 true） |
| `--output` | 输出文件路径（可选） |

### 支持的指标

| 类别 | 指标示例 |
|---|---|
| 血常规 | WBC、RBC、HGB、PLT、NEUT% |
| 肝功能 | ALT、AST、GGT、TBIL、ALB |
| 肾功能 | Cr、BUN、UA、eGFR |
| 血脂 | TC、TG、HDL-C、LDL-C |
| 血糖 | GLU、HbA1c |
| 肿瘤标志物 | CEA、AFP、CA199、CA125 |

### 示例

```bash
python skills/medical-report-parser/scripts/main.py --file "血常规报告.txt" --type lab

python skills/medical-report-parser/scripts/main.py --file "体检报告.txt" --type physical
```

## 输出格式

```json
{
  "report_type": "lab",
  "items": [
    {
      "name": "白细胞计数(WBC)",
      "value": 12.5,
      "unit": "×10⁹/L",
      "reference": "3.5-9.5",
      "flag": "H",
      "interpretation": "偏高，可能提示感染或炎症"
    }
  ],
  "abnormal_count": 3,
  "summary": "共检测15项，异常3项，建议关注白细胞升高和ALT升高"
}
```

## 依赖

- Python 3.11+（标准库）
