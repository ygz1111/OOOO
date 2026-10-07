"""Health degradation, optional dependencies and recovery without live services."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from realtime_api import health_check as health
from realtime_api.services import container


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,status", [({"status": "healthy", "pool_size": 2}, "healthy"), ({"status": "unhealthy", "error": "connection lost"}, "unhealthy"), ({}, "unhealthy")])
async def test_database_status_reflects_probe_result(monkeypatch, payload, status):
    monkeypatch.setattr(health.db_manager, "health_check", AsyncMock(return_value=payload))
    result = await health.HealthCheckService().check_database_health()
    assert result.name == "database" and result.status == status
    assert result.details == payload
    assert result.response_time_ms >= 0
    assert result.last_check


@pytest.mark.asyncio
async def test_database_failure_can_recover_on_next_probe(monkeypatch):
    monkeypatch.setattr(health.db_manager, "health_check", AsyncMock(side_effect=[OSError("offline"), {"status": "healthy"}]))
    service = health.HealthCheckService()
    failed = await service.check_database_health()
    assert failed.status == "unhealthy" and failed.details["error"] == "offline"
    assert (await service.check_database_health()).status == "healthy"


@pytest.mark.asyncio
@pytest.mark.parametrize("ping", [True, False])
async def test_redis_probe_retains_optional_status_and_uses_bounded_resp2(monkeypatch, ping):
    captured = {}
    def redis_client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(ping=lambda: ping, info=lambda: {"used_memory": 2 * 1024**2, "uptime_in_seconds": 7200, "connected_clients": 3})
    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=redis_client))
    result = await health.HealthCheckService().check_redis_health()
    assert result.status == ("healthy" if ping else "degraded")
    assert captured["protocol"] == 2
    assert captured["socket_connect_timeout"] == captured["socket_timeout"] == 2
    if ping:
        assert result.details == {"connected_clients": 3, "used_memory_mb": 2, "uptime_hours": 2}
    else:
        assert result.details is None


@pytest.mark.asyncio
async def test_redis_timeout_and_import_failure_keep_service_available(monkeypatch):
    async def timed_out(*args, **kwargs):
        raise asyncio.TimeoutError
    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=Mock()))
    monkeypatch.setattr(health.asyncio, "to_thread", lambda fn: None)
    monkeypatch.setattr(health.asyncio, "wait_for", timed_out)
    timeout = await health.HealthCheckService().check_redis_health()
    assert timeout.status == "degraded"
    assert timeout.details["error"] == "redis_health_check_timeout"
    monkeypatch.setitem(sys.modules, "redis", None)
    missing = await health.HealthCheckService().check_redis_health()
    assert missing.status == "degraded"
    assert missing.details["error"]


def test_model_health_distinguishes_absent_unready_partial_and_ready(monkeypatch):
    service = health.HealthCheckService()
    assert service.check_model_service_health(None).status == "unhealthy"
    assert service.check_model_service_health(SimpleNamespace(is_ready=False)).status == "unhealthy"
    monkeypatch.setattr(container, "active_model_runtime_stats", lambda: {"device": "CPU", "model_details": [{"id": "load", "loaded": True}, {"id": "price", "loaded": False}, {"id": "solar", "loaded": True}]})
    result = service.check_model_service_health(SimpleNamespace(is_ready=lambda: True))
    assert result.status == "degraded"
    assert result.details["models_loaded"] == 2 and result.details["total_models"] == 3
    monkeypatch.setattr(container, "active_model_runtime_stats", lambda: {"device": "CPU", "model_details": [{"loaded": True}, {"id": "price", "loaded": True}]})
    ready = service.check_model_service_health(SimpleNamespace(is_ready=True))
    assert ready.status == "healthy"
    assert ready.details["device"] == "CPU"
    assert "model_1" in ready.details["model_details"]


def test_model_health_fallback_and_failure_are_explicit(monkeypatch):
    service = health.HealthCheckService()
    monkeypatch.setattr(container, "active_model_runtime_stats", Mock(side_effect=OSError("stats unavailable")))
    inference = SimpleNamespace(is_ready=True, get_model_info=lambda: {"load": {"loaded": True}}, device="cpu")
    ready = service.check_model_service_health(inference)
    assert ready.status == "healthy" and ready.details["device"] == "cpu"
    inference.get_model_info = Mock(side_effect=RuntimeError("bad model info"))
    failed = service.check_model_service_health(inference)
    assert failed.status == "unhealthy"
    assert failed.details["error"] == "bad model info"


@pytest.mark.parametrize("cpu,memory,status", [(20, 30, "healthy"), (71, 30, "degraded"), (20, 81, "degraded"), (91, 30, "unhealthy"), (20, 91, "unhealthy")])
def test_host_resources_thresholds(monkeypatch, cpu, memory, status):
    monkeypatch.setattr(health.psutil, "cpu_percent", lambda interval: cpu)
    monkeypatch.setattr(health.psutil, "virtual_memory", lambda: SimpleNamespace(percent=memory, used=2 * 1024**3, total=8 * 1024**3))
    monkeypatch.setattr(health.psutil, "disk_usage", lambda path: SimpleNamespace(percent=25))
    monkeypatch.setattr(health.HealthCheckService, "_tensorflow_gpus_count", staticmethod(lambda: 0))
    result = health.HealthCheckService().check_system_resources()
    assert result.status == status
    assert result.details["memory_used_gb"] == 2 and result.details["memory_total_gb"] == 8
    assert result.details["disk_percent"] == 25
    assert result.details["gpu_available"] is False


def test_host_probe_failure_is_unhealthy(monkeypatch):
    monkeypatch.setattr(health.psutil, "cpu_percent", Mock(side_effect=OSError("resource probe failed")))
    result = health.HealthCheckService().check_system_resources()
    assert result.status == "unhealthy"
    assert result.details["error"] == "resource probe failed"


def test_gpu_health_reports_available_devices_and_broken_runtime(monkeypatch):
    gpu = SimpleNamespace(name="/physical_device:GPU:0", device_type="GPU")
    monkeypatch.setitem(sys.modules, "tensorflow", SimpleNamespace(config=SimpleNamespace(list_physical_devices=lambda kind: [gpu])))
    service = health.HealthCheckService()
    available = service.check_gpu_health()
    assert available.status == "healthy"
    assert available.details["device_count"] == 1
    assert available.details["devices"][0]["name"] == gpu.name
    assert service._tensorflow_gpus_count() == 1
    monkeypatch.setitem(sys.modules, "tensorflow", None)
    assert service.check_gpu_health().status == "degraded"
    assert service._tensorflow_gpus_count() == 0
    monkeypatch.setitem(sys.modules, "tensorflow", SimpleNamespace(config=SimpleNamespace(list_physical_devices=lambda kind: [object()])))
    broken = service.check_gpu_health()
    assert broken.status == "unhealthy" and broken.details["error"]


def _component(name, status):
    return health.ComponentHealth(name=name, status=status, message="probe")


@pytest.mark.asyncio
@pytest.mark.parametrize("database,redis,overall", [("healthy", "healthy", "healthy"), ("healthy", "degraded", "degraded"), ("unhealthy", "degraded", "unhealthy")])
async def test_comprehensive_health_prioritizes_failures(monkeypatch, database, redis, overall):
    service = health.HealthCheckService()
    monkeypatch.setattr(service, "check_database_health", AsyncMock(return_value=_component("database", database)))
    monkeypatch.setattr(service, "check_redis_health", AsyncMock(return_value=_component("redis", redis)))
    for method, name in (("check_model_service_health", "model"), ("check_system_resources", "resources"), ("check_gpu_health", "gpu")):
        monkeypatch.setattr(service, method, Mock(return_value=_component(name, "healthy")))
    result = await service.comprehensive_health_check()
    assert result["status"] == overall
    assert len(result["components"]) == 5
    assert result["response_time_ms"] >= 0 and result["uptime_seconds"] >= 0
    assert result["service"] and result["version"]


@pytest.mark.asyncio
async def test_comprehensive_health_captures_component_exception_and_global_timeout(monkeypatch):
    service = health.HealthCheckService()
    monkeypatch.setattr(service, "check_database_health", AsyncMock(side_effect=OSError("unexpected probe crash")))
    monkeypatch.setattr(service, "check_redis_health", AsyncMock(return_value=_component("redis", "healthy")))
    for method in ("check_model_service_health", "check_system_resources", "check_gpu_health"):
        monkeypatch.setattr(service, method, Mock(return_value=_component(method, "healthy")))
    result = await service.comprehensive_health_check()
    assert result["status"] == "unhealthy"
    assert result["components"][0]["name"] == "unknown"
    assert "unexpected probe crash" in result["components"][0]["message"]
    async def timeout(awaitable, timeout):
        awaitable.cancel()
        try:
            await awaitable
        except asyncio.CancelledError:
            pass
        raise asyncio.TimeoutError("overall health timeout")
    monkeypatch.setattr(health.asyncio, "wait_for", timeout)
    result = await service.comprehensive_health_check()
    assert result["status"] == "unhealthy" and result["error"] == "overall health timeout"
    assert health.get_health_check_service() is health.health_check_service
