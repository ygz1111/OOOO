"""Operations must preserve shared forecast provenance and independent degradation."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from realtime_api.services import operation_situation as ops


def prediction(pv_values):
    return SimpleNamespace(timestamp="2026-09-22T07:03:00", input_quality={},
        inference_time_ms=5., data_source="iso_ne+open_meteo:zonal_he_v2",
        predictions=[SimpleNamespace(timestamp=(datetime(2026, 9, 22, 8) + timedelta(hours=i)).isoformat(),
            load_forecast_mw=1000. + i * 100, pv_estimation_mw=pv, net_load_mw=None)
            for i, pv in enumerate(pv_values)])


def test_missing_pv_keeps_load_without_invented_zeros_or_net_load():
    result = ops._summarize_prediction(prediction([None, None]))
    assert len(result["hourly"]) == 2
    assert all(row["pv_mw"] is None and row["net_load_mw"] is None for row in result["hourly"])
    assert result["peak_valley"]["peak_load_mw"] == 1100
    assert result["renewable"]["total_energy_mwh"] is None
    assert result["supply_demand"]["maximum_net_load_mw"] is None
    assert not any("新能源贡献偏低" in risk["message"] for risk in result["risks"])


def test_partial_pv_is_not_reported_as_complete_total_and_ramp_never_crosses_gap():
    result = ops._summarize_prediction(prediction([100., None, 300.]))
    assert result["renewable"]["total_energy_mwh"] is None
    assert result["renewable"]["average_share_percent"] is None
    assert result["data_scope"]["pv_coverage_hours"] == 2
    assert result["supply_demand"]["maximum_net_load_ramp_mw"] is None


def test_real_zero_pv_is_not_missing_and_original_generation_time_is_preserved():
    result = ops._summarize_prediction(prediction([0., 0.]))
    assert result["generated_at"] == "2026-09-22T07:03:00"
    assert result["renewable"]["total_energy_mwh"] == 0
    assert result["hourly"][0]["net_load_mw"] == 1000
    assert result["supply_demand"]["maximum_net_load_ramp_mw"] == 100


def test_pending_empty_prediction_has_empty_rows_and_null_metrics():
    value = prediction([])
    value.input_quality = {"refresh_in_progress": True}
    result = ops._summarize_prediction(value)
    assert result["hourly"] == []
    assert result["peak_valley"]["spread_mw"] is None
    assert result["input_quality"]["refresh_in_progress"]


@pytest.mark.asyncio
async def test_live_operations_uses_bounded_shared_request_without_extra_weather_fetch(monkeypatch):
    from realtime_api.services import live_forecast as live
    request = AsyncMock(return_value={"shared": True})
    monkeypatch.setattr(ops, "get_engine_config", lambda: {"inference_mode": "live"})
    monkeypatch.setattr(live, "request_live_snapshot", request)
    monkeypatch.setattr(live, "snapshot_response", lambda snapshot: prediction([None]))
    result = await ops._build_operation_situation_impl()
    request.assert_awaited_once()
    assert result["hourly"][0]["load_mw"] == 1000.


@pytest.mark.asyncio
async def test_operations_cache_expires_at_hour_boundary_and_pending_retries(monkeypatch):
    hour = [datetime(2026, 9, 22, 7)]
    calls = AsyncMock(return_value={"input_quality": {}})
    monkeypatch.setattr(ops, "_SITUATION_CACHE", {"data": None, "timestamp": 0})
    monkeypatch.setattr(ops, "_situation_inflight", None)
    monkeypatch.setattr(ops, "eastern_now_hour", lambda: hour[0])
    monkeypatch.setattr(ops, "_build_operation_situation_impl", calls)
    await ops.build_operation_situation()
    await ops.build_operation_situation()
    assert calls.await_count == 1
    hour[0] += timedelta(hours=1)
    calls.return_value = {"input_quality": {"refresh_in_progress": True}}
    await ops.build_operation_situation()
    await ops.build_operation_situation()
    assert calls.await_count == 3
