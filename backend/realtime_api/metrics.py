# -*- coding: utf-8 -*-
"""
Prometheus 指标接入（轻量实现，基于 prometheus_client）

不依赖 prometheus-fastapi-instrumentator（其内部使用已移除的 Starlette
on_startup 参数，与新版不兼容）。手写请求计数/延迟直方图中间件，
在 /metrics 端点以 Prometheus 文本格式暴露。

供 docker-compose 中的 Prometheus 抓取（docker/prometheus.yml 已配置
smartgrid-api:8000/metrics）。
"""
import time

from fastapi import Request
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

# 请求计数（按 方法+路由+状态码 分组）
REQUESTS = Counter(
    "http_requests_total",
    "HTTP 请求总数（按方法/路径/状态码）",
    ["method", "path", "status"],
)

# 请求延迟直方图（秒）
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP 请求处理时长（秒）",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# 进行中的请求数（Gauge 支持 inc/dec）
IN_PROGRESS = Gauge(
    "http_requests_inprogress",
    "当前正在处理的请求数",
    ["method", "path"],
)


async def metrics_endpoint() -> Response:
    """/metrics 端点：输出 Prometheus 文本格式指标"""
    return Response(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


async def metrics_middleware(request: Request, call_next):
    """采集请求指标（方法 + 模板化路径 + 状态码）"""
    path = request.scope.get("route")
    route_path = getattr(path, "path", None) or request.url.path
    method = request.method

    IN_PROGRESS.labels(method=method, path=route_path).inc()
    start = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        REQUEST_DURATION.labels(method=method, path=route_path).observe(
            time.perf_counter() - start
        )
        IN_PROGRESS.labels(method=method, path=route_path).dec()
    REQUESTS.labels(
        method=method, path=route_path, status=str(response.status_code)
    ).inc()
    return response
