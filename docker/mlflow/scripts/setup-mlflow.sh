#!/bin/bash
#
# 智能网格负荷预测系统 - MLflow模型版本管理
#
# 功能:
# - MLflow服务部署
# - 模型注册与版本控制
# - 实验跟踪
# - 模型部署管理
#

# 设置严格模式
set -euo pipefail

# 日志函数
log_info() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $1"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >&2
}

log_warn() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: $1"
}
log_success() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ $1"
}

# 配置参数
export MLFLOW_VERSION="2.10.0"
export MLFLOW_DB_HOST="localhost"
export MLFLOW_DB_PORT="3306"
export MLFLOW_DB_USER="mlflow_user"
export MLFLOW_DB_PASSWORD="MLflowSecure123!"
export MLFLOW_DB_NAME="mlflow_db"
export MLFLOW_PORT=5000
export MLFLOW_ARTIFACT_PATH="/var/lib/mlflow/artifacts"
export MLFLOW_BACKEND_STORE_URI=""

# MLflow Docker配置
export MLFLOW_IMAGE="mlflow:${MLFLOW_VERSION}"
export CONTAINER_NAME="smartgrid-mlflow"
export NETWORK_NAME="smartgrid-network"

# 显示配置信息
show_config() {
    cat << EOF

╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║              MLflow模型版本管理系统部署                         Failure
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝

服务配置:
  版本:        MLflow ${MLFLOW_VERSION}
  端口:        ${MLFLOW_PORT}
  容器名:      ${CONTAINER_NAME}
  网络:        ${NETWORK_NAME}

数据库配置:
  主机:        ${MLFLOW_DB_HOST}
  端口:        ${MLFLOW_DB_PORT}
  用户:        ${MLFLOW_DB_USER}
  数据库:      ${MLFLOW_DB_NAME}

存储配置:
  工件目录:    ${MLFLOW_ARTIFACT_PATH}
  类型:        本地文件系统
  
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

继续部署? (yes/no): 
EOF
    
    read -r confirm
    if [ "$confirm" != "yes" ]; then
        log_info "部署已取消"
        exit 0
    fi
}

# 环境检查
check_environment() {
    log_info "环境检查..."
    
    # 检查Docker
    if ! command -v docker >/dev/null 2>&1; then
        log_error "❌ Docker未安装"
        exit 1
    fi
    
    # 检查Docker Compose
    if ! command -v docker-compose >/dev/null 2>&1; then
        log_warn "⚠️  docker-compose未安装，使用docker run"
    fi
    
    # 检查端口
    if netstat -tln | grep -q ":${MLFLOW_PORT} "; then
        log_error "❌ 端口${MLFLOW_PORT}已被占用"
        exit 1
    fi
    
    # 检查存储空间
    available_space=$(df /var/lib | tail -1 | awk '{print $4}')
    available_space_gb=$((available_space / 1024 / 1024))
    
    if [ $available_space_gb -lt 10 ]; then
        log_warn "⚠️  可用空间较少: ${available_space_gb}GB"
    else
        log_success "✅ 存储空间充足: ${available_space_gb}GB"
    fi
    
    log_success "环境检查通过"
}

# 准备存储目录
prepare_storage() {
    log_info "创建MLflow存储目录..."
    
    # 创建主目录
    mkdir -p "$MLFLOW_ARTIFACT_PATH"
    chmod 755 "$MLFLOW_ARTIFACT_PATH"
    
    # 创建子目录
    subdirs=("models" "experiments" "artifacts" "tmp")
    
    for dir in "${subdirs[@]}"; do
        dir_path="${MLFLOW_ARTIFACT_PATH}/${dir}"
        mkdir -p "$dir_path"
        chmod 755 "$dir_path"
        log_info "创建目录: $dir_path"
    done
    
    log_success "✅ 存储目录创建完成"
}

# 确保数据库就绪
ensure_database() {
    log_info "确保数据库就绪..."
    
    # 检查MySQL服务
    if ! docker ps | grep -q "smartgrid-mysql"; then
        log_warn "⚠️  MySQL容器未运行，尝试启动或配置外部数据库"
        return 0
    fi
    
    # 等待数据库就绪
    max_attempts=60
    attempt=0
    
    log_info "等待MySQL数据库就绪..."
    
    while [ $attempt -lt $max_attempts ]; do
        # 通过Docker连接到MySQL
        if docker exec smartgrid-mysql mysql -h${MLFLOW_DB_HOST} -P${MLFLOW_DB_PORT} \
            -u${MLFLOW_DB_USER} -p${MLFLOW_DB_PASSWORD} -e "SELECT 1" >/dev/null 2>&1; then
            break
        fi
        
        attempt=$((attempt + 1))
        sleep 2
        
        if [ $attempt -eq $max_attempts ]; then
            log_error "❌ 数据库连接超时"
            exit 1
        fi
done
    
    log_success "✅ 数据库已就绪"
    
    # 确保MLflow数据库存在
    setup_mlflow_database
}

# 设置MLflow数据库
setup_mlflow_database() {
    log_info "配置MLflow数据库..."
    
    # 检查数据库是否存在
    if ! docker exec smartgrid-mysql mysql -h${MLFLOW_DB_HOST} -P${MLFLOW_DB_PORT} \
        -uroot -p"your-root-password" -e "USE ${MLFLOW_DB_NAME}" >/dev/null 2>&1; then
        
        log_info "创建MLflow数据库..."
        
        # 创建数据库
        docker exec smartgrid-mysql mysql -h${MLFLOW_DB_HOST} -P${MLFLOW_DB_PORT} \
            -uroot -p"your-root-password" -e "CREATE DATABASE ${MLFLOW_DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" || true
        
        # 创建用户
        docker exec smartgrid-mysql mysql -h${MLFLOW_DB_HOST} -P${MLFLOW_DB_PORT} \
            -uroot -p"your-root-password" -e "CREATE USER IF NOT EXISTS '${MLFLOW_DB_USER}'@'%' IDENTIFIED BY '${MLFLOW_DB_PASSWORD}';" || true
        
        # 授权
        docker exec smartgrid-mysql mysql -h${MLFLOW_DB_HOST} -P${MLFLOW_DB_PORT} \
            -uroot -p"your-root-password" -e "GRANT ALL PRIVILEGES ON ${MLFLOW_DB_NAME}.* TO '${MLFLOW_DB_USER}'@'%';" || true
        
        docker exec smartgrid-mysql mysql -h${MLFLOW_DB_HOST} -P${MLFLOW_DB_PORT} \
            -uroot -p"your-root-password" -e "FLUSH PRIVILEGES;" || true
    fi
    
    log_success "✅ 数据库配置完成"
}

# 构建后端存储URI
build_backend_uri() {
    if [ -n "$MLFLOW_BACKEND_STORE_URI" ]; then
        echo "$MLFLOW_BACKEND_STORE_URI"
    else
        echo "mysql+pymysql://${MLFLOW_DB_USER}:${MLFLOW_DB_PASSWORD}@${MLFLOW_DB_HOST}:${MLFLOW_DB_PORT}/${MLFLOW_DB_NAME}"
    fi
}

# 启动MLflow服务
start_mlflow_service() {
    log_info "启动MLflow服务..."
    
    backend_uri=$(build_backend_uri)
    
    # 检查是否使用Docker Compose
    if command -v docker-compose >/dev/null 2>&1; then
        
        # 创建docker-compose配置文件
        create_docker_compose_file
        
        # 启动服务
        if docker-compose -f /docker/mlflow/docker-compose.mlflow.yml up -d; then
            log_success "✅ Docker Compose启动成功"
        else
            log_error "❌ Docker Compose启动失败"
            exit 1
        fi
        
    else
        # 使用docker run启动
        log_warn "⚠️  使用docker run启动(推荐使用docker-compose)"
        
        # 停止可能存在的容器
        docker stop "$CONTAINER_NAME" || true
        docker rm "$CONTAINER_NAME" || true
        
        # 启动MLflow容器
        if docker run -d \
            --name "$CONTAINER_NAME" \
            --network "smartgrid-network" \
            -p "${MLFLOW_PORT}:${MLFLOW_PORT}" \
            -e MLFLOW_PORT="${MLFLOW_PORT}" \
            -e BACKEND_STORE_URI="$backend_uri" \
            -e ARTIFACT_ROOT="file://${MLFLOW_ARTIFACT_PATH}" \
            -v "${MLFLOW_ARTIFACT_PATH}:${MLFLOW_ARTIFACT_PATH}" \
            ghcr.io/mlflow/mlflow:${MLFLOW_VERSION} \
            mlflow server \
            --host 0.0.0.0 \
            --port "${MLFLOW_PORT}" \
            --backend-store-uri "$backend_uri" \
            --default-artifact-root "file://${MLFLOW_ARTIFACT_PATH}"; then
            
            log_success "✅ MLflow容器启动成功"
        else
            log_error "❌ MLflow容器启动失败"
            exit 1
        fi
    fi
    
    # 等待服务就绪
    wait_for_service
}

# 创建docker-compose文件
create_docker_compose_file() {
    log_info "创建Docker Compose配置文件..."
    
    backend_uri=$(build_backend_uri)
    
    compose_file="/docker/mlflow/docker-compose.mlflow.yml"
    
    mkdir -p $(dirname "$compose_file")
    
    cat > "$compose_file" << EOF
# MLflow服务配置
# 集成到docker/docker-compose-ha.yml

version: '3.8'

services:
  mlflow-server:
    image: ghcr.io/mlflow/mlflow:${MLFLOW_VERSION}
    container_name: ${CONTAINER_NAME}
    restart: unless-stopped
    
    # 网络和端口
    networks:
      - ${NETWORK_NAME}
    ports:
      - "${MLFLOW_PORT}:${MLFLOW_PORT}"
      
    # 环境变量
    environment:
      - MLFLOW_TRACKING_URI=http://localhost:${MLFLOW_PORT}
      - MLFLOW_DEFAULT_ARTIFACT_ROOT=file://${MLFLOW_ARTIFACT_PATH}
      
    # 挂载卷
    volumes:
      - mlflow_artifacts:${MLFLOW_ARTIFACT_PATH}
      
    # 启动命令
    command: >
      mlflow server
        --host 0.0.0.0
        --port ${MLFLOW_PORT}
        --backend-store-uri ${backend_uri}
        --default-artifact-root file://${MLFLOW_ARTIFACT_PATH}
        --workers 4
        
    # 健康检查
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:${MLFLOW_PORT}/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      
    # 资源限制
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M

# Docker卷
volumes:
  mlflow_artifacts:
    driver: local
    driver_opts:
      o: bind
      type: none
      device: ${MLFLOW_ARTIFACT_PATH}

# 网络配置
networks:
  ${NETWORK_NAME}:
    external: true
    name: ${NETWORK_NAME}
EOF
    
    log_success "✅ Docker Compose配置创建: $compose_file"
}

# 等待服务就绪
wait_for_service() {
    log_info "等待MLflow服务就绪..."
    
    max_attempts=60
    attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        # 检查服务健康状态
        if curl -s -f "http://localhost:${MLFLOW_PORT}/health" >/dev/null 2>&1; then
            break
        fi
        
        # 备用检查方法
        if docker inspect "$CONTAINER_NAME" --format='{{.State.Health.Status}}' 2>/dev/null | grep -q "healthy"; then
            break
        fi
        
        attempt=$((attempt + 1))
        sleep 2
        
        if [ $attempt -gt 30 ]; then
            log_warn "⚠️  健康检查超时，但服务可能已启动"
            break
        fi
    done
    
    if [ $attempt -eq $max_attempts ]; then
        log_error "❌ 服务启动超时"
        exit 1
    fi
    
    log_success "✅ MLflow服务已就绪"
    
    # 显示访问信息
    log_info "MLflow地址: http://localhost:${MLFLOW_PORT}"
}

# 验证安装
verify_installation() {
    log_info "验证MLflow安装..."
    
    # 检查容器状态
    if docker ps | grep -q "$CONTAINER_NAME"; then
        log_success "✅ 容器运行正常"
    else
        log_error "❌ 容器未运行"
        exit 1
    fi
    
    # 测试API端点
    endpoints=("health" "api/2.0/mlflow/experiments/list")
    
    for endpoint in "${endpoints[@]}"; do
        if curl -s -f "http://localhost:${MLFLOW_PORT}/${endpoint}" >/dev/null 2>&1; then
            log_success "✅ 端点 ${endpoint} 访问正常"
        else
            log_warn "⚠️  端点 ${endpoint} 访问异常"
        fi
    done
    
    # 检查数据库连接
    if docker exec "$CONTAINER_NAME" curl -s -f "http://localhost:${MLFLOW_PORT}" >/dev/null 2>&1; then
        log_success "✅ 服务连通性测试通过"
    else
        log_error "❌ 服务连通性异常"
        exit 1
    fi
}

# 集成到应用
setup_integration() {
    log_info "配置应用集成..."
    
    # 创建Python示例代码
    create_integration_example
    
    # 创建环境配置文件
    create_env_file
    
    log_success "✅ 集成配置完成"
}

# 创建集成示例
create_integration_example() {
    log_info "创建集成示例..."
    
    example_file="/docker/mlflow/examples/mlflow_integration.py"
    
    mkdir -p $(dirname "$example_file")
    
    cat > "$example_file" << 'EOF'
"""
智能电网负荷预测 - MLflow集成示例

功能:
- 模型训练跟踪
- 参数记录
- 指标监控
- 模型注册
- 版本管理
"""

import mlflow
import mlflow.sklearn
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
import json
import os

# 配置MLflow
MLFLOW_TRACKING_URI = os.environ.get('MLFLOW_TRACKING_URI', 'http://localhost:5000')
mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

# 设置实验
EXPERIMENT_NAME = "smartgrid_load_forecasting"
mlflow.set_experiment(EXPERIMENT_NAME)

def train_and_log_model():
    """训练模型并记录MLflow"""
    
    print(f"开始训练实验: {EXPERIMENT_NAME}")
    
    with mlflow.start_run():
        # 1. 记录参数
        params = {
            'model_type': 'RandomForest', 
            'n_estimators': 100,
            'max_depth': 10,
            'min_samples_split': 5,
            'random_state': 42
        }
        mlflow.log_params(params)
        
        # 2. 记录数据特征
        features = [
            'temperature', 'humidity', 'wind_speed', 'radiation',
            'hour_sin', 'hour_cos', 'day_of_week', 'month',
            'load_lag_24h', 'load_lag_168h', 'is_weekend'
        ]
        mlflow.log_text(json.dumps(features, indent=2), 'features.json')
        
        # 3. 模拟训练过程
        np.random.seed(42)
        X_train = np.random.randn(1000, len(features))
        y_train = np.random.randn(1000)
        
        # 4. 训练模型
        model = RandomForestRegressor(
            n_estimators=params['n_estimators'],
            max_depth=params['max_depth'], 
            min_samples_split=params['min_samples_split'],
            random_state=params['random_state']
        )
        model.fit(X_train, y_train)
        
        # 5. 模型评估
        y_pred = model.predict(X_train)
        mae = mean_absolute_error(y_train, y_pred)
        mse = mean_squared_error(y_train, y_pred)
        rmse = np.sqrt(mse)
        
        # 记录指标
        metrics = {
            'mae': mae,
            'mse': mse,
            'rmse': rmse,
            'r2': model.score(X_train, y_train)
        }
        mlflow.log_metrics(metrics)
        
        # 6. 记录训练信息
        training_info = {
            'training_samples': len(X_train),
            'feature_count': len(features),
            'training_time': '模拟训练时间',
            'model_version': '1.0.0',
            'framework_version': 'sklearn-1.3.0'
        }
        mlflow.log_dict(training_info, 'training_info.json')
        
        # 7. 保存模型
        mlflow.sklearn.log_model(
            sk_model=model,
            artifact_path="model",
            registered_model_name="LoadForecast_RandomForest"
        )
        
        # 8. 记录数据集信息
        mlflow.log_artifact('features.json')
        
        print(f"训练完成 - MAE: {mae:.4f}, RMSE: {rmse:.4f}")
        
        return {
            'run_id': mlflow.active_run().info.run_id,
            'metrics': metrics
        }

def register_model_version():
    """注册模型版本"""
    
    client = mlflow.tracking.MlflowClient()
    
    # 获取最佳模型
    experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        order_by=["metrics.rmse ASC"]
    )
    
    if runs:
        best_run = runs[0]
        
        # 注册模型
        result = mlflow.register_model(
            model_uri=f"runs:/{best_run.info.run_id}/model",
            name="LoadForecast_BestModel"
        )
        
        print(f"模型已注册: {result.name} v{result.version}")
        
        # 设置标签
        client.set_model_version_tag(
            name=result.name,
            version=result.version,
            key="dataset",
            value="smartgrid-v1"
        )
        
        return result
        
def deploy_model():
    """部署模型到生产环境"""
    
    client = mlflow.tracking.MlflowClient()
    
    # 获取最新生产版本
    try:
        latest_version = client.get_latest_versions(
            "LoadForecast_BestModel",
            stages=["Production"]
        )[0]
        
        print(f"当前生产版本: {latest_version.version}")
        
    except:
        # 迁移到生产
        client.transition_model_version_stage(
            name="LoadForecast_BestModel", 
            version=1,
            stage="Production"
        )
        print("模型已部署到生产环境")

if __name__ == "__main__":
    # 运行示例
    result = train_and_log_model()
    
    if result['metrics']['rmse'] < 10.0:  # 阈值判断
        register_model_version()
        deploy_model()
    
    print("MLflow集成演示完成")
EOF
    
    log_success "✅ 集成示例创建: $example_file"
}

# 创建环境配置
create_env_file() {
    log_info "创建环境配置文件..."
    
    env_file="/docker/mlflow/configs/mlflow.env"
    
    mkdir -p $(dirname "$env_file")
    
    cat > "$env_file" << EOF
# MLflow环境配置

# 基础配置
MLFLOW_TRACKING_URI=http://localhost:5000
MLFLOW_EXPERIMENT_NAME=smartgrid_load_forecasting
MLFLOW_DEFAULT_ARTIFACT_ROOT=file:///var/lib/mlflow/artifacts

# 日志级别
MLFLOW_LOG_LEVEL=INFO
MLFLOW_LOGGING_LEVEL=INFO

# 模型注册
MLFLOW_REGISTERED_MODEL_NAME=LoadForecastModel
MLFLOW_MODEL_STAGES=Staging,Production,Archived

# 自动日志
MLFLOW_DISABLE_AUTO_LOG=false
MLFLOW_AUTOLOG=true

# 缓存配置
MLFLOW_CACHE_DIR=/tmp/mlflow_cache
MLFLOW_CACHE_TIMEOUT=3600

# 并发设置
MLFLOW_MAX_CONCURRENT_THREADS=4
MLFLOW_TIMEOUT=60

# 安全配置
MLFLOW_SERVER_INSECURE=false
MLFLOW_ALLOW_UNAUTHENTICATED=false

# 缓存大小(MB)
MLFLOW_ARTIFACT_CACHE_SIZE=1024
EOF
    
    log_success "✅ 环境配置创建: $env_file"
}

# 生成部署报告
generate_deployment_report() {
    log_info "生成部署报告..."
    
    report_file="/docker/mlflow/deployment_report.md"
    
    backend_uri=$(build_backend_uri)
    
    cat > "$report_file" << EOF
# MLflow模型版本管理系统部署报告

## 📋 部署概览

- **部署时间**: $(date '+%Y-%m-%d %H:%M:%S')
- **MLflow版本**: ${MLFLOW_VERSION}
- **部署方式**: Docker容器
- **服务状态**: ✅ 运行正常

## 🔧 系统配置

### 服务配置
- **URL**: 