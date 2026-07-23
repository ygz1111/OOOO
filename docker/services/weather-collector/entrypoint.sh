#!/bin/bash
# 气象采集服务入口脚本
set -e

echo "================================================"
echo "  Weather Collector Service"
echo "================================================"
echo "  COLLECT_INTERVAL: ${COLLECT_INTERVAL:-300}s"
echo "  PAST_DAYS: ${PAST_DAYS:-7}"
echo "  FORECAST_DAYS: ${FORECAST_DAYS:-2}"
echo "================================================"

# 等待 PostgreSQL 就绪
if [ -n "$POSTGRES_HOST" ]; then
    echo "等待 PostgreSQL ${POSTGRES_HOST}:${POSTGRES_PORT:-5432}..."
    until python -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.connect(('${POSTGRES_HOST}', ${POSTGRES_PORT:-5432}))
    s.close()
    exit(0)
except:
    exit(1)
" ; do
        sleep 2
    done
    echo "✅ PostgreSQL 已就绪"
fi

# 等待 Redis 就绪
if [ -n "$REDIS_HOST" ]; then
    echo "等待 Redis ${REDIS_HOST}:${REDIS_PORT:-6379}..."
    until python -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.connect(('${REDIS_HOST}', ${REDIS_PORT:-6379}))
    s.close()
    exit(0)
except:
    exit(1)
" ; do
        sleep 2
    done
    echo "✅ Redis 已就绪"
fi

echo "启动采集服务..."
exec "$@"
