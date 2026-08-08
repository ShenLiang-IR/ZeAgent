---
name: json-tool
description: 格式化、压缩、查询 JSON 数据，支持 jq 风格的简单路径查询
version: 1.0
enabled: true
---

# JSON 工具

对 JSON 数据进行格式化（美化/压缩）、键提取、简单路径查询。

> **重要**：不要读取 JavaScript 脚本文件本身，只需按照以下参数说明通过 `bash` 工具直接调用即可。

## 使用方式

使用 `bash` 工具执行 Node.js 脚本（项目根目录下）：

```bash
node skills/json-tool/scripts/json_tool.js --input data/data.json --action <操作>
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--input` | 输入 JSON 文件路径，或直接传 JSON 字符串 |
| `--action` | 操作类型：`format`（美化）、`minify`（压缩）、`keys`（提取所有键）、`query`（路径查询） |
| `--path` | 路径表达式（仅 `query` 操作使用），如 `users.0.name` |

### 示例

**格式化 JSON**

先将 JSON 数据写入 `data/`，然后：

```bash
node skills/json-tool/scripts/json_tool.js --input data/data.json --action format
```

**提取所有键**

```bash
node skills/json-tool/scripts/json_tool.js --input data/data.json --action keys
```

**路径查询**

```bash
node skills/json-tool/scripts/json_tool.js --input data/data.json --action query --path users.0.name
```

## 输出目录规范

| 路径 | 用途 | 权限 |
|---|---|---|
| `/mnt/workspace/` | 输入 JSON 文件 | 读写 |
| `/mnt/outputs/` | 输出结果文件 | 读写 |

## 依赖

- Node.js >= 18（使用内置 API，无额外 npm 依赖）
