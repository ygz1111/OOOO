#!/bin/bash
# ============================================================================
# 构建 Docker 镜像
# ============================================================================
set -e

cd "$(dirname "$0")/.."

echo "================================================"
echo "  构建 Docker 镜像"
echo "================================================"

# 1. 构建基础镜像
echo ""
echo "[1/6] 构建基础镜像..."
docker build -t registry.local:5000/grid-predict-base:latest \
    -f docker/Dockerfile.base .

# 2. 构建气象采集
echo ""
echo "[2/6] 构建气象采集服务..."
docker build -t grid-predict/weather-collector:latest \
    -f docker/services/weather-collector/Dockerfile .

# 3. 构建特征工程
echo ""
echo "[3/6] 构建特征工程服务..."
docker build -t grid-predict/feature-engine:latest \
    -f docker/services/feature-engine/Dockerfile .

# 4. 构建模型推理
echo ""
echo "[4/6] 构建模型推理服务..."
docker build -t grid-predict/model-inference:latest \
    -f docker/services/model-inference/Dockerfile .

# 5. 构建 API Gateway
echo ""
echo "[5/6] 构建 API Gateway..."
docker build -t grid-predict/api-gateway:latest \
    -f docker/services/api-gateway/Dockerfile .

# 6. 完成
echo ""
echo "[6/6] 构建完成!"
echo ""
echo "镜像列表:"
docker images | grep grid-predict

echo ""
echo "使用 docker compose up -d 启动服务"
