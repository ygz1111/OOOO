# ============================================================================
# 智能电网负荷预测系统 - API 服务镜像（单体架构）
# 当前 realtime_api.app:app（FastAPI 单体），替代旧的 gateway 微服务 Dockerfile
# ============================================================================
FROM python:3.11-slim

WORKDIR /app

# curl 用于 HEALTHCHECK
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用层缓存）
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 业务代码与数据
COPY backend/ /app/backend/
# 训练/推理数据（scaler、序列；模型权重由 compose volume 挂载）
COPY processed/ /app/processed/

ENV PYTHONPATH=/app/backend
WORKDIR /app/backend

EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "realtime_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
