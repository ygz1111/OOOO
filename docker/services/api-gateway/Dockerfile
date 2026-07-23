# ============================================================================
# API Gateway - Dockerfile
# FastAPI 主服务，整合所有微服务
# ============================================================================

FROM registry.local:5000/grid-predict-base:latest AS runtime

WORKDIR /app

COPY realtime_api/ /app/realtime_api/
COPY outputs/ /app/outputs/
COPY processed/ /app/processed/
COPY docker/services/api-gateway/gateway_app.py /app/
COPY docker/services/api-gateway/entrypoint.sh /app/

RUN chmod +x /app/entrypoint.sh

HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/system/status || exit 1

ENV SERVICE_NAME=api-gateway

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "gateway_app.py"]
