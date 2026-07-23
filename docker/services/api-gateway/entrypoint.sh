#!/bin/bash
set -e

echo "================================================"
echo "  API Gateway Service"
echo "================================================"
echo "  Weather: ${WEATHER_SERVICE_URL:-http://weather-collector:9090}"
echo "  Feature: ${FEATURE_SERVICE_URL:-http://feature-engine:8600}"
echo "  Inference: ${INFERENCE_SERVICE_URL:-http://model-inference:8500}"
echo "================================================"

# 等待下游服务就绪
for svc in weather-collector:9090 feature-engine:8600 model-inference:8500; do
    host=$(echo $svc | cut -d: -f1)
    port=$(echo $svc | cut -d: -f2)
    echo "等待 $host:$port..."
    until curl -sf http://$svc/health > /dev/null 2>&1; do
        sleep 2
    done
    echo "✅ $host 就绪"
done

echo "启动 API Gateway..."
exec "$@"
