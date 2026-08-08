# 容器化设计 — Dockerfile + compose + CI（P0）

> 日期：2026-07-19
> 状态：📝 DESIGN（待评审）
> 上下文：企业级短板补齐——运维底座

## 1. 背景

项目根**没有 Dockerfile**，仅有 `docker-compose.langfuse.yml`（给 Langfuse 用）。当前部署用 conda 环境 + `start_server.bat/sh`——开发环境与生产环境不一致，难以水平扩展、难以 CI/CD、难以灾备。

## 2. 目标

- **G1**：Dockerfile 多阶段构建（build 阶段装依赖，runtime 阶段精简镜像）
- **G2**：docker-compose.yml 编排后端 + 前端 + MySQL + Langfuse 一键启动
- **G3**：GitHub Actions CI：lint + test + build + push image
- **G4**：.env.example + config 标准化（dev/staging/prod 配置隔离）
- **G5**：镜像体积 < 1GB（runtime 阶段用 slim/python:3.13-slim）
- **G6**：非 root 用户运行（安全）

## 3. 数据模型

无数据模型——纯基础设施。

## 4. Dockerfile 设计

### `Dockerfile.backend`（新建）

```dockerfile
# ─── build 阶段：装依赖 ───
FROM python:3.13-slim AS builder
WORKDIR /app
# 系统依赖（pymysql/sqlalchemy 编译需要的）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc default-libmysqlclient-dev pkg-config && \
    rm -rf /var/lib/apt/lists/*
# 用 uv 装依赖（比 pip 快）
COPY pyproject.toml* requirements.txt ./
RUN pip install --no-cache-dir uv && \
    uv pip install --system --no-cache -r requirements.txt

# ─── runtime 阶段：精简镜像 ───
FROM python:3.13-slim AS runtime
WORKDIR /app
# 运行时系统依赖（mysqlclient 运行时只需 client 库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-mysql-client && \
    rm -rf /var/lib/apt/lists/* && \
    # 非 root 用户
    useradd -m -u 1000 agent
# 从 builder 复制已装的 Python 包
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
# 复制项目代码
COPY --chown=agent:agent . /app
USER agent
EXPOSE 8072
# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8072/').read()"
# 启动命令（生产用 uvicorn 不带 reload）
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8072", "--workers", "4"]
```

### `Dockerfile.frontend`（新建）

```dockerfile
# ─── build 阶段：npm build ───
FROM node:20-alpine AS builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci --legacy-peer-deps
COPY frontend/ ./
RUN npm run build

# ─── runtime 阶段：nginx 静态服务 ───
FROM nginx:alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
# nginx 配置：SPA fallback + /api 反向代理到后端
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget --spider http://localhost/ || exit 1
```

### `frontend/nginx.conf`（新建）

```nginx
server {
    listen 80;
    location /api/ {
        proxy_pass http://backend:8072;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }
}
```

## 5. docker-compose.yml 设计

### `docker-compose.yml`（新建，整合 Langfuse）

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile.backend
    ports: ["8072:8072"]
    env_file: .env
    depends_on:
      mysql:
        condition: service_healthy
      langfuse:
        condition: service_started
    restart: unless-stopped
    volumes:
      - ./data:/app/data        # 持久化数据
      - ./config:/app/config    # 配置文件
      - ./logs:/app/logs

  frontend:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    ports: ["3000:80"]
    depends_on: [backend]
    restart: unless-stopped

  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: ${MYSQL_DATABASE:-agent}
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  langfuse:
    image: langfuse/langfuse:latest
    ports: ["3001:3000"]
    env_file: langfuse.env
    depends_on:
      postgres: { condition: service_healthy }
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${LANGFUSE_DB_USER}
      POSTGRES_PASSWORD: ${LANGFUSE_DB_PASSWORD}
      POSTGRES_DB: langfuse
    volumes:
      - langfuse_pg:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${LANGFUSE_DB_USER}"]
      interval: 10s
      retries: 5
    restart: unless-stopped

volumes:
  mysql_data:
  langfuse_pg:
```

### `.env.example`（新建）

```env
# 数据库
MYSQL_ROOT_PASSWORD=changeme
MYSQL_DATABASE=agent
MYSQL_USER=agent
MYSQL_PASSWORD=changeme

# 后端配置（覆盖 config/agent_config.json 里的 ${VAR:default}）
AGENT_CONFIG_DIR=/app/config
LLM_API_KEY=changeme
LLM_BASE_URL=https://api.qnaigc.com/v1
LLM_MODEL=qwen-turbo

# Langfuse
LANGFUSE_PUBLIC_KEY=changeme
LANGFUSE_SECRET_KEY=changeme
LANGFUSE_HOST=http://langfuse:3000

# Langfuse DB
LANGFUSE_DB_USER=langfuse
LANGFUSE_DB_PASSWORD=changeme
```

## 6. CI 设计

### `.github/workflows/ci.yml`（新建）

```yaml
name: CI
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]
jobs:
  backend-test:
    runs-on: ubuntu-latest
    services:
      mysql:
        image: mysql:8.0
        env: { MYSQL_ROOT_PASSWORD: test, MYSQL_DATABASE: agent_test }
        ports: ["3306:3306"]
        options: >-
          --health-cmd="mysqladmin ping"
          --health-interval=10s --health-timeout=5s --health-retries=5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -r requirements.txt
      - run: python -m pytest test/ --ignore=test/test_skills.py
      - run: python migrate_trigger_schema.py

  frontend-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: cd frontend && npm ci --legacy-peer-deps
      - run: cd frontend && npx vitest run
      - run: cd frontend && npx vite build

  docker-build:
    needs: [backend-test, frontend-test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - run: docker build -f Dockerfile.backend -t agent-backend:ci .
      - run: docker build -f Dockerfile.frontend -t agent-frontend:ci .
```

## 7. 测试策略

容器化是基础设施，**不适合传统单元测试**，主要靠：

| 验证 | 方式 |
|---|---|
| `test_docker_backend_builds` | CI 跑 `docker build` 验证可构建 |
| `test_docker_frontend_builds` | 同上 |
| `test_compose_up_all_services_healthy` | CI 跑 `docker compose up -d` 后等所有 healthcheck 通过 |
| `test_backend_healthcheck` | curl http://localhost:8072/ 返回 200 |
| `test_frontend_serves_index` | curl http://localhost:3000/ 含 `<div id="app">` |
| `test_api_proxy_works` | curl http://localhost:3000/api/ → 代理到 8072 |
| `test_mysql_persistence` | 重启 backend 后数据仍在 |
| `test_non_root_user` | `docker exec backend whoami` 不返回 root |

**前端容器化验证**：用 docker compose 跑全套，访问前端验证页面可用。

## 8. 文件变更

| 文件 | 类型 |
|---|---|
| `Dockerfile.backend` | 新建 |
| `Dockerfile.frontend` | 新建 |
| `frontend/nginx.conf` | 新建 |
| `docker-compose.yml` | 新建（整合 docker-compose.langfuse.yml） |
| `.env.example` | 新建 |
| `.dockerignore` | 新建 |
| `.github/workflows/ci.yml` | 新建 |
| `requirements.txt` | 改：加 `gunicorn`（生产 WSGI/ASGI 服务器，可选） |
| `start_server.bat` / `start_server.sh` | 改：加说明（生产用 docker compose） |
| `README.md` | 改：加容器化部署章节 |

## 9. 关键设计决策

1. **多阶段构建**：builder 装依赖，runtime 精简。**理由**：镜像体积从 ~2GB 降到 ~500MB。
2. **用 uv 而非 pip**：装依赖快 5-10 倍。**备选**：pip。**推荐**：uv。
3. **runtime 用 python:3.13-slim 而非 alpine**：alpine 的 musl 与某些 C 扩展不兼容（pymysql 之类）。**推荐**：slim 稳妥。
4. **非 root 用户**：合规底线。**理由**：容器逃逸时降权。
5. **多 worker（uvicorn --workers 4）**：生产用多进程。**注意**：APScheduler 多 worker 需要 SQLAlchemyJobStore（与持久化方案联动）。**第一期**：单 worker；第二期：多 worker。
6. **不写 K8s manifests**：第一期只 docker compose，K8s 第二期。**理由**：docker compose 覆盖 90% 企业内部部署。
7. **前端用 nginx 而非 vite dev**：生产用静态服务。**理由**：性能 + 资源占用。
8. **config 目录挂载而非构建时 COPY**：配置可热更新（不用重建镜像）。**注意**：生产敏感配置走环境变量。

## 10. 兼容性影响

- 不影响现有 conda 开发流程（开发仍可用 `start_server.bat`）
- `docker-compose.langfuse.yml` 被合并到 `docker-compose.yml`（langfuse 作为其中一个 service）
- CI 不阻塞 PR——只跑 lint + test，build 失败不阻塞 merge（初期）
- 镜像构建依赖项目根 requirements.txt 与 frontend/package.json——后续若新建 pyproject.toml，Dockerfile 同步调整
- 与 APScheduler 持久化方案联动：多 worker 部署时必须先切 SQLAlchemyJobStore
