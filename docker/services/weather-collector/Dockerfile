# ============================================================================
# 气象数据采集服务 - Dockerfile
# 定时从 Open-Meteo API 采集气象数据并写入 PostgreSQL
# ============================================================================

FROM registry.local:5000/grid-predict-base:latest AS runtime

# 安装 cron 用于定时调度
USER root
RUN apt-get update && apt-get install -y --no-install-recommends cron && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制应用代码
COPY realtime_api/ /app/realtime_api/
COPY docker/services/weather-collector/entrypoint.sh /app/entrypoint.sh
COPY docker/services/weather-collector/collector.py /app/collector.py

RUN chmod +x /app/entrypoint.sh

# 健康检查
HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:9090/health || exit 1

# 资源限制提示（实际限制由 docker-compose 设置）
ENV SERVICE_NAME=weather-collector
ENV LOG_LEVEL=INFO

EXPOSE 9090

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "collector.py"]
