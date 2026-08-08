---
name: legal-case-analyzer
description: 法律案例分析技能。检索相关法条、分析案情要素、提供裁判倾向参考。触发词：案例分析、法条检索、判例查询、法律分析。
version: "1.0"
enabled: true
category: analysis
author: system
tags:
  - legal
  - case-law
  - statute
  - precedent
domain: legal
allowed-tools: read_file
---

# 法律案例分析技能

根据用户提供的案情描述，进行结构化分析：匹配相关法条、搜索类似判例、分析关键要素、提供裁判倾向参考。

## 使用方式

```bash
python skills/legal-case-analyzer/scripts/main.py --case "案情描述" --category "civil"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--case` | 案情描述文本（必填） |
| `--category` | 案件类别：civil/criminal/administrative/commercial/labor（默认 civil） |
| `--keywords` | 检索关键词（逗号分隔，可选） |
| `--output` | 输出文件路径（可选） |

### 分析维度

| 维度 | 内容 |
|---|---|
| 案由识别 | 自动识别案件类型和案由 |
| 主体分析 | 当事人法律关系、主体适格性 |
| 法条匹配 | 匹配相关法律法规条文 |
| 要素提取 | 提取关键事实要素和时间线 |
| 争议焦点 | 识别双方可能争议焦点 |
| 裁判倾向 | 基于类似案例的裁判倾向参考 |

### 示例

**民事合同纠纷分析**
```bash
python skills/legal-case-analyzer/scripts/main.py --case "甲公司与乙公司签订供货合同，乙公司未按期付款..." --category civil --keywords "买卖合同,逾期付款,违约金"
```

**劳动争议分析**
```bash
python skills/legal-case-analyzer/scripts/main.py --case "员工被公司单方面解除劳动合同，未支付补偿金..." --category labor
```

## 输出格式

```json
{
  "case_type": "合同纠纷",
  "category": "civil",
  "key_elements": {
    "parties": ["甲公司(买方)", "乙公司(供应商)"],
    "facts": ["签订供货合同", "货物已交付", "未按期付款"],
    "timeline": ["2024-01: 合同签订", "2024-03: 货物交付", "2024-06: 逾期未付款"]
  },
  "relevant_laws": [
    {"law": "民法典第577条", "content": "当事人不履行合同义务..."},
    {"law": "民法典第585条", "content": "违约金约定..."}
  ],
  "dispute_focus": ["付款义务是否履行", "违约金计算标准"],
  "tendency": "基于类似案例，支持债权方主张概率较高"
}
```

## 依赖

- Python 3.11+（标准库）
