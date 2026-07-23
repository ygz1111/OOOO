# 智能电网负荷预测系统 - Docker 部署指南

## 目录

1. [架构概览](#1-架构概览)
2. [前置要求](#2-前置要求)
3. [快速启动](#3-快速启动)
4. [配置说明](#4-配置说明)
5. [服务详解](#5-服务详解)
6. [运维管理](#6-运维管理)
7. [故障排查](#7-故障排查)

---

## 1. 架构概览

```
                    ┌─────────────────────────────────────────┐
                    │           用户 / 前端                     │
                    └────────────────┬────────────────────────┘
                                     │ :8000
                    ┌────────────────▼────────────────────────┐
                    │         API Gateway (FastAPI)            │
                    │  负荷预测 / 气象查询 / 系统状态 / 批量预测  │
                    └──┬──────────┬──────────┬─────────────────┘
                       │          │          │
            ┌──────────▼──┐ ┌────▼─────┐ ┌──▼──────────────┐
            │ Weather     │ │ Feature  │ │ Model Inference │
            │ Collector   │ │ Engine   │ │ (PyTorch)       │
            │ :9090       │ │ :8600    │ │ :8500           │
            └──────┬──────┘ └────┬─────┘ └──────┬──────────┘
                   │             │              │
            ┌──────▼─────────────▼──────────────▼──────────┐
            │            Redis Cache :6379                  │
            └──────────────────────────────────────────────┘
            ┌──────────────────────────────────────────────┐
            │       PostgreSQL (TimescaleDB) :5432           │
            └──────────────────────────────────────────────┘
```

### 容器清单

| 服务 | 端口 | 镜像 | 资源限制 |
|------|------|------|---------|
| postgres | 5432 | timescale/timescaledb:2.13.1-pg16 | 512MB / 2CPU |
| redis | 6379 | redis:7-alpine | 300MB |
| weather-collector | 9090 | grid-predict/weather-collector | 256MB |
| feature-engine | 8600 | grid-predict/feature-engine | 512MB |
| model-inference | 8500 | grid-predict/model-inference | 2GB / 4CPU |
| api-gateway | 8000 | grid-predict/api-gateway | 512MB |

---

## 2. 前置要求

### 系统要求

- Docker 20.10+
- Docker Compose 2.0+
- 磁盘空间: ≥ 5GB
- 内存: ≥ 4GB (推荐 8GB)
- CPU: ≥ 4 核

### 安装 Docker (Ubuntu)

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
sudo systemctl enable docker
```

### 验证

```bash
docker --version
docker compose version
```

---

## 3. 快速启动

### 3.1 克隆项目

```bash
cd /opt/grid-predict
```

### 3.2 配置环境变量

```bash
cd docker
cp .env.example .env
# 按需修改 .env 文件
vim .env
```

### 3.3 构建镜像

```bash
# 方式一: 使用构建脚本
bash scripts/build.sh

# 方式二: 使用 Docker Compose
docker compose -f docker-compose.yml build
```

### 3.4 启动所有服务

```bash
# 使用部署脚本
bash scripts/deploy.sh up

# 或直接使用 Docker Compose
cd ..
docker compose -f docker/docker-compose.yml up -d
```

### 3.5 验证服务

```bash
# 查看服务状态
docker compose -f docker/docker-compose.yml ps

# 测试 API
curl http://localhost:8000/
curl http://localhost:8000/api/system/status
curl http://localhost:8000/docs  # OpenAPI 文档
```

### 3.6 测试预测

```bash
# 负荷预测 (自动获取气象数据)
curl -X POST http://localhost:8000/api/prediction/load \
  -H "Content-Type: application/json" \
  -d '{"forecast_hours": 24}'
```

---

## 4. 配置说明

### 4.1 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `POSTGRES_DB` | grid_predict | 数据库名 |
| `POSTGRES_USER` | griduser | 数据库用户 |
| `POSTGRES_PASSWORD` | gridpass123 | 数据库密码 |
| `REDIS_PASSWORD` | redis123 | Redis 密码 |
| `API_PORT` | 8000 | API 对外端口 |
| `COLLECT_INTERVAL` | 300 | 气象采集间隔(秒) |
| `DEVICE` | cpu | 推理设备(cpu/cuda) |
| `LOG_LEVEL` | INFO | 日志级别 |
| `WORKERS` | 2 | API 工作进程数 |

### 4.2 资源限制

在 `docker-compose.yml` 的 `deploy.resources` 中修改:

```yaml
deploy:
  resources:
    limits:
      memory: 2G      # 最大内存
      cpus: "4"        # 最大 CPU 核数
    reservations:
      memory: 1G      # 保留内存
```

---

## 5. 服务详解

### 5.1 PostgreSQL (TimescaleDB)

- **用途**: 存储历史气象数据、预测结果、系统指标
- **特性**: 时序分区 (hypertable)，自动按时间分区
- **表结构**: `weather_data`, `load_predictions`, `system_metrics`, `storage_dispatch`
- **连接**:
  ```bash
  docker exec -it grid-predict-postgres psql -U griduser -d grid_predict
  ```

### 5.2 Redis

- **用途**: 缓存气象数据、预测结果、会话状态
- **配置**: 最大256MB, LRU淘汰策略, AOF持久化
- **连接**:
  ```bash
  docker exec -it grid-predict-redis redis-cli -a redis123
  ```

### 5.3 Weather Collector

- **功能**: 定时从 Open-Meteo API 采集6个气象站点数据
- **采集间隔**: 5分钟 (可配置)
- **健康检查**: `GET http://localhost:9090/health`
- **日志**:
  ```bash
  docker compose logs weather-collector
  ```

### 5.4 Feature Engine

- **功能**: 接收气象数据，生成38维特征，归一化，构建序列
- **端点**: `POST /generate`
- **健康检查**: `GET http://localhost:8600/health`

### 5.5 Model Inference

- **功能**: 加载4个PyTorch模型，提供加权集成推理
- **端点**: `POST /predict`, `GET /model-info`
- **健康检查**: `GET http://localhost:8500/health`
- **模型文件**: 挂载 `outputs/` 目录

### 5.6 API Gateway

- **功能**: 整合所有微服务，对外提供统一API
- **文档**: `http://localhost:8000/docs` (Swagger UI)
- **主要端点**:
  - `POST /api/prediction/load` - 24小时负荷预测
  - `GET /api/weather/current` - 当前气象
  - `GET /api/system/status` - 系统状态
  - `POST /api/prediction/batch` - 批量预测

---

## 6. 运维管理

### 6.1 常用命令

```bash
# 启动
bash scripts/deploy.sh up

# 停止
bash scripts/deploy.sh down

# 重启
bash scripts/deploy.sh restart

# 状态
bash scripts/deploy.sh status

# 查看日志
bash scripts/deploy.sh logs                    # 所有服务
bash scripts/deploy.sh logs api-gateway        # 指定服务

# 清理 (删除容器和卷)
bash scripts/deploy.sh clean
```

### 6.2 日志收集

日志输出到 Docker JSON 日志驱动，默认保留策略:

```yaml
# docker-compose.yml 添加日志配置
services:
  api-gateway:
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

查看实时日志:
```bash
docker compose -f docker/docker-compose.yml logs -f --tail=100
```

### 6.3 监控

每个服务暴露 `/metrics` 端点 (Prometheus 格式):

```bash
# 推理服务指标
curl http://localhost:8500/metrics

# 气象采集指标
curl http://localhost:9090/metrics
```

### 6.4 数据备份

```bash
# 备份 PostgreSQL
docker exec grid-predict-postgres \
  pg_dump -U griduser grid_predict > backup_$(date +%Y%m%d).sql

# 恢复
cat backup_20250723.sql | docker exec -i grid-predict-postgres \
  psql -U griduser -d grid_predict
```

### 6.5 更新镜像

```bash
# 重新构建
docker compose -f docker/docker-compose.yml build

# 滚动更新
docker compose -f docker/docker-compose.yml up -d --no-deps api-gateway
```

---

## 7. 故障排查

### 7.1 服务无法启动

```bash
# 查看容器日志
docker logs grid-predict-gateway

# 查看健康状态
docker inspect --format='{{json .State.Health}}' grid-predict-gateway | jq

# 进入容器
docker exec -it grid-predict-gateway bash
```

### 7.2 数据库连接失败

```bash
# 检查 PostgreSQL 状态
docker exec grid-predict-postgres pg_isready -U griduser

# 检查网络
docker exec grid-predict-gateway ping postgres

# 查看数据库日志
docker logs grid-predict-postgres
```

### 7.3 模型加载失败

```bash
# 检查模型文件
docker exec grid-predict-inference ls -la /app/outputs/

# 检查 GPU (如使用 CUDA)
docker exec grid-predict-inference python -c "import torch; print(torch.cuda.is_available())"
```

### 7.4 内存不足

```bash
# 查看资源使用
docker stats

# 调整限制 (docker-compose.yml)
deploy:
  resources:
    limits:
      memory: 4G  # 增加限制
```

### 7.5 网络问题

```bash
# 检查网络
docker network ls | grep grid
docker network inspect grid-predict_grid-network

# 测试服务间通信
docker exec grid-predict-gateway curl http://model-inference:8500/health
```

---

## 附录: 文件结构

```
docker/
├── docker-compose.yml          # 主编排文件
├── .env.example                # 环境变量模板
├── Dockerfile.base             # 基础镜像 (多阶段)
├── requirements-base.txt       # 基础依赖
├── requirements-ml.txt         # ML 依赖 (PyTorch)
├── config/
│   └── init-db.sql             # 数据库初始化
├── scripts/
│   ├── build.sh                # 构建脚本
│   └── deploy.sh               # 部署脚本
└── services/
    ├── weather-collector/
    │   ├── Dockerfile
    │   ├── collector.py
    │   └── entrypoint.sh
    ├── feature-engine/
    │   ├── Dockerfile
    │   ├── feature_server.py
    │   └── entrypoint.sh
    ├── model-inference/
    │   ├── Dockerfile
    │   ├── inference_server.py
    │   └── entrypoint.sh
    └── api-gateway/
        ├── Dockerfile
        ├── gateway_app.py
        └── entrypoint.sh
```
