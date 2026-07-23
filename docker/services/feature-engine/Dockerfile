# ============================================================================
# 特征工程服务 - Dockerfile
# ============================================================================

FROM registry.local:5000/grid-predict-base:latest AS runtime

WORKDIR /app

COPY realtime_api/ /app/realtime_api/
COPY processed/ /app/processed/
COPY docker/services/feature-engine/feature_server.py /app/
COPY docker/services/feature-engine/entrypoint.sh /app/

RUN chmod +x /app/entrypoint.sh

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8600/health || exit 1

ENV SERVICE_NAME=feature-engine

EXPOSE 8600

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "feature_server.py"]
