---
name: equity-chart
description: 生成企业股权结构图（PNG），支持多层控股、交叉持股等复杂结构，自动上传到持久存储
version: 2.0
enabled: true
---

# 股权结构图生成器

根据股权关系数据生成股权结构图（PNG 图片），并自动上传到持久存储。

> **重要**：不要读取 Python 脚本文件本身，只需按照以下参数说明通过 `bash` 工具直接调用即可。

## 使用方式

使用 `bash` 工具执行 Python 脚本（项目根目录下）：

```bash
python skills/equity-chart/scripts/equity_chart.py --data '数据JSON' --output data/股权结构图
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--data` | JSON 格式股权数据字符串，或 `@/mnt/workspace/data.json` 从文件读取 |
| `--output` | 输出文件路径（不含 .png 后缀），**统一输出到 `/mnt/outputs/`** |
| `--rankdir` | 图方向：`TB`（从上到下，默认）或 `LR`（从左到右） |
| `--upload` | 生成后自动上传到持久存储（**默认开启**，可省略） |
| `--no-upload` | 仅生成到本地，不上传 |
| `--category` | 上传路径分类前缀（默认 `equity-chart`） |

### 示例

**方式一：直接传 JSON 字符串（推荐）**

```bash
python skills/equity-chart/scripts/equity_chart.py \
  --data '[{"parent":"A集团","child":"B公司","ratio":"70%"},{"parent":"A集团","child":"C公司","ratio":"60%"}]' \
  --output data/equity_chart \
  --rankdir TB
```

**方式二：从文件读取数据（推荐用于大量数据）**

先将数据写入 `data/data.json`，然后：

```bash
python skills/equity-chart/scripts/equity_chart.py \
  --data @data/data.json \
  --output data/equity_chart \
  --rankdir TB
```

## 输出说明

脚本输出包含两部分：

1. **生成结果**：`OK: 股权结构图已保存为 /mnt/outputs/equity_chart.png`
2. **上传结果**（默认自动上传）：`UPLOAD_RESULT: {"provider": "minio", "bucketName": "invres-smart-agent", "filePath": "equity-chart/2026-06-02/a1b2c3d4.png"}`

**重要**：将 `UPLOAD_RESULT` 中的 `provider`、`bucketName` 和 `filePath` 信息返回给用户，前端使用这些字段展示图片。`provider` 标识存储系统类型（minio/http/local），用于后续获取文件时区分存储后端。

## 输出目录规范

| 路径 | 用途 | 权限 |
|---|---|---|
| `/mnt/workspace/` | 中间数据、临时文件 | 读写 |
| `/mnt/outputs/` | 生成文件（图片、报告等） | 读写 |

每个会话拥有独立的目录空间，会话之间互不干扰。

## 数据格式

股权数据为 JSON 数组，每个元素包含：

- `parent`: 母公司/持股方名称
- `child`: 子公司/被持股方名称
- `ratio`: 持股比例（如 "70%"、"51%"）

支持多层控股、交叉持股等复杂结构。

## 输出

PNG 格式图片，保存到指定路径（自动添加 `.png` 后缀），同时上传到持久存储。

## 依赖

- graphviz（Python 包 + 系统需安装 Graphviz）
