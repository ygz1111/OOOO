"""Monitor contract tests using isolated counters and deterministic host probes."""

from dataclasses import replace
from datetime import datetime, timedelta
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from realtime_api import monitoring_service as monitor


def test_accuracy_window_keeps_pairs_and_reports_real_units():
    tracker = monitor.AccuracyTracker(window_size=2)
    assert tracker.get_stats() == {
        "count": 0, "mape": 0.0, "rmse": 0.0, "mae": 0.0,
        "r2": 0.0, "window_size": 2,
    }
    tracker.record(999, 999, "discarded", "old")
    tracker.record(110, 100, "2026-10-01T00:00:00-04:00", "load")
    tracker.record(180, 200, model_name="load")
    stats = tracker.get_stats()
    assert stats["count"] == 2
    assert stats["mape"] == pytest.approx(10)
    assert stats["mae"] == 15
    assert stats["rmse"] == pytest.approx(np.sqrt(250))
    assert stats["r2"] == pytest.approx(0.9)
    recent = tracker.get_recent_predictions(limit=10)
    assert [p["actual"] for p in recent] == [200, 100]
    assert [p["error"] for p in recent] == [20, -10]
    assert recent[0]["model_name"] == "load"
    assert datetime.fromisoformat(recent[0]["timestamp"])


def test_accuracy_zero_denominators_and_single_record():
    tracker = monitor.AccuracyTracker()
    tracker.record(5, 0)
    assert tracker.compute_mape() == 0
    assert tracker.compute_r2() == 0
    tracker.record(7, 0)
    assert tracker.compute_r2() == 1
    assert tracker.compute_mae() == 6


def test_drift_requires_enough_samples_and_detects_distribution_shift():
    detector = monitor.ModelDriftDetector()
    assert detector.compute_psi() == 0
    assert detector.detect_drift()["drift_detected"] is False
    reference = np.linspace(1, 100, 100).tolist()
    detector.update_reference(reference, reference)
    detector.update_current(reference, reference)
    for variable in ("predictions", "actuals", "errors", "invalid"):
        assert detector.compute_psi(variable) == 0
    detector.current_predictions.clear()
    detector.current_actuals.clear()
    shifted = np.concatenate([np.linspace(1, 25, 90), np.linspace(26, 100, 10)]).tolist()
    detector.update_current(shifted, shifted)
    result = detector.detect_drift()
    assert result["drift_detected"] is True
    assert result["psi_predictions"] > 0.25
    assert result["psi_actuals"] > 0.25
    assert result["reference_size"] == result["current_size"] == 100


def test_weather_quality_identifies_each_fault_and_clamps_score():
    quality = monitor.DataQualityMonitor()
    assert quality.get_quality_stats() == {"valid_rate": 0.0, "avg_score": 0.0, "total_checks": 0}
    normal = quality.validate_weather_data({
        "temperature_2m": 10, "dew_point_2m": 8,
        "relative_humidity_2m": 70, "cloud_cover": 30, "shortwave_radiation": 300,
    })
    assert normal["is_valid"] is True
    assert normal["quality_score"] == 1
    bad = quality.validate_weather_data({
        "temperature_2m": 50, "dew_point_2m": 60,
        "relative_humidity_2m": 101, "cloud_cover": -1, "shortwave_radiation": -1,
    })
    assert bad["is_valid"] is False
    assert len(bad["issues"]) == 5
    assert bad["quality_score"] == 0
    assert quality.get_quality_stats() == {"valid_rate": 0.5, "avg_score": 0.5, "total_checks": 2}


def test_counter_aggregation_covers_requests_cache_batch_and_device(monkeypatch):
    service = monitor.MonitoringService(history_size=2)
    monkeypatch.setattr(monitor.time, "time", lambda: service.start_time + 2)
    service.record_api_request(10, True)
    service.record_api_request(30, False)
    service.websocket_clients.append(object())
    api = service._collect_api_metrics()
    assert (api.total_requests, api.successful_requests, api.failed_requests) == (2, 1, 1)
    assert api.average_response_time_ms == 20
    assert api.p50_response_time_ms == 20
    assert api.p95_response_time_ms == pytest.approx(29)
    assert api.p99_response_time_ms == pytest.approx(29.8)
    assert api.requests_per_second == 1
    assert api.active_connections == 1
    service.record_model_inference(10, True, cache_hit=True, is_batch=True, device="cuda")
    service.record_model_inference(30, False)
    model = service._collect_model_metrics()
    assert model.total_inferences == 2
    assert (model.successful_inferences, model.failed_inferences) == (1, 1)
    assert model.average_inference_time_ms == 20
    assert model.cache_hit_ratio == 0.5
    assert (model.batch_inferences, model.single_inferences) == (1, 1)
    assert (model.gpu_inferences, model.cpu_inferences) == (1, 1)
    service.record_prediction_accuracy(11, 10, "load", "2026-10-01T00:00:00")
    assert service.get_prediction_accuracy_stats()["mape"] == pytest.approx(10)
    assert service.check_model_drift()["drift_detected"] is False
    assert service.validate_data_quality({})["is_valid"] is True


def test_empty_and_failed_metric_probes_return_serializable_defaults(monkeypatch):
    service = monitor.MonitoringService()
    assert service._collect_api_metrics().average_response_time_ms == 0
    assert service._collect_model_metrics().cache_hit_ratio == 0
    monkeypatch.setattr(monitor.time, "time", lambda: service.start_time)
    assert service._collect_api_metrics().requests_per_second == 0
    service.api_requests["response_times"] = None
    service.model_inferences["inference_times"] = None
    assert service._collect_api_metrics().total_requests == 0
    assert service._collect_model_metrics().total_inferences == 0
    monkeypatch.setattr(monitor.psutil, "cpu_percent", Mock(side_effect=OSError("host unavailable")))
    assert service._collect_system_metrics().gpu_available is False


def _mock_host(monkeypatch, gpu_devices):
    monkeypatch.setattr(monitor.psutil, "cpu_percent", lambda interval: 25)
    monkeypatch.setattr(monitor.psutil, "virtual_memory", lambda: SimpleNamespace(
        percent=40, used=2 * 1024**3, available=6 * 1024**3))
    monkeypatch.setattr(monitor.psutil, "disk_usage", lambda path: SimpleNamespace(percent=55))
    monkeypatch.setattr(monitor.psutil, "net_io_counters", lambda: SimpleNamespace(bytes_sent=12, bytes_recv=34))
    monkeypatch.setattr(monitor.psutil, "pids", lambda: [1, 2, 3])
    monkeypatch.setitem(sys.modules, "tensorflow", SimpleNamespace(
        config=SimpleNamespace(list_physical_devices=lambda kind: gpu_devices)))


def test_host_probe_reads_cpu_memory_network_and_optional_gpu(monkeypatch):
    _mock_host(monkeypatch, [object()])
    nvml = SimpleNamespace(
        NVML_TEMPERATURE_GPU=1, nvmlInit=Mock(), nvmlShutdown=Mock(),
        nvmlDeviceGetHandleByIndex=lambda index: "gpu",
        nvmlDeviceGetMemoryInfo=lambda handle: SimpleNamespace(used=1024**2, total=4096 * 1024**2),
        nvmlDeviceGetUtilizationRates=lambda handle: SimpleNamespace(gpu=12),
        nvmlDeviceGetTemperature=lambda handle, kind: 45,
    )
    monkeypatch.setitem(sys.modules, "pynvml", nvml)
    sample = monitor.MonitoringService()._collect_system_metrics()
    assert (sample.cpu_percent, sample.memory_percent, sample.disk_usage_percent) == (25, 40, 55)
    assert sample.memory_used_gb == 2 and sample.memory_available_gb == 6
    assert (sample.network_io_bytes_sent, sample.network_io_bytes_recv, sample.process_count) == (12, 34, 3)
    assert sample.gpu_available is True
    assert (sample.gpu_memory_used_mb, sample.gpu_memory_total_mb) == (1, 4096)
    assert (sample.gpu_utilization_percent, sample.gpu_temperature_c) == (12, 45)
    nvml.nvmlShutdown.assert_called_once()
    nvml.nvmlInit.side_effect = RuntimeError("NVML missing")
    assert monitor.MonitoringService()._collect_system_metrics().gpu_memory_used_mb == 0


@pytest.mark.parametrize("tensorflow", [None, SimpleNamespace(config=SimpleNamespace(list_physical_devices=lambda kind: []))])
def test_missing_gpu_runtime_does_not_lose_host_metrics(monkeypatch, tensorflow):
    _mock_host(monkeypatch, [])
    monkeypatch.setitem(sys.modules, "tensorflow", tensorflow)
    sample = monitor.MonitoringService()._collect_system_metrics()
    assert sample.cpu_percent == 25
    assert sample.gpu_available is False


def test_alert_thresholds_and_severities():
    service = monitor.MonitoringService()
    system = replace(service._get_empty_system_metrics(), cpu_percent=95, memory_percent=95)
    api = replace(service._get_empty_api_metrics(), total_requests=10, failed_requests=1, p95_response_time_ms=35000)
    model = replace(service._get_empty_model_metrics(), cache_hit_ratio=0.1)
    service._check_alerts(system, api, model)
    alerts = {alert.metric_name: alert for alert in service.alerts_history}
    assert set(alerts) == {"cpu_percent", "memory_percent", "response_time_ms", "error_rate", "cache_hit_ratio"}
    assert all(alert.severity == 5 for alert in alerts.values())
    assert alerts["error_rate"].current_value == 10
    service.alerts_history.clear()
    service._check_alerts(replace(system, cpu_percent=80, memory_percent=20), service._get_empty_api_metrics(), replace(model, cache_hit_ratio=0.8))
    assert [(a.metric_name, a.severity) for a in service.alerts_history] == [("cpu_percent", 3)]
    assert service._create_alert("info", "state", 1, 0, "ready").severity == 1


def test_history_filters_by_time_and_metric_and_exports_prometheus():
    service = monitor.MonitoringService()
    assert service.get_current_status()["system"] is None
    assert monitor.PrometheusMetricsExporter.export_metrics(service) == ""
    old = (datetime.now() - timedelta(minutes=90)).isoformat()
    recent = datetime.now().isoformat()
    for history, sample in (
        (service.system_metrics_history, service._get_empty_system_metrics()),
        (service.api_metrics_history, service._get_empty_api_metrics()),
        (service.model_metrics_history, service._get_empty_model_metrics()),
    ):
        history.extend([replace(sample, timestamp=old), replace(sample, timestamp=recent)])
    result = service.get_metrics_history()
    assert all(len(samples) == 1 for samples in result.values())
    for kind in ("system", "api", "model"):
        assert set(service.get_metrics_history(kind)) == {kind}
    assert service.get_metrics_history("invalid") == {}
    assert service._metrics_to_dict(None) == {}
    assert service._metrics_to_dict({"key": "value"}) == {"key": "value"}
    service.alerts_history.append(service._create_alert("info", "state", 1, 0, "ready"))
    status = service.get_current_status()
    assert status["recent_alerts"][0]["message"] == "ready"
    assert status["api"]["total_requests"] == 0
    exported = monitor.PrometheusMetricsExporter.export_metrics(service)
    for metric in ("system_cpu_percent", "system_memory_percent", "api_total_requests_total", "api_response_time_ms", "model_total_inferences_total", "model_cache_hit_ratio"):
        assert f"# TYPE {metric} " in exported
    assert monitor.get_monitoring_service() is monitor.monitoring_service


def test_monitor_lifecycle_is_idempotent_and_loop_recovers(monkeypatch):
    service = monitor.MonitoringService()
    thread = Mock()
    monkeypatch.setattr(monitor.threading, "Thread", Mock(return_value=thread))
    service.start_monitoring()
    service.start_monitoring()
    thread.start.assert_called_once()
    service.stop_monitoring()
    thread.join.assert_called_once_with(timeout=5)
    service.monitoring_active = True
    service.websocket_clients = [object()]
    collect = Mock(side_effect=[RuntimeError("temporary host error"), service._get_empty_system_metrics()])
    monkeypatch.setattr(service, "_collect_system_metrics", collect)
    monkeypatch.setattr(service, "_broadcast_metrics", Mock())
    sleeps = []
    def fake_sleep(seconds):
        sleeps.append(seconds)
        if seconds == 5:
            service.monitoring_active = False
    monkeypatch.setattr(monitor.time, "sleep", fake_sleep)
    service._monitor_loop()
    assert sleeps == [10, 5]
    assert len(service.system_metrics_history) == 1
    assert len(service.api_metrics_history) == len(service.model_metrics_history) == 1
    service._broadcast_metrics.assert_called_once()


def test_broadcast_prepares_available_samples_without_breaking_on_bad_client_state(monkeypatch):
    service = monitor.MonitoringService()
    assert service._broadcast_metrics() is None
    service.websocket_clients.append(object())
    assert service._broadcast_metrics() is None
    service.system_metrics_history.append(service._get_empty_system_metrics())
    service.api_metrics_history.append(service._get_empty_api_metrics())
    service.model_metrics_history.append(service._get_empty_model_metrics())
    service.alerts_history.append(service._create_alert("info", "state", 1, 0, "ready"))
    assert service._broadcast_metrics() is None
    monkeypatch.setattr(service, "_metrics_to_dict", Mock(side_effect=ValueError("malformed snapshot")))
    assert service._broadcast_metrics() is None
