"""
智能电网负荷预测系统 - 系统状态与监控路由

端点:
  GET /api/system/status  - 系统状态监控
  GET /api/system/metrics - 系统监控指标查询
  GET /api/health         - 综合健康检查
  GET /api/health/liveness  - 存活检查
  GET /api/health/readiness - 就绪检查

从 app.py 中抽取。

作者: 毕业设计项目
"""

import time
import asyncio
import logging

from fastapi import APIRouter, HTTPException

from realtime_api.schemas import (
    SystemStatusResponse,
    SuccessResponse,
)
from realtime_api.crud import SystemMetricsCRUD
from realtime_api.health_check import get_health_check_service
from realtime_api.services.container import services, eastern_now

logger = logging.getLogger(__name__)

router = APIRouter(tags=["系统"])


# ============================================================================
# GET /api/system/status — 系统状态监控
# ============================================================================

@router.get(
    "/api/system/status",
    response_model=SystemStatusResponse,
    summary="系统状态监控",
    description="获取系统运行状态、模型信息和性能统计",
)
async def get_system_status():
    """系统状态监控"""
    stats = services.inference_service.get_performance_stats()

    # 内存和 CPU 使用
    try:
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        cpu_percent = process.cpu_percent(interval=0.1)
        sys_cpu_percent = psutil.cpu_percent(interval=0.1)
        sys_memory = psutil.virtual_memory()
        memory_percent = sys_memory.percent
        memory_used_gb = sys_memory.used / 1024 / 1024 / 1024
        memory_available_gb = sys_memory.available / 1024 / 1024 / 1024
        process_count = len(psutil.pids())
        disk_usage = psutil.disk_usage('/').percent
    except ImportError:
        memory_mb = None
        cpu_percent = None
        sys_cpu_percent = None
        memory_percent = None
        memory_used_gb = None
        memory_available_gb = None
        process_count = None
        disk_usage = None

    uptime = time.time() - services.start_time

    # 判断健康状态
    if stats['models_loaded'] == 4:
        health_status = "healthy"
    elif stats['models_loaded'] > 0:
        health_status = "degraded"
    else:
        health_status = "error"

    # 异步写入系统监控指标
    async def _persist_system_metrics():
        try:
            await SystemMetricsCRUD.insert_metrics(
                cpu_percent=sys_cpu_percent,
                cpu_count=process_count,
                memory_percent=memory_percent,
                memory_used_gb=round(memory_used_gb, 3) if memory_used_gb else None,
                memory_available_gb=round(memory_available_gb, 3) if memory_available_gb else None,
                gpu_available=False,
                gpu_memory_used_mb=None,
                gpu_memory_total_mb=None,
                gpu_utilization_percent=None,
                gpu_temperature_c=None,
                disk_usage_percent=disk_usage,
                process_count=process_count,
                active_connections=None,
            )
        except Exception as e:
            logger.warning(f"系统指标入库失败（非阻塞）: {e}")

    asyncio.create_task(_persist_system_metrics())

    return SystemStatusResponse(
        status=health_status,
        models_loaded=stats['models_loaded'],
        device=stats['device'],
        total_inferences=stats['total_inferences'],
        average_inference_time_ms=stats['average_time_ms'],
        ensemble_weights=stats['ensemble_weights'],
        uptime_seconds=round(uptime, 1),
        memory_usage_mb=round(memory_mb, 1) if memory_mb else None,
        timestamp=eastern_now().isoformat(),
    )


# ============================================================================
# GET /api/system/metrics — 系统监控指标查询
# ============================================================================

@router.get(
    "/api/system/metrics",
    response_model=SuccessResponse,
    summary="系统监控指标查询",
    description="获取系统性能监控指标（CPU、内存、GPU等）",
)
async def get_system_metrics(
    hours: int = 24,
    limit: int = 100,
):
    """系统监控指标查询API"""
    try:
        limit = max(1, min(limit, 1000))
        hours = max(1, min(hours, 168))  # 最多7天

        metrics = await SystemMetricsCRUD.get_metrics(hours=hours, limit=limit)

        logger.info(f"查询到 {len(metrics)} 条系统监控记录")

        return SuccessResponse(
            message=f"成功获取系统监控数据，共{len(metrics)}条记录",
            data=metrics
        )

    except Exception as e:
        logger.error(f"系统监控指标查询失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"查询系统监控数据失败: {str(e)}"
        )


# ============================================================================
# 健康检查端点
# ============================================================================

@router.get(
    "/api/health",
    summary="服务健康检查",
    description="检查所有核心组件的健康状态（数据库、Redis、模型服务、系统资源、GPU）",
)
async def health_check():
    """综合健康检查端点"""
    health_service = get_health_check_service()
    health_result = await health_service.comprehensive_health_check(
        inference_service=services.inference_service
    )
    return health_result


@router.get(
    "/api/health/liveness",
    summary="服务存活检查",
    description="简单的服务存活检查（用于Kubernetes liveness probe）",
)
async def liveness_check():
    """存活检查 - 最简单的服务可用性检查"""
    try:
        return {
            "status": "alive",
            "timestamp": eastern_now().isoformat(),
            "message": "Service is running"
        }
    except Exception as e:
        return {
            "status": "dead",
            "timestamp": eastern_now().isoformat(),
            "error": str(e)
        }


@router.get(
    "/api/health/readiness",
    summary="服务就绪检查",
    description="检查服务是否准备好接收流量（用于Kubernetes readiness probe）",
)
async def readiness_check():
    """就绪检查 - 检查服务是否能正常处理请求"""
    try:
        health_service = get_health_check_service()

        db_health = await health_service.check_database_health()
        model_health = health_service.check_model_service_health(services.inference_service)

        if db_health.status == "unhealthy" or model_health.status == "unhealthy":
            return {
                "status": "not_ready",
                "timestamp": eastern_now().isoformat(),
                "message": "Core services not ready",
                "db_status": db_health.status,
                "model_status": model_health.status
            }

        return {
            "status": "ready",
            "timestamp": eastern_now().isoformat(),
            "message": "All core services are ready",
            "db_status": db_health.status,
            "model_status": model_health.status
        }

    except Exception as e:
        return {
            "status": "not_ready",
            "timestamp": eastern_now().isoformat(),
            "error": str(e),
            "message": "Readiness check failed"
        }
