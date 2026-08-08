---
name: format-table-to-json
description: >-
  将带合并单元格的表格数据转换为 Tiptap 编辑器兼容的 JSON 格式。
  当用户需要生成表格 JSON、转换表格数据、处理合并单元格表格时触发。
  Triggers on "表格JSON", "table JSON", "合并单元格", "Tiptap 表格", "format table".
version: "2.0"
enabled: true
category: data
author: system
---

# 表格数据转 JSON 工具

将带有合并单元格（rowspan/colspan）的二维表格数据转换为 Tiptap 编辑器兼容的 JSON 格式。

> **重要**：不要读取 Python 脚本文件本身，只需按照以下参数说明通过 `bash` 工具直接调用即可。

## 使用方式

使用 `bash` 工具执行 Python 脚本（项目根目录下）：

```bash
python skills/format-table-to-json-V2/scripts/format_table_to_json.py --data '数据JSON'
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--data` | JSON 数据字符串，或 `@/mnt/workspace/data.json` 从文件读取 |
| `--output` | 可选，输出文件路径（自动加 `.json` 后缀），不指定则输出到 stdout |
| `--header-rows` | 可选，表头行数（默认自动检测） |
| `--no-auto-style` | 禁用智能默认样式 |

## 输入格式（三种，自动检测）

### 格式一：稀疏 2D 数组（推荐，LLM 友好）

每行只写有内容的单元格，**被 rowspan/colspan 覆盖的单元格无需写 null**，代码自动补全。

```json
[
  [{"text": "班级"}, {"text": "学生"}, {"text": "语文"}, {"text": "数学"}, {"text": "英语"}],
  [{"text": "一班", "rowspan": 3}, {"text": "张三"}, {"text": "90"}, {"text": "95"}, {"text": "88"}],
  [{"text": "李四"}, {"text": "85"}, {"text": "78"}, {"text": "92"}],
  [{"text": "王五"}, {"text": "92"}, {"text": "88"}, {"text": "95"}]
]
```

### 格式二：Dense 2D 数组（兼容旧格式）

含 null 占位的完整数组，仍然支持。

```json
[
  [{"text": "班级", "rowspan": 3}, {"text": "学生"}, {"text": "语文"}],
  [null, {"text": "李四"}, {"text": "85"}],
  [null, {"text": "王五"}, {"text": "92"}]
]
```

### 格式三：结构 + 数据分离（大型表格推荐）

当数据行超过 10 行时，将表头与数据分离，减少 LLM 工作量：

```json
{
  "cols": 9,
  "header_rows": 3,
  "headers": [
    [{"text": "2024年度报表", "colspan": 9}],
    [{"text": "收入", "colspan": 3}, {"text": "成本", "colspan": 3}, {"text": "利润", "rowspan": 2}, {"text": "净利润", "rowspan": 2}],
    [{"text": "Q1"}, {"text": "Q2"}, {"text": "Q3"}, {"text": "人力"}, {"text": "运营"}, {"text": "税费"}]
  ],
  "data": [
    ["智能终端", "5200", "5800", "6100", "2100", "1800", "450", "5200", "3900"],
    ["智能终端", "4800", "5200", "5500", "1900", "1600", "420", "4800", "3600"],
    ["云服务", "3800", "4200", "4600", "1500", "1200", "380", "3800", "2800"]
  ],
  "merge_columns": [0],
  "summary": [{"text": "合计"}, {"text": "54100", "colspan": 3}, null, null, {"text": "27230", "colspan": 3}, null, null, {"text": "26400"}, {"text": "19800"}]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `cols` | int | 总列数（可选，从 headers 推断） |
| `header_rows` | int | 表头行数（用于样式检测） |
| `headers` | array | 表头行，保留完整合并信息 |
| `data` | array | 纯数据行（字符串二维数组），无需写合并 |
| `merge_columns` | array | 需要自动合并相邻相同值的列索引列表 |
| `summary` | array | 可选合计行 |

`merge_columns` 会自动将指定列中相邻相同的值合并为一个 rowspan。

## 单元格字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `text` | string | 是 | 单元格文本 |
| `rowspan` | int | 否 | 行合并数，默认 1 |
| `colspan` | int | 否 | 列合并数，默认 1 |
| `align` | string | 否 | 覆盖默认对齐 left/center/right |
| `bold` | bool | 否 | 覆盖默认加粗 |

## 智能默认样式（自动应用，无需手写）

代码自动根据内容和位置应用样式：
- **表头行**（前 N 行）：自动加粗 + 居中
- **数字内容**（整数、小数、百分比、千分位）：自动右对齐
- **其他**：自动居中

仅在需要覆盖默认样式时才写 `align` 或 `bold`。

## 示例

**稀疏格式（推荐）**

```bash
python skills/format-table-to-json-V2/scripts/format_table_to_json.py \
  --data '[[{"text":"标题","colspan":3}],[{"text":"A"},{"text":"B"},{"text":"C"}]]'
```

**大型表格（结构+数据分离）**

先将数据写入临时文件（如 `data/table.json`），然后：

```bash
python skills/format-table-to-json-V2/scripts/format_table_to_json.py \
  --data @data/table.json \
  --output data/table_result
```

## 输出目录规范

| 路径 | 用途 | 权限 |
|---|---|---|
| `/mnt/workspace/` | 中间数据、临时文件 | 读写 |
| `/mnt/outputs/` | 生成文件 | 读写 |

## 输出格式

Tiptap 表格 JSON，结构为：

```json
{
  "type": "table",
  "attrs": { "id": "table-xxx", "sectionUuid": "section-xxx" },
  "content": [
    {
      "type": "tableRow",
      "content": [
        {
          "type": "tableCell",
          "attrs": { "colspan": 2 },
          "content": [{ "type": "paragraph", "attrs": { "textAlign": "center" }, "content": [{ "type": "text", "text": "..." }] }]
        }
      ]
    }
  ]
}
```

## 依赖

- Python 3.11+（系统自带）
