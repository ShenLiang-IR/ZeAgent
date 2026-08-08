---
name: legal-contract-review
description: 合同审查技能。分析合同条款、识别风险点、提供修改建议。支持买卖/租赁/劳动/服务/NDA 等常见合同类型审查。触发词：审查合同、合同风险、条款分析、合同审核。
version: "1.0"
enabled: true
category: analysis
author: system
tags:
  - legal
  - contract
  - compliance
  - risk
domain: legal
allowed-tools: read_file, write_file
---

# 合同审查技能

对合同文本进行结构化审查，识别潜在法律风险、不合规条款和利益失衡点，并提供修改建议。

## 使用方式

```bash
python skills/legal-contract-review/scripts/main.py --file "合同文件路径" --type "contract_type"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--file` | 合同文件路径（txt/md/docx，必填） |
| `--type` | 合同类型：sales/lease/labor/service/nda/partnership（默认 auto 自动识别） |
| `--focus` | 审查重点：all/risk/compliance/balance（默认 all） |
| `--output` | 输出报告路径（可选，默认 stdout） |

### 审查维度

| 维度 | 检查内容 |
|---|---|
| 主体资格 | 签约方信息完整性、授权有效性 |
| 权利义务 | 条款对等性、模糊条款识别 |
| 违约责任 | 违约金合理性、免责条款边界 |
| 知识产权 | IP归属、许可范围、保密义务 |
| 争议解决 | 管辖约定、仲裁条款有效性 |
| 合规检查 | 行业监管要求、数据保护条款 |

### 示例

**审查销售合同**
```bash
python skills/legal-contract-review/scripts/main.py --file "销售合同.txt" --type sales --focus risk
```

**全面审查NDA**
```bash
python skills/legal-contract-review/scripts/main.py --file "保密协议.md" --type nda
```

## 输出格式

```json
{
  "contract_type": "sales",
  "risk_level": "medium",
  "sections": [
    {
      "clause": "违约责任条款",
      "risk_score": 7,
      "issues": ["违约金比例偏高", "缺少免责条款"],
      "suggestions": ["建议将违约金从30%调整为20%", "增加不可抗力免责"]
    }
  ],
  "summary": "整体风险等级：中等，共发现 5 处需关注条款"
}
```

## 依赖

- Python 3.11+（标准库 + python-docx 用于 docx 解析）
