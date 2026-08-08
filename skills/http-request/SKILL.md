---
name: http-request
description: 发送 HTTP 请求（GET/POST/PUT/DELETE），支持自定义 headers、body、超时。类似 Dify 的 HTTP 节点，用于调用外部 API。
version: "1.0"
enabled: true
category: network
author: system
---

# HTTP 请求工具

发送 HTTP 请求到指定 URL，支持 GET/POST/PUT/DELETE 方法，自定义请求头和请求体。

## 使用方式

```bash
python skills/http-request/scripts/main.py --url "https://api.example.com/data" --method GET
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--url` | 请求 URL（必填） |
| `--method` | HTTP 方法：GET/POST/PUT/DELETE（默认 GET） |
| `--headers` | 请求头 JSON 字符串，如 `'{"Content-Type":"application/json"}'` |
| `--body` | 请求体 JSON 字符串（POST/PUT 时使用） |
| `--timeout` | 超时秒数（默认 30） |
| `--output` | 输出文件路径（可选，不指定则输出到 stdout） |

### 示例

**GET 请求**
```bash
python skills/http-request/scripts/main.py --url "https://httpbin.org/get"
```

**POST 请求**
```bash
python skills/http-request/scripts/main.py \
  --url "https://httpbin.org/post" \
  --method POST \
  --headers '{"Content-Type":"application/json"}' \
  --body '{"name":"test","value":123}'
```

## 输出格式

JSON 格式的响应，包含 status_code、headers、body。

## 依赖

- Python 3.11+（使用 urllib，无第三方依赖）
