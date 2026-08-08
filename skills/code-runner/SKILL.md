---
name: code-runner
description: 执行 Python 代码片段并返回输出。支持 stdin 输入，限制执行时间。适用于 Agent 动态生成并运行代码的场景。
version: "1.0"
enabled: true
category: developer
author: system
---

# 代码执行器

执行 Python 代码片段，返回 stdout/stderr 和执行结果。

## 使用方式

```bash
python skills/code-runner/scripts/main.py --code "print('hello world')"
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--code` | Python 代码字符串（必填） |
| `--stdin` | stdin 输入内容（可选） |
| `--timeout` | 执行超时秒数（默认 10） |

### 示例

**执行简单代码**
```bash
python skills/code-runner/scripts/main.py --code "result = 3 + 5; print(f'3+5={result}')"
```

**带输入**
```bash
python skills/code-runner/scripts/main.py --code "name = input(); print(f'Hello, {name}!')" --stdin "World"
```

## 输出格式

```json
{
  "stdout": "3+5=8\n",
  "stderr": "",
  "exit_code": 0,
  "duration_ms": 12
}
```

## 依赖

- Python 3.11+（标准库）
