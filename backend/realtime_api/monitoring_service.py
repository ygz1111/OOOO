#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能电网负荷预测系统 - 监控面板实时跟踪

功能:
  1. 系统性能监控 (CPU、内存、GPU)
  2. API性能指标收集
  3. 模型推理统计
  4. 实时日志跟踪
  5. 健康检查
  6. 性能预警

集成:
  - Prometheus指标收集
  - Grafana仪表板配置
  - 实时WebSocket推送
  - 自动化性能预警

作者: 毕业设计项目
"""

import os
import sys
import time
import json
import asyncio
import logging
import threading
import platform
from datetime import datetime, timedelta
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable

import psutil
import numpy as np

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# 预测准确性追踪类
# ============================================================================

class AccuracyTracker:
    """预测准确性追踪器"""
    
    def __init__(self, window_size: int = 1000):
        """
        初始化准确性追踪器
        
        Args:
            window_size: 滑动窗口大小，保留最近的预测记录数
        """
        self.window_size = window_size
        self.predictions = deque(maxlen=window_size)  # 预测值
        self.actuals = deque(maxlen=window_size)      # 实际值
        self.timestamps = deque(maxlen=window_size)   # 时间戳
        self.model_names = deque(maxlen=window_size)  # 模型名称
        
        logger.info(f"✅ 预测准确性追踪器初始化完成，窗口大小: {window_size}")
    
    def record(self, prediction: float, actual: float, 
               timestamp: Optional[str] = None, model_name: str = "ensemble"):
        """
        记录一次预测和实际值
        
        Args:
            prediction: 预测值
            actual: 实际值
            timestamp: 时间戳（可选）
            model_name: 模型名称
        """
        if timestamp is None:
            timestamp = datetime.now().isoformat()
            
        self.predictions.append(float(prediction))
        self.actuals.append(float(actual))
        self.timestamps.append(timestamp)
        self.model_names.append(model_name)
    
    def compute_mape(self) -> float:
        """计算MAPE（平均绝对百分比误差）"""
        if len(self.predictions) == 0:
            return 0.0
            
        predictions = np.array(self.predictions)
        actuals = np.array(self.actuals)
        
        # 避免除以零
        mask = np.abs(actuals) > 1e-6
        if not np.any(mask):
            return 0.0
            
        mape = np.mean(np.abs((actuals[mask] - predictions[mask]) / actuals[mask])) * 100
        return float(mape)
    
    def compute_rmse(self) -> float:
        """计算RMSE（均方根误差）"""
        if len(self.predictions) == 0:
            return 0.0
            
        predictions = np.array(self.predictions)
        actuals = np.array(self.actuals)
        
        rmse = np.sqrt(np.mean((actuals - predictions) ** 2))
        return float(rmse)
    
    def compute_mae(self) -> float:
        """计算MAE（平均绝对误差）"""
        if len(self.predictions) == 0:
            return 0.0
            
        predictions = np.array(self.predictions)
        actuals = np.array(self.actuals)
        
        mae = np.mean(np.abs(actuals - predictions))
        return float(mae)
    
    def compute_r2(self) -> float:
        """计算R²（决定系数）"""
        if len(self.predictions) < 2:
            return 0.0
            
        predictions = np.array(self.predictions)
        actuals = np.array(self.actuals)
        
        ss_res = np.sum((actuals - predictions) ** 2)
        ss_tot = np.sum((actuals - np.mean(actuals)) ** 2)
        
        if ss_tot == 0:
            return 1.0
            
        r2 = 1 - (ss_res / ss_tot)
        return float(r2)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取当前统计信息"""
        return {
            "count": len(self.predictions),
            "mape": self.compute_mape(),
            "rmse": self.compute_rmse(),
            "mae": self.compute_mae(),
            "r2": self.compute_r2(),
            "window_size": self.window_size
        }
    
    def get_recent_predictions(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近的预测记录"""
        result = []
        for i in range(min(limit, len(self.predictions))):
            idx = -(i + 1)  # 从后往前取
            result.append({
                "timestamp": self.timestamps[idx],
                "prediction": self.predictions[idx],
                "actual": self.actuals[idx],
                "model_name": self.model_names[idx],
                "error": self.actuals[idx] - self.predictions[idx]
            })
        return result


class ModelDriftDetector:
    """模型漂移检测器"""
    
    def __init__(self, reference_window: int = 1000, current_window: int = 100):
        """
        初始化漂移检测器
        
        Args:
            reference_window: 参考窗口大小
            current_window: 当前窗口大小
        """
        self.reference_predictions = deque(maxlen=reference_window)
        self.reference_actuals = deque(maxlen=reference_window)
        self.current_predictions = deque(maxlen=current_window)
        self.current_actuals = deque(maxlen=current_window)
        
        logger.info(f"✅ 模型漂移检测器初始化完成")
    
    def update_reference(self, predictions: List[float], actuals: List[float]):
        """更新参考数据"""
        self.reference_predictions.extend(predictions)
        self.reference_actuals.extend(actuals)
        
        logger.info(f"✅ 参考数据更新: {len(predictions)} 条记录")
    
    def update_current(self, predictions: List[float], actuals: List[float]):
        """更新当前数据"""
        self.current_predictions.extend(predictions)
        self.current_actuals.extend(actuals)
    
    def compute_psi(self, variable: str = "predictions") -> float:
        """
        计算PSI（Population Stability Index）
        
        Args:
            variable: 检测变量 ('predictions' 或 'actuals' 或 'errors')
        
        Returns:
            PSI值
        """
        if len(self.reference_predictions) < 50 or len(self.current_predictions) < 50:
            return 0.0
        
        # 获取数据
        if variable == "predictions":
            ref_data = np.array(self.reference_predictions)
            curr_data = np.array(self.current_predictions)
        elif variable == "actuals":
            ref_data = np.array(self.reference_actuals)
            curr_data = np.array(self.current_actuals)
        elif variable == "errors":
            ref_errors = np.array(self.reference_actuals) - np.array(self.reference_predictions)
            curr_errors = np.array(self.current_actuals) - np.array(self.current_predictions)
            ref_data = ref_errors
            curr_data = curr_errors
        else:
            return 0.0
        
        # 创建分箱
        all_data = np.concatenate([ref_data, curr_data])
        percentiles = np.percentile(all_data, [25, 50, 75])
        bins = np.concatenate([[np.min(all_data)], percentiles, [np.max(all_data)]])
        
        # 计算每个分箱的占比
        ref_hist, _ = np.histogram(ref_data, bins=bins)
        curr_hist, _ = np.histogram(curr_data, bins=bins)
        
        ref_prop = ref_hist / len(ref_data)
        curr_prop = curr_hist / len(curr_data)
        
        # 计算PSI
        psi = 0.0
        for i in range(len(ref_prop)):
            if ref_prop[i] > 0 and curr_prop[i] > 0:
                psi += (curr_prop[i] - ref_prop[i]) * np.log(curr_prop[i] / ref_prop[i])
        
        return float(psi)
    
    def detect_drift(self) -> Dict[str, Any]:
        """检测模型漂移"""
        psi_predictions = self.compute_psi("predictions")
        psi_actuals = self.compute_psi("actuals")
        psi_errors = self.compute_psi("errors")
        
        # 判断是否发生漂移
        drift_detected = (
            psi_predictions > 0.25 or 
            psi_actuals > 0.25 or 
            psi_errors > 0.25
        )
        
        return {
            "drift_detected": drift_detected,
            "psi_predictions": psi_predictions,
            "psi_actuals": psi_actuals,
            "psi_errors": psi_errors,
            "reference_size": len(self.reference_predictions),
            "current_size": len(self.current_predictions)
        }


class DataQualityMonitor:
    """数据质量监控器"""
    
    def __init__(self):
        self.quality_history = deque(maxlen=1000)
        logger.info("✅ 数据质量监控器初始化完成")
    
    def validate_weather_data(self, data: Dict[str, float]) -> Dict[str, Any]:
        """验证气象数据质量"""
        issues = []
        score = 1.0
        
        # 温度范围检查（新英格兰地区）
        temp = data.get('temperature_2m', 0)
        if not (-30 <= temp <= 45):
            issues.append(f"温度异常: {temp}°C")
            score -= 0.3
        
        # 露点检查
        dew_point = data.get('dew_point_2m', 0)
        if dew_point > temp:
            issues.append(f"露点({dew_point})高于气温({temp})")
            score -= 0.2
        
        # 湿度范围
        humidity = data.get('relative_humidity_2m', 0)
        if not (0 <= humidity <= 100):
            issues.append(f"湿度异常: {humidity}%")
            score -= 0.3
        
        # 云量范围
        cloud_cover = data.get('cloud_cover', 0)
        if not (0 <= cloud_cover <= 100):
            issues.append(f"云量异常: {cloud_cover}%")
            score -= 0.3
        
        # 辐射值检查
        radiation = data.get('shortwave_radiation', 0)
        if radiation < 0:
            issues.append(f"辐射值为负: {radiation}")
            score -= 0.3
        
        quality_result = {
            "is_valid": len(issues) == 0,
            "quality_score": max(0.0, score),
            "issues": issues,
            "timestamp": datetime.now().isoformat()
        }
        
        self.quality_history.append(quality_result)
        return quality_result
    
    def get_quality_stats(self) -> Dict[str, Any]:
        """获取质量统计信息"""
        if len(self.quality_history) == 0:
            return {"valid_rate": 0.0, "avg_score": 0.0, "total_checks": 0}
        
        valid_count = sum(1 for q in self.quality_history if q["is_valid"])
        avg_score = sum(q["quality_score"] for q in self.quality_history) / len(self.quality_history)
        
        return {
            "valid_rate": valid_count / len(self.quality_history),
            "avg_score": avg_score,
            "total_checks": len(self.quality_history)
        }


# ============================================================================
# 监控数据类
# ============================================================================

@dataclass
class SystemMetrics:
    """系统性能指标"""
    timestamp: str
    cpu_percent: float
    memory_percent: float
    memory_used_gb: float
    memory_available_gb: float
    disk_usage_percent: float
    network_io_bytes_sent: int
    network_io_bytes_recv: int
    process_count: int
    
    # GPU指标
    gpu_available: bool = False
    gpu_memory_used_mb: float = 0.0
    gpu_memory_total_mb: float = 0.0
    gpu_utilization_percent: float = 0.0
    gpu_temperature_c: float = 0.0


@dataclass
class APIMetrics:
    """API性能指标"""
    timestamp: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    average_response_time_ms: float
    p50_response_time_ms: float
    p95_response_time_ms: float
    p99_response_time_ms: float
    requests_per_second: float
    active_connections: int


@dataclass
class ModelMetrics:
    """模型推理指标"""
    timestamp: str
    total_inferences: int
    average_inference_time_ms: float
    successful_inferences: int
    failed_inferences: int
    cache_hits: int
    cache_misses: int
    cache_hit_ratio: float
    batch_inferences: int
    single_inferences: int
    gpu_inferences: int
    cpu_inferences: int


@dataclass
class PerformanceAlert:
    """性能预警"""
    timestamp: str
    alert_type: str  # 'critical', 'warning', 'info'
    metric_name: str
    current_value: float
    threshold: float
    message: str
    severity: int  # 1-5, 5最严重


# ============================================================================
# 监控服务类
# ============================================================================

class MonitoringService:
    """实时监控服务"""
    
    def __init__(self, history_size: int = 1000):
        self.history_size = history_size
        self.start_time = time.time()
        
        # 性能指标历史记录
        self.system_metrics_history = deque(maxlen=history_size)
        self.api_metrics_history = deque(maxlen=history_size)
        self.model_metrics_history = deque(maxlen=history_size)
        
        # 实时计数器
        self.api_requests = {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'response_times': deque(maxlen=1000),
            'requests_per_minute': defaultdict(int)
        }
        
        self.model_inferences = {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'inference_times': deque(maxlen=1000),
            'cache_hits': 0,
            'cache_misses': 0,
            'batch_count': 0,
            'single_count': 0,
            'gpu_count': 0,
            'cpu_count': 0
        }
        
        # 预警配置
        self.alert_thresholds = {
            'cpu_percent': {'warning': 80, 'critical': 95},
            'memory_percent': {'warning': 85, 'critical': 95},
            'response_time_ms': {'warning': 25000, 'critical': 35000},
            'error_rate': {'warning': 0.05, 'critical': 0.1},
            'cache_hit_ratio': {'warning': 0.4, 'critical': 0.2},
            'gpu_memory_percent': {'warning': 90, 'critical': 98}
        }
        
        # 预警历史
        self.alerts_history = deque(maxlen=100)
        
        # 预测准确性追踪
        self.accuracy_tracker = AccuracyTracker(window_size=1000)
        
        # 模型漂移检测
        self.drift_detector = ModelDriftDetector()
        
        # 数据质量监控
        self.data_quality_monitor = DataQualityMonitor()
        
        # 监控状态
        self.monitoring_active = False
        self.monitor_thread = None
        
        # WebSocket订阅者
        self.websocket_clients = []
        
        logger.info("✅ 监控服务初始化完成")
    
    def start_monitoring(self):
        """启动后台监控"""
        if self.monitoring_active:
            logger.warning("监控服务已在运行")
            return
        
        self.monitoring_active = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True
        )
        self.monitor_thread.start()
        
        logger.info("🚀 后台监控服务已启动")
    
    def stop_monitoring(self):
        """停止监控"""
        self.monitoring_active = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        logger.info("🛑 监控服务已停止")
    
    def _monitor_loop(self):
        """监控循环"""
        while self.monitoring_active:
            try:
                # 收集系统指标
                system_metrics = self._collect_system_metrics()
                self.system_metrics_history.append(system_metrics)
                
                # 收集API指标
                api_metrics = self._collect_api_metrics()
                self.api_metrics_history.append(api_metrics)
                
                # 收集模型指标
                model_metrics = self._collect_model_metrics()
                self.model_metrics_history.append(model_metrics)
                
                # 检查预警
                self._check_alerts(system_metrics, api_metrics, model_metrics)
                
                # 推送到WebSocket客户端
                if self.websocket_clients:
                    self._broadcast_metrics()
                
                # 每5秒收集一次
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"监控循环错误: {e}")
                time.sleep(10)  # 错误后等待更长时间
    
    def _collect_system_metrics(self) -> SystemMetrics:
        """收集系统性能指标"""
        try:
            # CPU和内存
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            
            # 磁盘使用
            disk = psutil.disk_usage('/')
            
            # 网络IO
            net_io = psutil.net_io_counters()
            
            # 进程数量
            process_count = len(psutil.pids())
            
            # GPU指标
            try:
                import tensorflow as tf
                gpu_available = bool(tf.config.list_physical_devices("GPU"))
            except Exception:
                gpu_available = False
            gpu_memory_used_mb = 0.0
            gpu_memory_total_mb = 0.0
            gpu_utilization_percent = 0.0
            gpu_temperature_c = 0.0
            
            if gpu_available:
                try:
                    # GPU 显存与利用率由 NVML 提供，模型框架统一为 TensorFlow。
                    try:
                        import pynvml
                        pynvml.nvmlInit()
                        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                        memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                        gpu_memory_used_mb = memory_info.used / 1024**2
                        gpu_memory_total_mb = memory_info.total / 1024**2
                        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                        gpu_utilization_percent = util.gpu
                        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                        gpu_temperature_c = temp
                        pynvml.nvmlShutdown()
                    except:
                        pass  # nvidia-ml-py库未安装
                        
                except Exception as e:
                    logger.warning(f"GPU指标获取失败: {e}")
            
            return SystemMetrics(
                timestamp=datetime.now().isoformat(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_used_gb=memory.used / 1024**3,
                memory_available_gb=memory.available / 1024**3,
                disk_usage_percent=disk.percent,
                network_io_bytes_sent=net_io.bytes_sent,
                network_io_bytes_recv=net_io.bytes_recv,
                process_count=process_count,
                gpu_available=gpu_available,
                gpu_memory_used_mb=gpu_memory_used_mb,
                gpu_memory_total_mb=gpu_memory_total_mb,
                gpu_utilization_percent=gpu_utilization_percent,
                gpu_temperature_c=gpu_temperature_c
            )
            
        except Exception as e:
            logger.error(f"系统指标收集失败: {e}")
            return self._get_empty_system_metrics()
    
    def _collect_api_metrics(self) -> APIMetrics:
        """收集API性能指标"""
        try:
            # 计算响应时间统计
            response_times = list(self.api_requests['response_times'])
            
            if response_times:
                avg_time = np.mean(response_times)
                p50_time = np.percentile(response_times, 50)
                p95_time = np.percentile(response_times, 95)
                p99_time = np.percentile(response_times, 99)
            else:
                avg_time = p50_time = p95_time = p99_time = 0.0
            
            # 计算请求速率
            total = self.api_requests['total']
            elapsed = time.time() - self.start_time
            rps = total / elapsed if elapsed > 0 else 0
            
            return APIMetrics(
                timestamp=datetime.now().isoformat(),
                total_requests=total,
                successful_requests=self.api_requests['successful'],
                failed_requests=self.api_requests['failed'],
                average_response_time_ms=avg_time,
                p50_response_time_ms=p50_time,
                p95_response_time_ms=p95_time,
                p99_response_time_ms=p99_time,
                requests_per_second=rps,
                active_connections=len(self.websocket_clients)
            )
            
        except Exception as e:
            logger.error(f"API指标收集失败: {e}")
            return self._get_empty_api_metrics()
    
    def _collect_model_metrics(self) -> ModelMetrics:
        """收集模型推理指标"""
        try:
            # 计算推理时间统计
            inference_times = list(self.model_inferences['inference_times'])
            avg_inference_time = np.mean(inference_times) if inference_times else 0.0
            
            # 缓存命中率
            total_cache = self.model_inferences['cache_hits'] + self.model_inferences['cache_misses']
            cache_hit_ratio = self.model_inferences['cache_hits'] / total_cache if total_cache > 0 else 0.0
            
            return ModelMetrics(
                timestamp=datetime.now().isoformat(),
                total_inferences=self.model_inferences['total'],
                average_inference_time_ms=avg_inference_time,
                successful_inferences=self.model_inferences['successful'],
                failed_inferences=self.model_inferences['failed'],
                cache_hits=self.model_inferences['cache_hits'],
                cache_misses=self.model_inferences['cache_misses'],
                cache_hit_ratio=cache_hit_ratio,
                batch_inferences=self.model_inferences['batch_count'],
                single_inferences=self.model_inferences['single_count'],
                gpu_inferences=self.model_inferences['gpu_count'],
                cpu_inferences=self.model_inferences['cpu_count']
            )
            
        except Exception as e:
            logger.error(f"模型指标收集失败: {e}")
            return self._get_empty_model_metrics()
    
    def _check_alerts(self, system: SystemMetrics, api: APIMetrics, model: ModelMetrics):
        """检查性能预警"""
        alerts = []
        
        # 检查CPU
        if system.cpu_percent >= self.alert_thresholds['cpu_percent']['critical']:
            alerts.append(self._create_alert(
                'critical', 'cpu_percent', 
                system.cpu_percent, 
                self.alert_thresholds['cpu_percent']['critical'],
                f"CPU使用率过高: {system.cpu_percent:.1f}%"
            ))
        elif system.cpu_percent >= self.alert_thresholds['cpu_percent']['warning']:
            alerts.append(self._create_alert(
                'warning', 'cpu_percent',
                system.cpu_percent,
                self.alert_thresholds['cpu_percent']['warning'],
                f"CPU使用率警告: {system.cpu_percent:.1f}%"
            ))
        
        # 检查内存
        if system.memory_percent >= self.alert_thresholds['memory_percent']['critical']:
            alerts.append(self._create_alert(
                'critical', 'memory_percent',
                system.memory_percent,
                self.alert_thresholds['memory_percent']['critical'],
                f"内存使用率过高: {system.memory_percent:.1f}%"
            ))
        
        # 检查响应时间
        if api.p95_response_time_ms >= self.alert_thresholds['response_time_ms']['critical']:
            alerts.append(self._create_alert(
                'critical', 'response_time_ms',
                api.p95_response_time_ms,
                self.alert_thresholds['response_time_ms']['critical'],
                f"响应时间过长: {api.p95_response_time_ms:.1f}ms"
            ))
        
        # 检查错误率
        error_rate = api.failed_requests / api.total_requests if api.total_requests > 0 else 0
        if error_rate >= self.alert_thresholds['error_rate']['critical']:
            alerts.append(self._create_alert(
                'critical', 'error_rate',
                error_rate * 100,
                self.alert_thresholds['error_rate']['critical'] * 100,
                f"错误率过高: {error_rate:.2%}"
            ))
        
        # 检查缓存命中率
        if model.cache_hit_ratio < self.alert_thresholds['cache_hit_ratio']['critical']:
            alerts.append(self._create_alert(
                'critical', 'cache_hit_ratio',
                model.cache_hit_ratio * 100,
                self.alert_thresholds['cache_hit_ratio']['critical'] * 100,
                f"缓存命中率过低: {model.cache_hit_ratio:.2%}"
            ))
        
        # 保存预警
        for alert in alerts:
            self.alerts_history.append(alert)
            logger.warning(f"⚠️ 性能预警: {alert.message}")
    
    def _create_alert(self, alert_type: str, metric_name: str, 
                     current_value: float, threshold: float, message: str) -> PerformanceAlert:
        """创建预警对象"""
        severity = 5 if alert_type == 'critical' else 3 if alert_type == 'warning' else 1
        
        return PerformanceAlert(
            timestamp=datetime.now().isoformat(),
            alert_type=alert_type,
            metric_name=metric_name,
            current_value=current_value,
            threshold=threshold,
            message=message,
            severity=severity
        )
    
    def _broadcast_metrics(self):
        """广播指标到WebSocket客户端"""
        if not self.websocket_clients:
            return
        
        try:
            # 准备广播数据
            broadcast_data = {
                'type': 'metrics_update',
                'timestamp': datetime.now().isoformat(),
                'system': self._metrics_to_dict(self.system_metrics_history[-1]) if self.system_metrics_history else None,
                'api': self._metrics_to_dict(self.api_metrics_history[-1]) if self.api_metrics_history else None,
                'model': self._metrics_to_dict(self.model_metrics_history[-1]) if self.model_metrics_history else None,
                'alerts': [self._metrics_to_dict(a) for a in list(self.alerts_history)[-5:]]
            }
            
            # 广播 (这里需要实际的WebSocket实现)
            # 在实际应用中，这里会调用WebSocket的broadcast方法
            
        except Exception as e:
            logger.error(f"WebSocket广播失败: {e}")
    
    def record_api_request(self, response_time_ms: float, success: bool):
        """记录API请求"""
        self.api_requests['total'] += 1
        
        if success:
            self.api_requests['successful'] += 1
        else:
            self.api_requests['failed'] += 1
        
        self.api_requests['response_times'].append(response_time_ms)
        
        # 记录每分钟请求数
        current_minute = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.api_requests['requests_per_minute'][current_minute] += 1
    
    def record_model_inference(self, inference_time_ms: float, success: bool, 
                               cache_hit: bool = False, is_batch: bool = False,
                               device: str = "cpu"):
        """记录模型推理"""
        self.model_inferences['total'] += 1
        
        if success:
            self.model_inferences['successful'] += 1
        else:
            self.model_inferences['failed'] += 1
        
        self.model_inferences['inference_times'].append(inference_time_ms)
        
        if cache_hit:
            self.model_inferences['cache_hits'] += 1
        else:
            self.model_inferences['cache_misses'] += 1
        
        if is_batch:
            self.model_inferences['batch_count'] += 1
        else:
            self.model_inferences['single_count'] += 1
        
        if device == "cuda":
            self.model_inferences['gpu_count'] += 1
        else:
            self.model_inferences['cpu_count'] += 1
    
    def record_prediction_accuracy(self, prediction: float, actual: float, 
                                  model_name: str = "ensemble", timestamp: str = None):
        """记录预测准确性"""
        self.accuracy_tracker.record(prediction, actual, timestamp, model_name)
    
    def get_prediction_accuracy_stats(self) -> Dict[str, Any]:
        """获取预测准确性统计"""
        return self.accuracy_tracker.get_stats()
    
    def check_model_drift(self) -> Dict[str, Any]:
        """检查模型漂移"""
        return self.drift_detector.detect_drift()
    
    def validate_data_quality(self, weather_data: Dict[str, float]) -> Dict[str, Any]:
        """验证数据质量"""
        return self.data_quality_monitor.validate_weather_data(weather_data)
    
    def get_current_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            'timestamp': datetime.now().isoformat(),
            'uptime_seconds': time.time() - self.start_time,
            'monitoring_active': self.monitoring_active,
            'system': self._metrics_to_dict(self.system_metrics_history[-1]) if self.system_metrics_history else None,
            'api': self._metrics_to_dict(self.api_metrics_history[-1]) if self.api_metrics_history else None,
            'model': self._metrics_to_dict(self.model_metrics_history[-1]) if self.model_metrics_history else None,
            'recent_alerts': [self._metrics_to_dict(a) for a in list(self.alerts_history)[-10:]],
            'websocket_clients': len(self.websocket_clients)
        }
    
    def get_metrics_history(self, metric_type: str = 'all', 
                           duration_minutes: int = 60) -> Dict[str, List[Dict]]:
        """获取历史指标数据"""
        cutoff_time = datetime.now() - timedelta(minutes=duration_minutes)
        
        result = {}
        
        if metric_type in ['all', 'system']:
            result['system'] = [
                self._metrics_to_dict(m) 
                for m in self.system_metrics_history 
                if datetime.fromisoformat(m.timestamp) >= cutoff_time
            ]
        
        if metric_type in ['all', 'api']:
            result['api'] = [
                self._metrics_to_dict(m) 
                for m in self.api_metrics_history 
                if datetime.fromisoformat(m.timestamp) >= cutoff_time
            ]
        
        if metric_type in ['all', 'model']:
            result['model'] = [
                self._metrics_to_dict(m) 
                for m in self.model_metrics_history 
                if datetime.fromisoformat(m.timestamp) >= cutoff_time
            ]
        
        return result
    
    def _metrics_to_dict(self, metrics_obj) -> Dict[str, Any]:
        """转换指标对象为字典"""
        if metrics_obj is None:
            return {}
        
        if hasattr(metrics_obj, '__dataclass_fields__'):
            return {k: getattr(metrics_obj, k) for k in metrics_obj.__dataclass_fields__}
        else:
            return dict(metrics_obj)
    
    def _get_empty_system_metrics(self) -> SystemMetrics:
        """返回空的系统指标"""
        return SystemMetrics(
            timestamp=datetime.now().isoformat(),
            cpu_percent=0.0,
            memory_percent=0.0,
            memory_used_gb=0.0,
            memory_available_gb=0.0,
            disk_usage_percent=0.0,
            network_io_bytes_sent=0,
            network_io_bytes_recv=0,
            process_count=0,
            gpu_available=False
        )
    
    def _get_empty_api_metrics(self) -> APIMetrics:
        """返回空的API指标"""
        return APIMetrics(
            timestamp=datetime.now().isoformat(),
            total_requests=0,
            successful_requests=0,
            failed_requests=0,
            average_response_time_ms=0.0,
            p50_response_time_ms=0.0,
            p95_response_time_ms=0.0,
            p99_response_time_ms=0.0,
            requests_per_second=0.0,
            active_connections=0
        )
    
    def _get_empty_model_metrics(self) -> ModelMetrics:
        """返回空的模型指标"""
        return ModelMetrics(
            timestamp=datetime.now().isoformat(),
            total_inferences=0,
            average_inference_time_ms=0.0,
            successful_inferences=0,
            failed_inferences=0,
            cache_hits=0,
            cache_misses=0,
            cache_hit_ratio=0.0,
            batch_inferences=0,
            single_inferences=0,
            gpu_inferences=0,
            cpu_inferences=0
        )


# ============================================================================
# Prometheus格式导出
# ============================================================================

class PrometheusMetricsExporter:
    """Prometheus指标格式导出器"""
    
    @staticmethod
    def export_metrics(monitoring_service: MonitoringService) -> str:
        """导出Prometheus格式的指标"""
        metrics_lines = []
        
        # 获取当前指标
        current_status = monitoring_service.get_current_status()
        
        # 系统指标
        system = current_status.get('system', {})
        if system:
            metrics_lines.extend([
                f"# HELP system_cpu_percent System CPU usage percentage",
                f"# TYPE system_cpu_percent gauge",
                f"system_cpu_percent {system.get('cpu_percent', 0)}",
                "",
                f"# HELP system_memory_percent System memory usage percentage",
                f"# TYPE system_memory_percent gauge",
                f"system_memory_percent {system.get('memory_percent', 0)}",
                "",
                f"# HELP system_memory_used_gb System memory used in GB",
                f"# TYPE system_memory_used_gb gauge",
                f"system_memory_used_gb {system.get('memory_used_gb', 0):.2f}",
                "",
                f"# HELP system_gpu_memory_mb GPU memory used in MB",
                f"# TYPE system_gpu_memory_mb gauge",
                f"system_gpu_memory_mb {system.get('gpu_memory_used_mb', 0):.2f}",
                "",
            ])
        
        # API指标
        api = current_status.get('api', {})
        if api:
            metrics_lines.extend([
                f"# HELP api_total_requests_total Total API requests",
                f"# TYPE api_total_requests_total counter",
                f"api_total_requests_total {api.get('total_requests', 0)}",
                "",
                f"# HELP api_successful_requests_total Successful API requests",
                f"# TYPE api_successful_requests_total counter",
                f"api_successful_requests_total {api.get('successful_requests', 0)}",
                "",
                f"# HELP api_failed_requests_total Failed API requests",
                f"# TYPE api_failed_requests_total counter",
                f"api_failed_requests_total {api.get('failed_requests', 0)}",
                "",
                f"# HELP api_response_time_ms API response time in milliseconds",
                f"# TYPE api_response_time_ms gauge",
                f"api_response_time_ms{{percentile=\"p50\"}} {api.get('p50_response_time_ms', 0):.2f}",
                f"api_response_time_ms{{percentile=\"p95\"}} {api.get('p95_response_time_ms', 0):.2f}",
                f"api_response_time_ms{{percentile=\"p99\"}} {api.get('p99_response_time_ms', 0):.2f}",
                "",
                f"# HELP api_requests_per_second API requests per second",
                f"# TYPE api_requests_per_second gauge",
                f"api_requests_per_second {api.get('requests_per_second', 0):.2f}",
                "",
            ])
        
        # 模型指标
        model = current_status.get('model', {})
        if model:
            metrics_lines.extend([
                f"# HELP model_total_inferences_total Total model inferences",
                f"# TYPE model_total_inferences_total counter",
                f"model_total_inferences_total {model.get('total_inferences', 0)}",
                "",
                f"# HELP model_inference_time_ms Model inference time in milliseconds",
                f"# TYPE model_inference_time_ms gauge",
                f"model_inference_time_ms {model.get('average_inference_time_ms', 0):.2f}",
                "",
                f"# HELP model_cache_hit_ratio Cache hit ratio",
                f"# TYPE model_cache_hit_ratio gauge",
                f"model_cache_hit_ratio {model.get('cache_hit_ratio', 0):.4f}",
                "",
            ])
        
        return "\n".join(metrics_lines)


# ============================================================================
# 单例监控实例
# ============================================================================

# 全局监控服务实例
monitoring_service = MonitoringService()

def get_monitoring_service() -> MonitoringService:
    """获取监控服务单例"""
    return monitoring_service
