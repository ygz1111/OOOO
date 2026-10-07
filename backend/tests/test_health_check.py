"""Regression tests for optional runtime dependency health checks."""

import sys
from types import SimpleNamespace

import pytest

from realtime_api.health_check import HealthCheckService


@pytest.mark.asyncio
async def test_redis_health_uses_resp2_for_legacy_windows_server(monkeypatch):
    captured = {}

    class FakeRedisClient:
        def ping(self):
            return True

        def info(self):
            return {
                "connected_clients": 1,
                "used_memory": 1024,
                "uptime_in_seconds": 3600,
            }

    def create_client(**kwargs):
        captured.update(kwargs)
        return FakeRedisClient()

    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=create_client))

    result = await HealthCheckService().check_redis_health()

    assert result.status == "healthy"
    assert captured["protocol"] == 2


def test_missing_optional_gpu_keeps_cpu_inference_healthy(monkeypatch):
    fake_tensorflow = SimpleNamespace(
        config=SimpleNamespace(list_physical_devices=lambda _kind: [])
    )
    monkeypatch.setitem(sys.modules, "tensorflow", fake_tensorflow)

    result = HealthCheckService().check_gpu_health()

    assert result.status == "healthy"
    assert result.details == {
        "available": False,
        "required": False,
        "reason": "cuda_not_available",
    }
