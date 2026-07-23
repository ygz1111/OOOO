"""
系统监控模块单元测试

测试内容:
  1. 结构化日志
  2. 预测准确率跟踪 (MAPE/RMSE/MAE/R²)
  3. 模型漂移检测 (PSI/KS)
  4. API调用统计
  5. 数据质量监控
  6. 告警机制
  7. Prometheus 指标导出
  8. 仪表盘数据
  9. 边界情况

运行方式:
    cd c:/OOOO/OOOO
    python realtime_api/test_monitoring_service.py -v
"""

import unittest
import os
import sys
import time
import json
import tempfile
import logging
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtime_api.monitoring_service import (
    MonitoringService,
    AccuracyTracker,
    ModelDriftDetector,
    APICallTracker,
    DataQualityMonitor,
    Alert,
    AlertRule,
    StructuredFormatter,
    setup_structured_logging,
)


# ============================================================================
# 结构化日志测试
# ============================================================================

class TestStructuredLogging(unittest.TestCase):
    """测试结构化日志"""

    def test_formatter_produces_json(self):
        """测试格式化器输出JSON"""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="test message %s", args=("arg",), exc_info=None
        )
        output = formatter.format(record)
        data = json.loads(output)
        self.assertEqual(data["message"], "test message arg")
        self.assertEqual(data["level"], "INFO")

    def test_setup_logging(self):
        """测试日志设置不报错"""
        log_file = tempfile.mktemp(suffix=".log")

        try:
            setup_structured_logging(level="DEBUG", log_file=log_file)
            logger = logging.getLogger("test_setup")
            logger.info("test log entry")
            # 刷新并关闭 handlers
            for h in logging.getLogger().handlers:
                h.flush()
                h.close()
            logging.getLogger().handlers.clear()

            # 验证文件写入
            if os.path.exists(log_file):
                with open(log_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    self.assertIn("test log entry", content)
        finally:
            # 关闭可能残留的 handler
            for h in logging.getLogger().handlers:
                h.close()
            if os.path.exists(log_file):
                try:
                    os.unlink(log_file)
                except PermissionError:
                    pass  # Windows 可能仍锁定文件


# ============================================================================
# 准确率跟踪测试
# ============================================================================

class TestAccuracyTracker(unittest.TestCase):
    """测试预测准确率跟踪"""

    def setUp(self):
        self.tracker = AccuracyTracker(window_size=100)
        np.random.seed(42)

    def test_empty_stats(self):
        """测试空数据统计"""
        stats = self.tracker.get_stats()
        self.assertEqual(stats["mape"], 0.0)
        self.assertEqual(stats["rmse"], 0.0)
        self.assertEqual(stats["count"], 0)

    def test_perfect_prediction(self):
        """测试完美预测 (误差为0)"""
        for v in [100, 200, 300]:
            self.tracker.record(v, v)
        stats = self.tracker.get_stats()
        self.assertAlmostEqual(stats["mape"], 0.0)
        self.assertAlmostEqual(stats["rmse"], 0.0)
        self.assertAlmostEqual(stats["r2"], 1.0)

    def test_mape_calculation(self):
        """测试MAPE计算"""
        self.tracker.record(110, 100)  # pred=110, actual=100, MAPE=10%
        self.tracker.record(190, 200)  # pred=190, actual=200, MAPE=5%
        # MAPE = (10 + 5) / 2 = 7.5%
        self.assertAlmostEqual(self.tracker.compute_mape(), 7.5, places=1)

    def test_rmse_calculation(self):
        """测试RMSE计算"""
        self.tracker.record(100, 110)  # 误差10
        self.tracker.record(200, 190)  # 误差-10
        # RMSE = sqrt((100+100)/2) = 10
        self.assertAlmostEqual(self.tracker.compute_rmse(), 10.0, places=1)

    def test_mae_calculation(self):
        """测试MAE计算"""
        self.tracker.record(100, 110)
        self.tracker.record(200, 190)
        # MAE = (10+10)/2 = 10
        self.assertAlmostEqual(self.tracker.compute_mae(), 10.0)

    def test_r2_calculation(self):
        """测试R²计算"""
        actuals = [100, 200, 300, 400]
        preds = [105, 195, 305, 395]  # 接近实际值
        for a, p in zip(actuals, preds):
            self.tracker.record(p, a)
        r2 = self.tracker.compute_r2()
        self.assertGreater(r2, 0.99)

    def test_window_size(self):
        """测试滑动窗口"""
        tracker = AccuracyTracker(window_size=5)
        for i in range(10):
            tracker.record(float(i), float(i))
        self.assertEqual(len(tracker.predictions), 5)

    def test_zero_actual_no_crash(self):
        """测试实际值为0时不崩溃"""
        self.tracker.record(0, 0)
        self.tracker.record(100, 100)
        stats = self.tracker.get_stats()
        self.assertGreaterEqual(stats["mape"], 0)


# ============================================================================
# 模型漂移检测测试
# ============================================================================

class TestModelDriftDetector(unittest.TestCase):
    """测试模型漂移检测"""

    def setUp(self):
        self.detector = ModelDriftDetector(reference_size=100)
        np.random.seed(42)

    def test_no_reference(self):
        """测试未设置参考分布"""
        result = self.detector.detect_drift(
            np.array([1, 2, 3]), np.array([0.1, 0.2])
        )
        self.assertEqual(result["status"], "no_reference")

    def test_no_drift(self):
        """测试无漂移 (相同分布)"""
        ref = np.random.normal(100, 10, 500)
        self.detector.set_reference(ref, np.abs(np.random.normal(0, 5, 500)))

        cur = np.random.normal(100, 10, 200)  # 相同分布，更多样本
        result = self.detector.detect_drift(cur, np.abs(np.random.normal(0, 5, 200)))
        self.assertLess(result["psi_predictions"], 0.3)
        self.assertFalse(result["drift_detected"])

    def test_drift_detected(self):
        """测试检测到漂移 (不同分布)"""
        ref = np.random.normal(100, 10, 200)
        self.detector.set_reference(ref, np.abs(np.random.normal(0, 5, 200)))

        cur = np.random.normal(150, 20, 50)  # 均值偏移50
        result = self.detector.detect_drift(cur, np.abs(np.random.normal(0, 15, 50)))
        self.assertGreater(result["psi_predictions"], 0.1)

    def test_psi_identical_distributions(self):
        """测试相同分布PSI接近0"""
        dist = np.random.normal(100, 10, 200)
        psi = self.detector.compute_psi(dist, dist)
        self.assertLess(psi, 0.1)

    def test_psi_different_distributions(self):
        """测试不同分布PSI较大"""
        ref = np.random.normal(100, 10, 200)
        cur = np.random.normal(200, 20, 200)
        psi = self.detector.compute_psi(ref, cur)
        self.assertGreater(psi, 0.25)

    def test_psi_empty_arrays(self):
        """测试空数组PSI为0"""
        psi = self.detector.compute_psi(np.array([]), np.array([]))
        self.assertEqual(psi, 0.0)


# ============================================================================
# API调用统计测试
# ============================================================================

class TestAPICallTracker(unittest.TestCase):
    """测试API调用统计"""

    def setUp(self):
        self.tracker = APICallTracker(window_seconds=60)

    def test_empty_stats(self):
        """测试空统计"""
        stats = self.tracker.get_stats()
        self.assertEqual(stats["call_rate_per_sec"], 0.0)
        self.assertEqual(stats["error_rate"], 0.0)

    def test_record_call(self):
        """测试记录调用"""
        self.tracker.record("/api/test", 200, 100.0)
        stats = self.tracker.get_stats()
        self.assertEqual(stats["total_calls"], 1)
        self.assertEqual(stats["avg_response_ms"], 100.0)

    def test_error_rate(self):
        """测试错误率计算"""
        self.tracker.record("/api/test", 200, 100.0)
        self.tracker.record("/api/test", 500, 100.0)
        self.tracker.record("/api/test", 200, 100.0)
        self.tracker.record("/api/test", 500, 100.0)
        # 2/4 = 50%
        self.assertAlmostEqual(self.tracker.get_error_rate(), 0.5)

    def test_endpoint_stats(self):
        """测试端点统计"""
        self.tracker.record("/api/predict", 200, 100.0)
        self.tracker.record("/api/predict", 200, 200.0)
        self.tracker.record("/api/weather", 200, 50.0)

        stats = self.tracker.get_endpoint_stats()
        self.assertIn("/api/predict", stats)
        self.assertIn("/api/weather", stats)
        self.assertEqual(stats["/api/predict"]["count"], 2)

    def test_call_rate(self):
        """测试调用频率"""
        for _ in range(10):
            self.tracker.record("/api/test", 200, 100.0)
        rate = self.tracker.get_call_rate()
        self.assertGreater(rate, 0)

    def test_window_expiry(self):
        """测试窗口过期"""
        # 记录旧数据 (2分钟前)
        old_time = time.time() - 120
        self.tracker.record("/api/old", 200, 100.0, timestamp=old_time)
        # 记录新数据
        self.tracker.record("/api/new", 200, 100.0)
        stats = self.tracker.get_stats()
        # 旧数据应被清理
        self.assertEqual(stats["total_calls"], 1)


# ============================================================================
# 数据质量监控测试
# ============================================================================

class TestDataQualityMonitor(unittest.TestCase):
    """测试数据质量监控"""

    def setUp(self):
        self.monitor = DataQualityMonitor()

    def test_empty_stats(self):
        """测试空统计"""
        stats = self.monitor.get_stats()
        self.assertEqual(stats["avg_quality"], 0.0)

    def test_record_quality(self):
        """测试记录质量"""
        self.monitor.record_quality(0.95, 2)
        self.monitor.record_quality(0.90, 3)
        self.assertAlmostEqual(self.monitor.get_avg_quality(), 0.925, places=2)

    def test_data_freshness(self):
        """测试数据新鲜度"""
        self.monitor.record_quality(0.95, 0)
        freshness = self.monitor.get_data_freshness_seconds()
        self.assertGreaterEqual(freshness, 0)
        self.assertLess(freshness, 5)

    def test_stale_data(self):
        """测试数据过期"""
        # 不记录任何数据，freshness应为inf
        self.assertEqual(self.monitor.get_data_freshness_seconds(), float("inf"))


# ============================================================================
# 告警机制测试
# ============================================================================

class TestAlerting(unittest.TestCase):
    """测试告警机制"""

    def setUp(self):
        self.monitor = MonitoringService(
            enable_prometheus=False,
            alert_rules=[
                AlertRule(
                    name="test_high_mape",
                    description="MAPE过高",
                    metric_name="mape",
                    condition="gt",
                    threshold=5.0,
                    severity="warning",
                    cooldown_seconds=0,  # 测试用，无冷却
                ),
            ],
        )

    def test_no_alert_when_ok(self):
        """测试正常时不告警"""
        # 记录完美预测
        for v in [100, 200, 300]:
            self.monitor.record_prediction(float(v), float(v))
        alerts = self.monitor.check_alerts()
        self.assertEqual(len(alerts), 0)

    def test_alert_when_threshold_exceeded(self):
        """测试超过阈值时告警"""
        # 记录有误差的预测 (MAPE > 5%)
        self.monitor.record_prediction(100, 80)  # 20% 误差
        alerts = self.monitor.check_alerts()
        self.assertGreater(len(alerts), 0)
        self.assertEqual(alerts[0].name, "test_high_mape")
        self.assertEqual(alerts[0].severity, "warning")

    def test_alert_callback(self):
        """测试告警回调"""
        received = []

        def callback(alert: Alert):
            received.append(alert)

        self.monitor.add_alert_callback(callback)
        self.monitor.record_prediction(100, 80)
        self.monitor.check_alerts()
        self.assertGreater(len(received), 0)

    def test_alert_cooldown(self):
        """测试告警冷却"""
        monitor = MonitoringService(
            enable_prometheus=False,
            alert_rules=[
                AlertRule(
                    name="test_cooldown",
                    description="冷却测试",
                    metric_name="mape",
                    condition="gt",
                    threshold=1.0,
                    severity="warning",
                    cooldown_seconds=60,  # 60秒冷却
                ),
            ],
        )
        monitor.record_prediction(100, 80)  # 高误差

        # 第一次应告警
        alerts1 = monitor.check_alerts()
        self.assertEqual(len(alerts1), 1)

        # 冷却期内不应告警
        alerts2 = monitor.check_alerts()
        self.assertEqual(len(alerts2), 0)

    def test_alert_to_dict(self):
        """测试告警转字典"""
        alert = Alert(
            name="test", severity="warning",
            message="test", value=10.5, threshold=5.0
        )
        d = alert.to_dict()
        self.assertEqual(d["name"], "test")
        self.assertEqual(d["value"], 10.5)
        self.assertIn("timestamp", d)


# ============================================================================
# 监控服务集成测试
# ============================================================================

class TestMonitoringService(unittest.TestCase):
    """测试监控服务主类"""

    def setUp(self):
        self.monitor = MonitoringService(enable_prometheus=False)

    def test_record_prediction(self):
        """测试记录预测"""
        self.monitor.record_prediction(100, 95)
        stats = self.monitor.get_all_stats()
        self.assertEqual(stats["prediction_count"], 1)
        self.assertGreater(stats["mape"], 0)

    def test_record_api_call(self):
        """测试记录API调用"""
        self.monitor.record_api_call("/api/test", 200, 100.0)
        stats = self.monitor.get_all_stats()
        self.assertEqual(stats["total_api_calls"], 1)

    def test_record_data_quality(self):
        """测试记录数据质量"""
        self.monitor.record_data_quality(0.95, 1)
        stats = self.monitor.get_all_stats()
        self.assertAlmostEqual(stats["avg_quality"], 0.95)

    def test_record_inference_time(self):
        """测试记录推理时间"""
        self.monitor.record_inference_time(150.0)
        # 不应崩溃
        self.assertTrue(True)

    def test_get_dashboard_data(self):
        """测试获取仪表盘数据"""
        self.monitor.record_prediction(100, 95)
        self.monitor.record_api_call("/api/test", 200, 100.0)

        dashboard = self.monitor.get_dashboard_data()
        self.assertIn("summary", dashboard)
        self.assertIn("accuracy", dashboard)
        self.assertIn("api", dashboard)
        self.assertIn("alerts", dashboard)
        self.assertIn("timestamp", dashboard)

    def test_export_metrics_no_prometheus(self):
        """测试无Prometheus时导出为空"""
        metrics = self.monitor.export_metrics()
        self.assertEqual(metrics, "")

    def test_check_drift_no_reference(self):
        """测试未设参考时漂移检测"""
        result = self.monitor.check_drift(
            np.array([1, 2, 3]), np.array([0.1, 0.2])
        )
        self.assertEqual(result["status"], "no_reference")

    def test_set_drift_reference(self):
        """测试设置漂移参考"""
        preds = np.random.normal(100, 10, 200)
        errors = np.abs(np.random.normal(0, 5, 200))
        self.monitor.set_drift_reference(preds, errors)

        result = self.monitor.check_drift(
            np.random.normal(100, 10, 50),
            np.abs(np.random.normal(0, 5, 50))
        )
        self.assertIn("psi_predictions", result)

    def test_default_alert_rules(self):
        """测试默认告警规则"""
        monitor = MonitoringService(enable_prometheus=False)
        self.assertGreater(len(monitor.alert_rules), 0)
        rule_names = [r.name for r in monitor.alert_rules]
        self.assertIn("high_mape", rule_names)
        self.assertIn("high_error_rate", rule_names)
        self.assertIn("model_drift", rule_names)


# ============================================================================
# 边界情况测试
# ============================================================================

class TestEdgeCases(unittest.TestCase):
    """测试边界情况"""

    def setUp(self):
        self.monitor = MonitoringService(enable_prometheus=False)

    def test_single_prediction(self):
        """测试单次预测"""
        self.monitor.record_prediction(100, 100)
        stats = self.monitor.get_all_stats()
        self.assertEqual(stats["mape"], 0.0)

    def test_negative_values(self):
        """测试负值"""
        self.monitor.record_prediction(-100, -110)
        # 不应崩溃
        stats = self.monitor.get_all_stats()
        self.assertGreaterEqual(stats["mape"], 0)

    def test_large_values(self):
        """测试大数值"""
        self.monitor.record_prediction(50000, 51000)
        stats = self.monitor.get_all_stats()
        self.assertGreater(stats["mape"], 0)

    def test_many_records(self):
        """测试大量记录"""
        for i in range(200):
            self.monitor.record_prediction(float(i + 100), float(i + 100 + 1))
        stats = self.monitor.get_all_stats()
        # 窗口大小默认168，超过后只保留最近168条
        self.assertGreaterEqual(stats["prediction_count"], 168)

    def test_concurrent_api_calls(self):
        """测试并发API调用记录"""
        import threading

        def record_calls():
            for i in range(50):
                self.monitor.record_api_call("/api/test", 200, 100.0)

        threads = [threading.Thread(target=record_calls) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = self.monitor.get_all_stats()
        self.assertEqual(stats["total_api_calls"], 200)

    def test_empty_drift_detection(self):
        """测试空数组漂移检测"""
        monitor = MonitoringService(enable_prometheus=False)
        monitor.set_drift_reference(
            np.array([1, 2, 3]), np.array([0.1, 0.2, 0.3])
        )
        result = monitor.check_drift(np.array([]), np.array([]))
        self.assertFalse(result["drift_detected"])


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
