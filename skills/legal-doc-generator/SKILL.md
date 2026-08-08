---
name: legal-doc-generator
description: 法律文书生成技能。根据用户需求自动生成起诉状、答辩状、申请书、法律意见书等常见法律文书模板。触发词：生成起诉状、写答辩状、法律文书、起诉书、申请书。
version: "1.0"
enabled: true
category: writing
author: system
tags:
  - legal
  - document
  - template
  - litigation
domain: legal
allowed-tools: write_file
---

# 法律文书生成技能

根据用户提供的案件信息和文书类型，生成符合格式规范的法律文书初稿。

## 使用方式

```bash
python skills/legal-doc-generator/scripts/main.py --type "complaint" --parties "原告信息" --facts "案件事实"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--type` | 文书类型：complaint(起诉状)/answer(答辩状)/application(申请书)/opinion(法律意见书)/notice(律师函)/contract(合同模板) |
| `--parties` | 当事人信息（JSON字符串） |
| `--facts` | 案件事实描述 |
| `--claims` | 诉讼请求（可选） |
| `--output` | 输出文件路径（可选） |
| `--format` | 输出格式：md/docx（默认 md） |

### 支持的文书类型

| 类型 | 说明 |
|---|---|
| complaint | 民事起诉状 |
| answer | 民事答辩状 |
| application | 各类申请书（财产保全/强制执行/回避等） |
| opinion | 法律意见书 |
| notice | 律师函 |
| contract | 通用合同模板 |

### 示例

**生成起诉状**
```bash
python skills/legal-doc-generator/scripts/main.py --type complaint --parties "{\"plaintiff\":\"张三\",\"defendant\":\"李四\"}" --facts "2024年1月借款10万，约定6月还款，至今未还" --claims "请求判令被告返还借款本金10万元及利息"
```

## 输出格式

生成的文书包含标准格式抬头、当事人信息、事实与理由、诉讼请求、此致/落款等完整结构。

## 依赖

- Python 3.11+（标准库，docx 输出需 python-docx）
