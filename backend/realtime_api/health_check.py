#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能电网负荷预测系统 - 健康检查模块

提供全面的服务健康状态检查，包括数据库、缓存、模型服务等

作者: 毕业设计项目
"""

import asyncio
import time
import logging
import psutil
import torch
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

from realtime_api.database import db_manager
from realtime_api.config_manager import get_config
from realtime_api.prediction_service import ModelInferenceService


@dataclass
class ComponentHealth:
    """组件健康状态"""
    name: str
    status: str  # healthy, degraded, unhealthy
    message: str
    response_time_ms: Optional[float] = None
    last_check: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class HealthCheckService:
    """健康检查服务"""
    
    def __init__(self):
        self.config = get_config()
        self.logger = logging.getLogger(__name__)
        self.start_time = time.time()
        
    async def check_database_health(self) -> ComponentHealth:
        """检查数据库健康状态"""
        start_time = time.perf_counter()
        
        try:
            # 测试数据库连接
            health_result = await db_manager.health_check()
            response_time = (time.perf_counter() - start_time) * 1000
            
            if health_result.get('status') == 'healthy':
                return ComponentHealth(
                    name="database",
                    status="healthy",
                    message="数据库连接正常",
                    response_time_ms=round(response_time, 2),
                    last_check=datetime.now().isoformat(),
                    details=health_result
                )
            else:
                return ComponentHealth(
                    name="database",
                    status="unhealthy",
                    message=f"数据库连接异常: {health_result.get('error', '未知错误')}",
                    response_time_ms=round(response_time, 2),
                    last_check=datetime.now().isoformat(),
                    details=health_result
                )
                
        except Exception as e:
            response_time = (time.perf_counter() - start_time) * 1000
            return ComponentHealth(
                name="database",
                status="unhealthy",
                message=f"数据库检查失败: {str(e)}",
                response_time_ms=round(response_time, 2),
                last_check=datetime.now().isoformat(),
                details={'error': str(e)}
            )
    
    async def check_redis_health(self) -> ComponentHealth:
        """检查Redis健康状态"""
        start_time = time.perf_counter()
        
        try:
            import redis
            
            redis_config = self.config.get_cache_config()
            redis_client = redis.Redis(
                host=redis_config.get('host', 'localhost'),
                port=redis_config.get('port', 6379),
                db=redis_config.get('db', 0),
                socket_connect_timeout=2,
                socket_timeout=2
            )
            
            # 测试Redis连接
            ping_result = redis_client.ping()
            response_time = (time.perf_counter() - start_time) * 1000
            
            if ping_result:
                # 获取Redis信息
                info = redis_client.info()
                return ComponentHealth(
                    name="redis",
                    status="healthy",
                    message="Redis连接正常",
                    response_time_ms=round(response_time, 2),
                    last_check=datetime.now().isoformat(),
                    details={
                        'connected_clients': info.get('connected_clients', 0),
                        'used_memory_mb': round(info.get('used_memory', 0) / 1024 / 1024, 2),
                        'uptime_hours': round(info.get('uptime_in_seconds', 0) / 3600, 1)
                    }
                )
            else:
                return ComponentHealth(
                    name="redis",
                    status="unhealthy",
                    message="Redis ping失败",
                    response_time_ms=round(response_time, 2),
                    last_check=datetime.now().isoformat()
                )
                
        except Exception as e:
            response_time = (time.perf_counter() - start_time) * 1000
            return ComponentHealth(
                name="redis",
                status="unhealthy",
                message=f"Redis检查失败: {str(e)}",
                response_time_ms=round(response_time, 2),
                last_check=datetime.now().isoformat(),
                details={'error': str(e)}
            )
    
    def check_model_service_health(self, inference_service: Optional[ModelInferenceService]) -> ComponentHealth:
        """检查模型服务健康状态"""
        start_time = time.perf_counter()
        
        try:
            if not inference_service:
                return ComponentHealth(
                    name="model_service",
                    status="unhealthy",
                    message="模型服务未初始化",
                    last_check=datetime.now().isoformat()
                )
            
            if not inference_service.is_ready():
                return ComponentHealth(
                    name="model_service",
                    status="unhealthy",
                    message="模型服务未就绪",
                    last_check=datetime.now().isoformat()
                )
            
            # 获取模型信息
            model_info = inference_service.get_model_info()
            response_time = (time.perf_counter() - start_time) * 1000
            
            models_loaded = sum(1 for info in model_info.values() if info.get('loaded', False))
            total_models = len(model_info)
            
            if models_loaded == total_models:
                return ComponentHealth(
                    name="model_service",
                    status="healthy",
                    message=f"模型服务正常 ({models_loaded}/{total_models} 模型已加载)",
                    response_time_ms=round(response_time, 2),
                    last_check=datetime.now().isoformat(),
                    details={
                        'models_loaded': models_loaded,
                        'total_models': total_models,
                        'device': str(inference_service.device),
                        'model_details': model_info
                    }
                )
            else:
                return ComponentHealth(
                    name="model_service",
                    status="degraded",
                    message=f"模型服务降级 ({models_loaded}/{total_models} 模型已加载)",
                    response_time_ms=round(response_time, 2),
                    last_check=datetime.now().isoformat(),
                    details={
                        'models_loaded': models_loaded,
                        'total_models': total_models,
                        'model_details': model_info
                    }
                )
                
        except Exception as e:
            response_time = (time.perf_counter() - start_time) * 1000
            return ComponentHealth(
                name="model_service",
                status="unhealthy", 
                message=f"模型服务检查失败: {str(e)}",
                response_time_ms=round(response_time, 2),
                last_check=datetime.now().isoformat(),
                details={'error': str(e)}
            )
    
    def check_system_resources(self) -> ComponentHealth:
        """检查系统资源"""
        start_time = time.perf_counter()
        
        try:
            # 获取CPU使用率
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # 获取内存使用情况
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_used_gb = round(memory.used / (1024**3), 2)
            memory_total_gb = round(memory.total / (1024**3), 2)
            
            # 获取磁盘使用情况
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
            
            response_time = (time.perf_counter() - start_time) * 1000
            
            # 判断资源健康状态
            if cpu_percent > 90 or memory_percent > 90:
                status = "unhealthy"
                message = f"系统资源告警: CPU {cpu_percent}%, 内存 {memory_percent}%"
            elif cpu_percent > 70 or memory_percent > 80:
                status = "degraded"
                message = f"系统资源较高: CPU {cpu_percent}%, 内存 {memory_percent}%"
            else:
                status = "healthy"
                message = f"系统资源正常: CPU {cpu_percent}%, 内存 {memory_percent}%"
            
            return ComponentHealth(
                name="system_resources",
                status=status,
                message=message,
                response_time_ms=round(response_time, 2),
                last_check=datetime.now().isoformat(),
                details={
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory_percent,
                    'memory_used_gb': memory_used_gb,
                    'memory_total_gb': memory_total_gb,
                    'disk_percent': disk_percent,
                    'gpu_available': torch.cuda.is_available() if hasattr(torch, 'cuda') else False
                }
            )
            
        except Exception as e:
            response_time = (time.perf_counter() - start_time) * 1000
            return ComponentHealth(
                name="system_resources",
                status="unhealthy",
                message=f"系统资源检查失败: {str(e)}",
                response_time_ms=round(response_time, 2),
                last_check=datetime.now().isoformat(),
                details={'error': str(e)}
            )
    
    def check_gpu_health(self) -> ComponentHealth:
        """检查GPU健康状态"""
        start_time = time.perf_counter()
        
        try:
            if not hasattr(torch, 'cuda') or not torch.cuda.is_available():
                return ComponentHealth(
                    name="gpu",
                    status="degraded",
                    message="GPU不可用，使用CPU模式",
                    last_check=datetime.now().isoformat(),
                    details={'available': False, 'reason': 'cuda_not_available'}
                )
            
            # GPU可用，检查详细信息
            gpu_count = torch.cuda.device_count()
            if gpu_count == 0:
                return ComponentHealth(
                    name="gpu",
                    status="degraded", 
                    message="无可用GPU设备",
                    last_check=datetime.now().isoformat(),
                    details={'available': False, 'reason': 'no_gpu_devices'}
                )
            
            # 获取GPU信息
            gpu_info = []
            for i in range(gpu_count):
                props = torch.cuda.get_device_properties(i)
                gpu_info.append({
                    'device_id': i,
                    'name': props.name,
                    'total_memory_gb': round(props.total_memory / (1024**3), 2),
                    'compute_capability': f"{props.major}.{props.minor}"
                })
            
            response_time = (time.perf_counter() - start_time) * 1000
            
            return ComponentHealth(
                name="gpu",
                status="healthy",
                message=f"GPU正常 ({gpu_count} 个设备)",
                response_time_ms=round(response_time, 2),
                last_check=datetime.now().isoformat(),
                details={
                    'available': True,
                    'device_count': gpu_count,
                    'devices': gpu_info
                }
            )
            
        except Exception as e:
            response_time = (time.perf_counter() - start_time) * 1000
            return ComponentHealth(
                name="gpu",
                status="unhealthy",
                message=f"GPU检查失败: {str(e)}",
                response_time_ms=round(response_time, 2),
                last_check=datetime.now().isoformat(),
                details={'error': str(e)}
            )
    
    async def comprehensive_health_check(self, inference_service: Optional[ModelInferenceService] = None) -> Dict[str, Any]:
        """执行综合健康检查"""
        start_time = time.perf_counter()
        
        try:
            # 并行执行健康检查
            tasks = [
                self.check_database_health(),
                self.check_redis_health(),
                asyncio.to_thread(self.check_model_service_health, inference_service),
                asyncio.to_thread(self.check_system_resources),
                asyncio.to_thread(self.check_gpu_health)
            ]
            
            # 总超时 10s：任一组件检查卡住（如 Redis/GPU 环境缺失）也快速返回，
            # 避免 /api/health 长时间挂起（start.ps1 / Docker healthcheck 依赖它）
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=10.0
            )
            
            # 处理结果
            components = []
            overall_status = "healthy"
            
            for result in results:
                if isinstance(result, Exception):
                    # 处理异常情况
                    components.append(ComponentHealth(
                        name="unknown",
                        status="unhealthy",
                        message=f"检查异常: {str(result)}",
                        last_check=datetime.now().isoformat()
                    ))
                    overall_status = "unhealthy"
                else:
                    components.append(result)
                    
                    # 更新整体状态
                    if result.status == "unhealthy":
                        overall_status = "unhealthy"
                    elif result.status == "degraded" and overall_status != "unhealthy":
                        overall_status = "degraded"
            
            total_time = (time.perf_counter() - start_time) * 1000
            
            # 计算服务运行时间
            uptime = time.time() - self.start_time
            
            return {
                "status": overall_status,
                "timestamp": datetime.now().isoformat(),
                "response_time_ms": round(total_time, 2),
                "uptime_seconds": round(uptime, 1),
                "uptime_human": str(timedelta(seconds=int(uptime))),
                "service": self.config.get('system.name', 'Smart Grid Prediction System'),
                "version": self.config.get('system.version', '1.0.0'),
                "environment": self.config.get('system.environment', 'unknown'),
                "components": [asdict(comp) for comp in components]
            }
            
        except Exception as e:
            total_time = (time.perf_counter() - start_time) * 1000
            
            return {
                "status": "unhealthy",
                "timestamp": datetime.now().isoformat(),
                "response_time_ms": round(total_time, 2),
                "error": str(e),
                "message": "健康检查执行失败"
            }


# 全局健康检查服务实例
health_check_service = HealthCheckService()


def get_health_check_service() -> HealthCheckService:
    """获取健康检查服务实例"""
    return health_check_service