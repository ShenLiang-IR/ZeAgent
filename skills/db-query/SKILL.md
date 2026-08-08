---
name: db-query
description: 数据库查询工具。执行 SQL 查询并返回 JSON 结果。支持 MySQL/PostgreSQL，只读模式安全限制。
version: "1.0"
enabled: true
category: office
author: system
---

# 数据库查询工具

执行 SQL 查询语句，返回 JSON 格式结果。

## 使用方式

```bash
python skills/db-query/scripts/main.py --sql "SELECT * FROM users LIMIT 10" --db config
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `--sql` | SQL 查询语句（必填，仅支持 SELECT） |
| `--db` | 数据库名称：config/chat/checkpoint/writing/business（默认 config） |
| `--limit` | 返回行数限制（默认 100） |
| `--output` | 输出文件路径（可选） |

## 依赖

- Python 3.11+（标准库 + 项目已有的 SQLAlchemy）
