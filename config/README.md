# Agent 配置目录说明

## 配置文件

### 主要配置文件

1. **agent_config.json** - Agent 主配置文件
   - LLM 配置
   - Agent Lightning 配置
   - Context 配置

2. **db_config.json** - 数据库配置文件（可选）
   - 配置 agent 模块使用的数据库（config.db, chat.db）
   - 支持 SQLite 和 PostgreSQL
   - 如果不存在，使用默认 SQLite 配置

### 数据库配置

#### 使用 db_config.json（推荐）

创建 `agent/config/db_config.json`：

```json
{
  "config": {
    "type": "sqlite",
    "path": "data/config.db"
  },
  "chat": {
    "type": "sqlite",
    "path": "data/chat.db"
  }
}
```

#### PostgreSQL 配置示例

```json
{
  "config": {
    "type": "postgresql",
    "host": "localhost",
    "port": 5432,
    "database": "agent_config_db",
    "user": "postgres",
    "password": "your_password"
  },
  "chat": {
    "type": "postgresql",
    "host": "localhost",
    "port": 5432,
    "database": "agent_chat_db",
    "user": "postgres",
    "password": "your_password"
  }
}
```

#### 配置优先级

1. **db_config.json**（最高优先级）
2. **agent_config.json** 中的 `database.{db_name}` 配置（向后兼容）
3. **默认配置**（如果以上都不存在）

### 数据库说明

- **config.db**: Agent 配置数据库（存储 Agent、SubAgent、Tool 配置）
- **chat.db**: 聊天数据库（存储会话和聊天记录）

**重要**：
- agent 模块使用自己的数据库，不应使用 server_data.db

---

## HTTP 配置

### 什么是 HTTP 配置？

HTTP 配置用于集中管理外部工具的 API 基础地址和全局请求头。通过 HTTP 配置，你可以：

1. **集中管理** - 统一管理多个环境（开发、测试、生产）的 API 地址
2. **简化工具配置** - 外部工具通过 `http_config_name` 引用，无需重复配置 `api_base_url`
3. **便于切换环境** - 修改 HTTP 配置即可为所有使用该配置的工具切换环境
4. **共用请求头** - 统一配置全局请求头（如认证信息、Content-Type 等）

### 创建 HTTP 配置

1. **复制示例文件**：
```bash
cp agent/config/http_config.json.example agent/config/http_config.json
```

2. **修改配置文件**，并通过管理员 API 或数据库指令网批量导入。

---

## SubAgent 配置

### SubAgent 配置结构

SubAgent 配置文件位于 `agent/config/subagents/` 目录，每个 SubAgent 对应一个 JSON 文件。

**配置示例：**
```json
{
  "name": "market_research",
  "display_name": "宏观研究",
  "description": "资深的宏观经济分析师...",
  "system_prompt": "你是一位资深的宏观经济分析师...\n\n## 核心能力\n...",
  "tools": [],
  "external_tools": ["search_indicators", "get_indicator_data"],
  "model": null
}
```

### SubAgent 配置字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| name | string | SubAgent 的唯一标识符（用于 API 调用和路由）|
| display_name | string | SubAgent 的中文显示名称 |
| description | string | SubAgent 的功能描述 |
| system_prompt | string | SubAgent 的系统提示词（角色定义、分析框架、输出要求等）|
| tools | array | 内置工具列表（通常为空）|
| external_tools | array | 外部工具列表（工具名称，将被自动注入）|
| model | string\|null | 指定使用的 LLM 模型（null 表示使用默认模型）|

### 工具自动注入机制

**工具自动注入是 Agent 架构的核心特性**：

- **自动生成工具描述** - 系统在运行时根据工具配置自动生成完整的工具描述
- **动态注入到提示词** - 工具描述不包含在系统提示词中，而是动态注入
- **简化系统提示词** - SubAgent 的系统提示词只需包含：
  - **核心角色定义** - SubAgent 的职责和专业背景
  - **分析框架** - 分析问题的方法论和步骤
  - **输出要求** - 对回答格式和内容的要求
  - **不包含** - 具体的工具使用说明（由自动注入机制提供）

---

## 外部工具配置

### 外部工具配置两种方式

**方式一：使用 HTTP 配置（推荐）**
```json
{
  "name": "search_indicators",
  "display_name": "指标查询",
  "api_endpoint": "/api/indicators/search",
  "method": "POST",
  "http_config_name": "invres_server",
  "parameters": {...},
  "enabled": true
}
```

**方式二：直接配置 API 地址**
```json
{
  "name": "search_indicators",
  "display_name": "指标查询",
  "api_base_url": "http://localhost:8001",
  "api_endpoint": "/api/indicators/search",
  "method": "POST",
  "parameters": {...},
  "enabled": true
}
```

