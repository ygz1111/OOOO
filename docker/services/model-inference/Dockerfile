# ============================================================================
# 模型推理服务 - Dockerfile (多阶段，含 PyTorch)
# ============================================================================

# ---- 阶段1: Builder ----
FROM python:3.11-slim AS builder

WORKDIR /build

# 安装编译依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev && rm -rf /var/lib/apt/lists/*

# 安装基础依赖
COPY docker/requirements-base.txt /build/
RUN pip install --no-cache-dir --user -r /build/requirements-base.txt

# 安装 ML 依赖 (PyTorch CPU)
COPY docker/requirements-ml.txt /build/
RUN pip install --no-cache-dir --user -r /build/requirements-ml.txt

# ---- 阶段2: Runtime ----
FROM python:3.11-slim AS runtime

# 运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libgomp1 curl && rm -rf /var/lib/apt/lists/*

# 复制 Python 包
COPY --from=builder /root/.local /root/.local

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 复制应用代码和模型
COPY realtime_api/ /app/realtime_api/
COPY models/ /app/models/
COPY outputs/ /app/outputs/
COPY processed/ /app/processed/
COPY docker/services/model-inference/inference_server.py /app/
COPY docker/services/model-inference/entrypoint.sh /app/

RUN chmod +x /app/entrypoint.sh

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8500/health || exit 1

ENV SERVICE_NAME=model-inference
ENV MODEL_DIR=/app/outputs
ENV DEVICE=cpu

EXPOSE 8500

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "inference_server.py"]
