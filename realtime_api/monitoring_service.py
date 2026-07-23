"""
智能电网负荷预测系统 - 系统监控模块

功能:
  1. 预测准确率监控 (MAPE, RMSE)
  2. 系统响应时间监控
  3. API调用频率统计
  4. 数据质量监控
  5. 模型漂移检测
  6. 告警机制 (多级别、多渠道)
  7. Prometheus 指标导出
  8. 结构化日志管理

架构:
  ┌─────────────────────────────────────────────────────┐
  │              MonitoringService                       │
  │  ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
  │  │ Metrics  │ │ Alerts   │ │ Drift Detector   │   │
  │  │ Collector│ │ Engine   │ │ (KS Test / PSI)  │   │
  │  └──────────┘ └──────────┘ └──────────────────┘   │
  │  ┌──────────────────────────────────────────────┐  │
  │  │         Prometheus Exporter (:9095)          │  │
  │  └──────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────┘

依赖: prometheus-client, numpy, pandas, scipy

作者: 毕业设计项目
"""

import os
import time
import json
import logging
import threading
from collections import deque, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable

import numpy as np

try:
    from prometheus_client import (
        CollectorRegistry, Counter, Gauge, Histogram, Summary,
        generate_latest, CONTENT_TYPE_LATEST, start_http_server,
    )
    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False

try:
    from scipy import stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


# ============================================================================
# 结构化日志
# ============================================================================

class StructuredFormatter(logging.Formatter):
    """JSON 格式结构化日志"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 异常信息
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # 额外字段
        if hasattr(record, "extra_fields"):
            log_entry["extra"] = record.extra_fields

        return json.dumps(log_entry, ensure_ascii=False, default=str)


def setup_structured_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
):
    """
    配置结构化日志

    Args:
        level: 日志级别
        log_file: 日志文件路径 (None=仅控制台)
        max_bytes: 单文件最大字节数 (日志轮转)
        backup_count: 保留备份数
    """
    from logging.handlers import RotatingFileHandler

    formatter = StructuredFormatter()

    # 控制台 handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))

    handlers = [console]

    # 文件 handler (轮转)
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        handlers.append(file_handler)

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=handlers,
        force=True,
    )


# ============================================================================
# 告警数据类
# ============================================================================

@dataclass
class Alert:
    """告警对象"""
    name: str
    severity: str          # info / warning / error / critical
    message: str
    value: float
    threshold: float
    timestamp: str = ""
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "severity": self.severity,
            "message": self.message,
            "value": round(self.value, 4),
            "threshold": round(self.threshold, 4),
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class AlertRule:
    """告警规则"""
    name: str
    description: str
    metric_name: str
    condition: str         # gt / lt / gte / lte / eq
    threshold: float
    severity: str = "warning"
    cooldown_seconds: int = 300  # 冷却时间，避免告警风暴
    last_fired: float = 0.0


# ============================================================================
# 预测准确率跟踪器
# ============================================================================

class AccuracyTracker:
    """
    预测准确率实时跟踪器

    维护滑动窗口内的预测值和实际值，
    计算 MAPE、RMSE、MAE 等指标。
    """

    def __init__(self, window_size: int = 168):
        """
        Args:
            window_size: 滑动窗口大小 (默认168=一周小时数)
        """
        self.window_size = window_size
        self.predictions = deque(maxlen=window_size)
        self.actuals = deque(maxlen=window_size)
        self.timestamps = deque(maxlen=window_size)

        # 累计统计
        self._total_predictions = 0
        self._sum_mape = 0.0
        self._sum_rmse_sq = 0.0

    def record(self, prediction: float, actual: float, timestamp: Optional[str] = None):
        """记录一次预测-实际对"""
        self.predictions.append(prediction)
        self.actuals.append(actual)
        self.timestamps.append(timestamp or datetime.now().isoformat())
        self._total_predictions += 1

    def compute_mape(self) -> float:
        """计算平均绝对百分比误差 (MAPE)"""
        if not self.actuals:
            return 0.0

        errors = []
        for pred, act in zip(self.predictions, self.actuals):
            if abs(act) > 0.01:  # 避免除零
                errors.append(abs((act - pred) / act) * 100)

        return float(np.mean(errors)) if errors else 0.0

    def compute_rmse(self) -> float:
        """计算均方根误差 (RMSE)"""
        if not self.actuals:
            return 0.0
        return float(np.sqrt(np.mean(
            [(p - a) ** 2 for p, a in zip(self.predictions, self.actuals)]
        )))

    def compute_mae(self) -> float:
        """计算平均绝对误差 (MAE)"""
        if not self.actuals:
            return 0.0
        return float(np.mean(
            [abs(p - a) for p, a in zip(self.predictions, self.actuals)]
        ))

    def compute_r2(self) -> float:
        """计算决定系数 R²"""
        if len(self.actuals) < 2:
            return 0.0

        preds = np.array(self.predictions)
        acts = np.array(self.actuals)

        ss_res = np.sum((acts - preds) ** 2)
        ss_tot = np.sum((acts - np.mean(acts)) ** 2)

        if ss_tot == 0:
            return 0.0

        return float(1 - ss_res / ss_tot)

    def get_stats(self) -> Dict[str, float]:
        """获取所有统计指标"""
        return {
            "mape": self.compute_mape(),
            "rmse": self.compute_rmse(),
            "mae": self.compute_mae(),
            "r2": self.compute_r2(),
            "count": len(self.predictions),
            "total": self._total_predictions,
        }


# ============================================================================
# 模型漂移检测器
# ============================================================================

class ModelDriftDetector:
    """
    模型漂移检测器

    使用以下方法检测分布漂移:
      1. Kolmogorov-Smirnov 检验 (特征分布)
      2. Population Stability Index (PSI)
      3. 预测误差趋势分析

    漂移判断:
      PSI < 0.1  → 无漂移
      PSI 0.1-0.25 → 轻微漂移
      PSI > 0.25  → 显著漂移
    """

    def __init__(self, reference_size: int = 500):
        """
        Args:
            reference_size: 参考分布样本数
        """
        self.reference_size = reference_size
        self.reference_predictions: Optional[np.ndarray] = None
        self.reference_errors: Optional[np.ndarray] = None
        self._reference_set = False

    def set_reference(self, predictions: np.ndarray, errors: np.ndarray):
        """设置参考分布 (训练时的预测和误差)"""
        self.reference_predictions = np.array(predictions)
        self.reference_errors = np.array(errors)
        self._reference_set = True

    def compute_psi(self, reference: np.ndarray, current: np.ndarray, n_bins: int = 10) -> float:
        """
        计算Population Stability Index (PSI)

        PSI = Σ (p_current - p_reference) × ln(p_current / p_reference)

        Args:
            reference: 参考分布
            current: 当前分布
            n_bins: 分箱数

        Returns:
            PSI值
        """
        if len(reference) == 0 or len(current) == 0:
            return 0.0

        # 合并范围
        edges = np.linspace(
            min(reference.min(), current.min()),
            max(reference.max(), current.max()),
            n_bins + 1
        )

        # 计算分布
        ref_hist, _ = np.histogram(reference, bins=edges)
        cur_hist, _ = np.histogram(current, bins=edges)

        # 转为比例 (避免除零)
        ref_pct = ref_hist / max(len(reference), 1) + 1e-6
        cur_pct = cur_hist / max(len(current), 1) + 1e-6

        # PSI
        psi = np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct))

        return float(psi)

    def ks_test(self, reference: np.ndarray, current: np.ndarray) -> Dict:
        """Kolmogorov-Smirnov 检验"""
        if not HAS_SCIPY or len(reference) == 0 or len(current) == 0:
            return {"statistic": 0.0, "pvalue": 1.0}

        try:
            result = stats.ks_2samp(reference, current)
            return {
                "statistic": float(result.statistic),
                "pvalue": float(result.pvalue),
            }
        except Exception:
            return {"statistic": 0.0, "pvalue": 1.0}

    def detect_drift(
        self,
        current_predictions: np.ndarray,
        current_errors: np.ndarray,
    ) -> Dict[str, Any]:
        """
        检测模型漂移

        Args:
            current_predictions: 当前预测值
            current_errors: 当前预测误差

        Returns:
            漂移检测结果
        """
        if not self._reference_set:
            return {
                "status": "no_reference",
                "message": "未设置参考分布",
                "psi_predictions": 0.0,
                "psi_errors": 0.0,
                "drift_detected": False,
            }

        # PSI
        psi_pred = self.compute_psi(self.reference_predictions, current_predictions)
        psi_err = self.compute_psi(self.reference_errors, current_errors)

        # KS检验
        ks_pred = self.ks_test(self.reference_predictions, current_predictions)
        ks_err = self.ks_test(self.reference_errors, current_errors)

        # 判断
        drift_pred = psi_pred > 0.25
        drift_err = psi_err > 0.25
        drift_detected = drift_pred or drift_err

        # 级别
        if psi_pred > 0.25 or psi_err > 0.25:
            level = "significant"
        elif psi_pred > 0.1 or psi_err > 0.1:
            level = "minor"
        else:
            level = "none"

        return {
            "status": level,
            "psi_predictions": round(psi_pred, 4),
            "psi_errors": round(psi_err, 4),
            "ks_predictions": ks_pred,
            "ks_errors": ks_err,
            "drift_detected": drift_detected,
            "drift_level": level,
            "message": f"漂移级别: {level}" + (
                " - 建议重新训练模型" if level == "significant" else ""
            ),
        }


# ============================================================================
# API 调用统计
# ============================================================================

class APICallTracker:
    """API 调用频率和错误率统计"""

    def __init__(self, window_seconds: int = 3600):
        """
        Args:
            window_seconds: 统计窗口 (秒)
        """
        self.window_seconds = window_seconds
        self._calls = deque()  # (timestamp, endpoint, status_code, duration_ms)
        self._endpoint_stats = defaultdict(lambda: {"count": 0, "errors": 0, "total_time": 0.0})

    def record(
        self,
        endpoint: str,
        status_code: int,
        duration_ms: float,
        timestamp: Optional[float] = None,
    ):
        """记录一次API调用"""
        ts = timestamp or time.time()
        self._calls.append((ts, endpoint, status_code, duration_ms))

        # 端点统计
        self._endpoint_stats[endpoint]["count"] += 1
        self._endpoint_stats[endpoint]["total_time"] += duration_ms
        if status_code >= 400:
            self._endpoint_stats[endpoint]["errors"] += 1

        # 清理过期记录
        cutoff = ts - self.window_seconds
        while self._calls and self._calls[0][0] < cutoff:
            self._calls.popleft()

    def get_call_rate(self) -> float:
        """获取每秒调用次数"""
        now = time.time()
        cutoff = now - self.window_seconds
        recent = [c for c in self._calls if c[0] >= cutoff]
        return len(recent) / self.window_seconds if recent else 0.0

    def get_error_rate(self) -> float:
        """获取错误率"""
        if not self._calls:
            return 0.0
        errors = sum(1 for c in self._calls if c[2] >= 400)
        return errors / len(self._calls)

    def get_avg_response_time(self) -> float:
        """获取平均响应时间"""
        if not self._calls:
            return 0.0
        return float(np.mean([c[3] for c in self._calls]))

    def get_endpoint_stats(self) -> Dict:
        """获取各端点统计"""
        result = {}
        for endpoint, stats in self._endpoint_stats.items():
            avg_time = stats["total_time"] / max(stats["count"], 1)
            error_rate = stats["errors"] / max(stats["count"], 1)
            result[endpoint] = {
                "count": stats["count"],
                "errors": stats["errors"],
                "error_rate": round(error_rate, 4),
                "avg_response_ms": round(avg_time, 1),
            }
        return result

    def get_stats(self) -> Dict[str, Any]:
        """获取完整统计"""
        return {
            "call_rate_per_sec": round(self.get_call_rate(), 2),
            "error_rate": round(self.get_error_rate(), 4),
            "avg_response_ms": round(self.get_avg_response_time(), 1),
            "total_calls": len(self._calls),
            "endpoints": self.get_endpoint_stats(),
        }


# ============================================================================
# 数据质量监控
# ============================================================================

class DataQualityMonitor:
    """数据质量监控器"""

    def __init__(self):
        self._quality_history = deque(maxlen=168)  # 一周
        self._last_update: Optional[float] = None

    def record_quality(self, quality_score: float, anomaly_count: int = 0):
        """记录数据质量"""
        self._quality_history.append({
            "timestamp": time.time(),
            "quality_score": quality_score,
            "anomaly_count": anomaly_count,
        })
        self._last_update = time.time()

    def get_avg_quality(self) -> float:
        """获取平均质量分数"""
        if not self._quality_history:
            return 0.0
        return float(np.mean([q["quality_score"] for q in self._quality_history]))

    def get_data_freshness_seconds(self) -> float:
        """获取数据新鲜度 (距离上次更新的秒数)"""
        if self._last_update is None:
            return float("inf")
        return time.time() - self._last_update

    def get_stats(self) -> Dict[str, Any]:
        """获取完整统计"""
        return {
            "avg_quality": round(self.get_avg_quality(), 4),
            "data_freshness_seconds": round(self.get_data_freshness_seconds(), 1),
            "total_records": len(self._quality_history),
            "avg_anomalies": float(np.mean([
                q["anomaly_count"] for q in self._quality_history
            ])) if self._quality_history else 0.0,
        }


# ============================================================================
# 监控服务主类
# ============================================================================

class MonitoringService:
    """
    系统监控服务

    整合预测准确率、API调用、数据质量、模型漂移监控，
    提供 Prometheus 指标导出和告警机制。

    使用方式:
        monitor = MonitoringService()
        monitor.record_prediction(actual=15200, predicted=14950)
        monitor.record_api_call("/api/prediction/load", 200, 150.5)
        monitor.check_alerts()
        monitor.export_metrics()  # Prometheus 格式
    """

    # 告警规则默认配置
    DEFAULT_RULES = [
        AlertRule(
            name="high_mape",
            description="预测MAPE超过5%",
            metric_name="mape",
            condition="gt",
            threshold=5.0,
            severity="warning",
        ),
        AlertRule(
            name="critical_mape",
            description="预测MAPE超过10%",
            metric_name="mape",
            condition="gt",
            threshold=10.0,
            severity="critical",
        ),
        AlertRule(
            name="high_response_time",
            description="平均响应时间超过2000ms",
            metric_name="avg_response_ms",
            condition="gt",
            threshold=2000.0,
            severity="warning",
        ),
        AlertRule(
            name="high_error_rate",
            description="API错误率超过5%",
            metric_name="error_rate",
            condition="gt",
            threshold=0.05,
            severity="error",
        ),
        AlertRule(
            name="data_stale",
            description="数据超过10分钟未更新",
            metric_name="data_freshness_seconds",
            condition="gt",
            threshold=600.0,
            severity="warning",
        ),
        AlertRule(
            name="low_data_quality",
            description="数据质量分数低于0.8",
            metric_name="avg_quality",
            condition="lt",
            threshold=0.8,
            severity="warning",
        ),
        AlertRule(
            name="model_drift",
            description="检测到模型漂移 (PSI>0.25)",
            metric_name="psi_predictions",
            condition="gt",
            threshold=0.25,
            severity="error",
        ),
    ]

    def __init__(
        self,
        alert_rules: Optional[List[AlertRule]] = None,
        enable_prometheus: bool = True,
        prometheus_port: int = 9095,
        log_file: Optional[str] = None,
    ):
        """
        Args:
            alert_rules: 自定义告警规则
            enable_prometheus: 是否启用Prometheus导出
            prometheus_port: Prometheus指标端口
            log_file: 结构化日志文件路径
        """
        # 初始化日志
        setup_structured_logging(
            level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=log_file,
        )
        self.logger = logging.getLogger("monitoring")

        # 子模块
        self.accuracy = AccuracyTracker()
        self.api_tracker = APICallTracker()
        self.data_quality = DataQualityMonitor()
        self.drift_detector = ModelDriftDetector()

        # 告警
        self.alert_rules = alert_rules or self.DEFAULT_RULES
        self.active_alerts: List[Alert] = []
        self.alert_history: deque = deque(maxlen=1000)
        self._alert_callbacks: List[Callable] = []

        # Prometheus 指标
        self._init_prometheus(enable_prometheus, prometheus_port)

        # 运行统计
        self._start_time = time.time()
        self._total_alerts_fired = 0

        self.logger.info("MonitoringService 初始化完成")
        self.logger.info(f"  告警规则: {len(self.alert_rules)} 条")
        self.logger.info(f"  Prometheus: {'启用' if enable_prometheus else '禁用'}")

    # ========================================================================
    # Prometheus 初始化
    # ========================================================================

    def _init_prometheus(self, enable: bool, port: int):
        """初始化 Prometheus 指标"""
        self.registry = None
        self.metrics = {}

        if not enable or not HAS_PROMETHEUS:
            self.logger.warning("Prometheus 未启用或未安装 prometheus-client")
            return

        self.registry = CollectorRegistry()

        # 预测准确率
        self.metrics["mape"] = Gauge(
            "grid_predict_mape", "平均绝对百分比误差", registry=self.registry
        )
        self.metrics["rmse"] = Gauge(
            "grid_predict_rmse", "均方根误差", registry=self.registry
        )
        self.metrics["mae"] = Gauge(
            "grid_predict_mae", "平均绝对误差", registry=self.registry
        )
        self.metrics["r2"] = Gauge(
            "grid_predict_r2", "决定系数", registry=self.registry
        )

        # API 指标
        self.metrics["api_calls_total"] = Counter(
            "grid_predict_api_calls_total", "API调用总数",
            ["endpoint", "status"], registry=self.registry
        )
        self.metrics["api_response_time"] = Histogram(
            "grid_predict_api_response_time_ms", "API响应时间",
            ["endpoint"], registry=self.registry
        )
        self.metrics["api_error_rate"] = Gauge(
            "grid_predict_api_error_rate", "API错误率", registry=self.registry
        )
        self.metrics["api_call_rate"] = Gauge(
            "grid_predict_api_call_rate_per_sec", "API调用频率", registry=self.registry
        )

        # 数据质量
        self.metrics["data_quality"] = Gauge(
            "grid_predict_data_quality", "数据质量分数", registry=self.registry
        )
        self.metrics["data_freshness"] = Gauge(
            "grid_predict_data_freshness_seconds", "数据新鲜度(秒)", registry=self.registry
        )

        # 模型漂移
        self.metrics["psi_predictions"] = Gauge(
            "grid_predict_psi_predictions", "预测分布PSI", registry=self.registry
        )
        self.metrics["psi_errors"] = Gauge(
            "grid_predict_psi_errors", "误差分布PSI", registry=self.registry
        )

        # 系统指标
        self.metrics["uptime"] = Gauge(
            "grid_predict_uptime_seconds", "服务运行时间", registry=self.registry
        )
        self.metrics["active_alerts"] = Gauge(
            "grid_predict_active_alerts", "活跃告警数", registry=self.registry
        )

        # 推理时间
        self.metrics["inference_time"] = Histogram(
            "grid_predict_inference_time_ms", "模型推理时间", registry=self.registry,
            buckets=(10, 50, 100, 200, 500, 1000, 2000, 5000)
        )

        # 启动 HTTP 服务
        try:
            start_http_server(port, registry=self.registry)
            self.logger.info(f"  Prometheus 指标端口: :{port}/metrics")
        except Exception as e:
            self.logger.warning(f"  Prometheus HTTP 启动失败: {e}")

    # ========================================================================
    # 数据记录方法
    # ========================================================================

    def record_prediction(
        self,
        actual: float,
        predicted: float,
        timestamp: Optional[str] = None,
    ):
        """记录预测-实际值对"""
        self.accuracy.record(predicted, actual, timestamp)

        if self.metrics:
            stats = self.accuracy.get_stats()
            self.metrics["mape"].set(stats["mape"])
            self.metrics["rmse"].set(stats["rmse"])
            self.metrics["mae"].set(stats["mae"])
            self.metrics["r2"].set(stats["r2"])

        self.logger.debug(
            f"记录预测: actual={actual}, predicted={predicted}",
            extra={"extra_fields": {"actual": actual, "predicted": predicted}}
        )

    def record_api_call(
        self,
        endpoint: str,
        status_code: int,
        duration_ms: float,
    ):
        """记录API调用"""
        self.api_tracker.record(endpoint, status_code, duration_ms)

        if self.metrics:
            self.metrics["api_calls_total"].labels(
                endpoint=endpoint, status=str(status_code)
            ).inc()
            self.metrics["api_response_time"].labels(
                endpoint=endpoint
            ).observe(duration_ms)
            self.metrics["api_error_rate"].set(self.api_tracker.get_error_rate())
            self.metrics["api_call_rate"].set(self.api_tracker.get_call_rate())

    def record_data_quality(self, quality_score: float, anomaly_count: int = 0):
        """记录数据质量"""
        self.data_quality.record_quality(quality_score, anomaly_count)

        if self.metrics:
            self.metrics["data_quality"].set(quality_score)
            self.metrics["data_freshness"].set(
                self.data_quality.get_data_freshness_seconds()
            )

    def record_inference_time(self, duration_ms: float):
        """记录推理时间"""
        if self.metrics:
            self.metrics["inference_time"].observe(duration_ms)

    def set_drift_reference(self, predictions: np.ndarray, errors: np.ndarray):
        """设置漂移检测参考分布"""
        self.drift_detector.set_reference(predictions, errors)
        self.logger.info(f"漂移参考分布已设置: {len(predictions)} 样本")

    def check_drift(
        self,
        current_predictions: np.ndarray,
        current_errors: np.ndarray,
    ) -> Dict:
        """检测模型漂移"""
        result = self.drift_detector.detect_drift(current_predictions, current_errors)

        if self.metrics and "psi_predictions" in result:
            self.metrics["psi_predictions"].set(result.get("psi_predictions", 0))
            self.metrics["psi_errors"].set(result.get("psi_errors", 0))

        if result.get("drift_detected"):
            self.logger.warning(f"模型漂移检测: {result['message']}")

        return result

    # ========================================================================
    # 告警机制
    # ========================================================================

    def add_alert_callback(self, callback: Callable[[Alert], None]):
        """添加告警回调函数"""
        self._alert_callbacks.append(callback)

    def _get_metric_value(self, metric_name: str) -> float:
        """获取当前指标值"""
        stats = self.get_all_stats()
        return stats.get(metric_name, 0.0)

    def _evaluate_condition(self, value: float, condition: str, threshold: float) -> bool:
        """评估条件"""
        if condition == "gt":
            return value > threshold
        elif condition == "lt":
            return value < threshold
        elif condition == "gte":
            return value >= threshold
        elif condition == "lte":
            return value <= threshold
        elif condition == "eq":
            return abs(value - threshold) < 1e-6
        return False

    def check_alerts(self) -> List[Alert]:
        """检查所有告警规则"""
        now = time.time()
        fired_alerts = []
        stats = self.get_all_stats()

        for rule in self.alert_rules:
            # 冷却检查
            if now - rule.last_fired < rule.cooldown_seconds:
                continue

            value = stats.get(rule.metric_name, 0.0)

            if self._evaluate_condition(value, rule.condition, rule.threshold):
                alert = Alert(
                    name=rule.name,
                    severity=rule.severity,
                    message=rule.description,
                    value=value,
                    threshold=rule.threshold,
                    metadata={"metric": rule.metric_name},
                )
                fired_alerts.append(alert)
                rule.last_fired = now
                self._total_alerts_fired += 1

                # 触发回调
                for callback in self._alert_callbacks:
                    try:
                        callback(alert)
                    except Exception as e:
                        self.logger.error(f"告警回调失败: {e}")

                # 日志
                log_method = (
                    self.logger.critical if rule.severity == "critical"
                    else self.logger.error if rule.severity == "error"
                    else self.logger.warning if rule.severity == "warning"
                    else self.logger.info
                )
                log_method(
                    f"告警触发: {alert.name} - {alert.message} "
                    f"(值={alert.value:.2f}, 阈值={alert.threshold:.2f})",
                    extra={"extra_fields": alert.to_dict()}
                )

        # 更新活跃告警
        self.active_alerts = fired_alerts
        self.alert_history.extend(fired_alerts)

        if self.metrics:
            self.metrics["active_alerts"].set(len(fired_alerts))

        return fired_alerts

    # ========================================================================
    # 指标导出
    # ========================================================================

    def export_metrics(self) -> str:
        """导出 Prometheus 格式指标"""
        if self.registry and HAS_PROMETHEUS:
            # 更新实时指标
            if self.metrics:
                stats = self.get_all_stats()
                self.metrics["uptime"].set(time.time() - self._start_time)

            return generate_latest(self.registry).decode("utf-8")
        return ""

    def get_all_stats(self) -> Dict[str, Any]:
        """获取所有统计数据"""
        accuracy_stats = self.accuracy.get_stats()
        api_stats = self.api_tracker.get_stats()
        quality_stats = self.data_quality.get_stats()

        return {
            # 预测准确率
            "mape": accuracy_stats["mape"],
            "rmse": accuracy_stats["rmse"],
            "mae": accuracy_stats["mae"],
            "r2": accuracy_stats["r2"],
            "prediction_count": accuracy_stats["count"],
            # API
            "api_call_rate_per_sec": api_stats["call_rate_per_sec"],
            "error_rate": api_stats["error_rate"],
            "avg_response_ms": api_stats["avg_response_ms"],
            "total_api_calls": api_stats["total_calls"],
            # 数据质量
            "avg_quality": quality_stats["avg_quality"],
            "data_freshness_seconds": quality_stats["data_freshness_seconds"],
            # 系统
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "active_alerts": len(self.active_alerts),
            "total_alerts_fired": self._total_alerts_fired,
        }

    def get_dashboard_data(self) -> Dict[str, Any]:
        """获取仪表盘数据"""
        stats = self.get_all_stats()

        return {
            "summary": {
                "mape": round(stats["mape"], 2),
                "rmse": round(stats["rmse"], 1),
                "r2": round(stats["r2"], 4),
                "api_error_rate": round(stats["error_rate"] * 100, 2),
                "avg_response_ms": round(stats["avg_response_ms"], 0),
                "data_quality": round(stats["avg_quality"], 3),
                "uptime_hours": round(stats["uptime_seconds"] / 3600, 1),
                "active_alerts": stats["active_alerts"],
            },
            "accuracy": stats,
            "api": self.api_tracker.get_stats(),
            "data_quality": self.data_quality.get_stats(),
            "alerts": {
                "active": [a.to_dict() for a in self.active_alerts],
                "history_count": len(self.alert_history),
            },
            "endpoints": self.api_tracker.get_endpoint_stats(),
            "timestamp": datetime.now().isoformat(),
        }


# ============================================================================
# 使用示例
# ============================================================================

def demo():
    """演示监控服务"""
    print("=" * 60)
    print("系统监控模块演示")
    print("=" * 60)

    # 创建监控服务 (不启用Prometheus HTTP)
    monitor = MonitoringService(
        enable_prometheus=False,
        log_file=None,
    )

    # 添加告警回调
    def alert_handler(alert: Alert):
        print(f"  🚨 [{alert.severity.upper()}] {alert.name}: {alert.message}")

    monitor.add_alert_callback(alert_handler)

    # 1. 模拟预测记录
    print("\n[1] 模拟预测记录...")
    np.random.seed(42)
    for i in range(50):
        actual = 15000 + 2000 * np.sin(i * 0.1) + np.random.normal(0, 100)
        predicted = actual + np.random.normal(0, 200)  # 有误差
        if i > 40:  # 后面误差变大
            predicted = actual + np.random.normal(0, 800)
        monitor.record_prediction(actual, predicted)

    stats = monitor.accuracy.get_stats()
    print(f"  MAPE: {stats['mape']:.2f}%")
    print(f"  RMSE: {stats['rmse']:.1f}")
    print(f"  R²: {stats['r2']:.4f}")

    # 2. 模拟API调用
    print("\n[2] 模拟API调用...")
    for i in range(100):
        endpoint = np.random.choice([
            "/api/prediction/load",
            "/api/weather/current",
            "/api/system/status",
        ])
        status = 200 if np.random.random() > 0.05 else 500
        duration = np.random.exponential(100)
        monitor.record_api_call(endpoint, status, duration)

    api_stats = monitor.api_tracker.get_stats()
    print(f"  调用频率: {api_stats['call_rate_per_sec']:.2f}/s")
    print(f"  错误率: {api_stats['error_rate']*100:.1f}%")
    print(f"  平均响应: {api_stats['avg_response_ms']:.0f}ms")

    # 3. 模拟数据质量
    print("\n[3] 模拟数据质量...")
    monitor.record_data_quality(0.95, 2)
    monitor.record_data_quality(0.88, 5)
    print(f"  平均质量: {monitor.data_quality.get_avg_quality():.3f}")

    # 4. 模型漂移检测
    print("\n[4] 模型漂移检测...")
    ref_preds = np.random.normal(15000, 500, 200)
    ref_errors = np.abs(np.random.normal(0, 200, 200))
    monitor.set_drift_reference(ref_preds, ref_errors)

    cur_preds = np.random.normal(15500, 700, 50)  # 有漂移
    cur_errors = np.abs(np.random.normal(0, 400, 50))
    drift_result = monitor.check_drift(cur_preds, cur_errors)
    print(f"  PSI(预测): {drift_result['psi_predictions']:.4f}")
    print(f"  PSI(误差): {drift_result['psi_errors']:.4f}")
    print(f"  漂移级别: {drift_result['status']}")

    # 5. 检查告警
    print("\n[5] 检查告警...")
    alerts = monitor.check_alerts()
    print(f"  触发告警: {len(alerts)} 条")

    # 6. 仪表盘数据
    print("\n[6] 仪表盘数据:")
    dashboard = monitor.get_dashboard_data()
    print(json.dumps(dashboard["summary"], indent=2, ensure_ascii=False))

    # 7. Prometheus 指标
    print("\n[7] Prometheus 指标 (部分):")
    metrics_text = monitor.export_metrics()
    if metrics_text:
        for line in metrics_text.split("\n")[:10]:
            if line and not line.startswith("#"):
                print(f"  {line}")
    else:
        print("  (Prometheus 未启用)")

    return monitor


if __name__ == "__main__":
    demo()
