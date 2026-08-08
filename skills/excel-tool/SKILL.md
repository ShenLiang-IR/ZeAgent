---
name: excel-tool
description: Excel 文件处理工具。读取/创建/编辑 .xlsx 文件，支持多工作表、单元格格式、公式。输出 CSV 或 JSON。
version: "1.0"
enabled: true
category: office
author: system
---

# Excel 工具

读取 Excel 文件转 JSON，或将 JSON 数据写入 Excel 文件。

## 使用方式

```bash
# 读取 Excel
python skills/excel-tool/scripts/main.py --action read --file data.xlsx --sheet Sheet1

# 写入 Excel
python skills/excel-tool/scripts/main.py --action write --file output.xlsx --data '[{"name":"张三","age":25},{"name":"李四","age":30}]'
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--action` | read（读取）或 write（写入） |
| `--file` | Excel 文件路径（必填） |
| `--sheet` | 工作表名称（可选，默认第一个） |
| `--data` | JSON 数据（write 时必填） |

## 依赖

- openpyxl（pip install openpyxl）
