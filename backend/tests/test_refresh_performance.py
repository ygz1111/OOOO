"""Refresh regressions: offline, without downloading data or loading models."""
import asyncio
from unittest.mock import Mock

import pandas as pd
import pytest

from realtime_api.openmeteo_client import OpenMeteoClient, DataQualityReport


def weather_client(monkeypatch):
    client = OpenMeteoClient(locations=[{"name": "Boston", "lat": 42, "lon": -71}])
    fresh = pd.DataFrame({"timestamp": [pd.Timestamp("2026-09-21")], "value": [2]})
    report = DataQualityReport(location="Boston", is_valid=True)
    fetch = Mock(return_value={"new": True})
    monkeypatch.setattr(client, "_fetch_single_location", fetch)
    monkeypatch.setattr(client, "_parse_response", lambda *args: (fresh, report))
    monkeypatch.setattr(client, "_validate_and_clean", lambda df, report: (df, report))
    monkeypatch.setattr(client, "_print_summary", lambda *args: None)
    client._cached_df = fresh.assign(value=1)
    client._cached_reports = {"Boston": report}
    return client, fetch


@pytest.mark.parametrize("force,age,expected_calls", [(False, 10, 0), (False, 1000, 1), (True, 10, 1)])
def test_weather_rechecks_ttl_inside_singleflight(monkeypatch, force, age, expected_calls):
    client, fetch = weather_client(monkeypatch)
    monkeypatch.setattr("realtime_api.openmeteo_client.time.time", lambda: 2000.0)
    client._cache_timestamp = 2000 - age
    result, _ = client.fetch_weather_data(force_refresh=force)
    assert fetch.call_count == expected_calls
    assert result.iloc[0]["value"] == (2 if expected_calls else 1)
    assert not client._fetching


def test_failed_weather_refresh_does_not_present_expired_cache_as_fresh(monkeypatch):
    client, fetch = weather_client(monkeypatch)
    fetch.return_value = None
    client._cache_timestamp = 0
    result, _ = client.fetch_weather_data()
    assert result.empty
    assert client._cache_timestamp == 0
    assert not client._fetching


def test_failed_weather_owner_releases_singleflight_and_next_request_recovers(monkeypatch):
    client = OpenMeteoClient(locations=[{"name": "Boston", "lat": 42, "lon": -71}],
                             rate_limit_interval=0)
    clock = [2000.0]
    monkeypatch.setattr("realtime_api.openmeteo_client.time.time", lambda: clock[0])
    old = pd.DataFrame({"timestamp": [pd.Timestamp("2026-01-30")], "value": [1.]})
    client._cached_df = old.copy()
    client._cached_reports = {"Boston": DataQualityReport(location="Boston", is_valid=True)}
    client._cache_timestamp = 1000.0
    hourly = {"time": pd.date_range("2026-01-31", periods=24, freq="h").strftime("%Y-%m-%dT%H:%M").tolist(),
              "temperature_2m": [20.] * 24, "dew_point_2m": [12.] * 24,
              "relative_humidity_2m": [60.] * 24, "wind_speed_10m": [3.] * 24,
              "cloud_cover": [30.] * 24, "shortwave_radiation": [100.] * 24}
    fetch = Mock(side_effect=[None, {"timezone": "America/New_York", "hourly": hourly}])
    monkeypatch.setattr(client, "_fetch_single_location", fetch)

    failed, reports = client.fetch_weather_data()

    assert failed.empty and not reports["Boston"].is_valid
    assert client._cache_timestamp == 1000.0
    pd.testing.assert_frame_equal(client._cached_df, old)
    assert not client._fetching and client._last_fetch_failed

    clock[0] = 2100.0
    recovered, reports = client.fetch_weather_data()

    assert len(recovered) == 24 and reports["Boston"].is_valid
    assert recovered["temperature_2m"].tolist() == [20.] * 24
    assert client._cache_timestamp == 2100.0
    assert not client._fetching and not client._last_fetch_failed
    assert fetch.call_count == 2
    cached, _ = client.fetch_weather_data()
    pd.testing.assert_frame_equal(cached, recovered)
    assert fetch.call_count == 2


def test_weather_concurrent_misses_share_one_download(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    client, fetch = weather_client(monkeypatch)
    started, release = threading.Event(), threading.Event()
    def download(*args):
        started.set()
        assert release.wait(5)
        return {"new": True}
    fetch.side_effect = download
    client._cache_timestamp = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(client.fetch_weather_data) for _ in range(3)]
        assert started.wait(5)
        release.set()
        assert all(future.result()[0].iloc[0]["value"] == 2 for future in futures)
    assert fetch.call_count == 1


def test_backtest_reuses_unchanged_windows_without_sharing_mutable_results(monkeypatch):
    from realtime_api.services import prediction_insight as insight
    service = Mock(spec=["predict_features"])
    service.predict_features.return_value = {"hourly": [{
        "timestamp": "2026-09-21T09:00:00", "load_forecast_mw": 10000,
    }]}
    monkeypatch.setattr(insight.services, "tf_load_price_service", service)
    monkeypatch.setattr(insight, "_TF_BACKTEST_CACHE", {"windows": None, "service": None, "pairs": None})
    windows = [{"past": [], "future": [], "target_time": "2026-09-21T09:00:00", "actual_load_mw": 9900}]
    first = insight._run_tf_historical_backtest(windows)
    first[0]["historical_actual"] = 0
    second = insight._run_tf_historical_backtest(windows)
    assert service.predict_features.call_count == 1
    assert second[0]["historical_actual"] == 9900
    insight._run_tf_historical_backtest(list(windows))
    assert service.predict_features.call_count == 1
    windows[0]["actual_load_mw"] = 9800
    revised = insight._run_tf_historical_backtest(windows)
    assert service.predict_features.call_count == 2
    assert revised[0]["historical_actual"] == 9800


@pytest.mark.asyncio
async def test_overview_singleflight_and_completion_based_expiry(monkeypatch):
    from realtime_api.services import prediction_insight as insight
    clock = [100.0]
    hour = [pd.Timestamp("2026-09-21 09:00")]
    calls = []
    async def compute():
        calls.append(1)
        await asyncio.sleep(0)
        clock[0] += 80
        return {"result": len(calls)}
    monkeypatch.setattr(insight, "_OVERVIEW_CACHE", {"data": None, "timestamp": 0})
    monkeypatch.setattr(insight, "_overview_inflight", None)
    monkeypatch.setattr(insight, "_generate_load_overview_impl", compute)
    monkeypatch.setattr(insight, "_eastern_now_hour", lambda: hour[0])
    monkeypatch.setattr(insight.time, "time", lambda: clock[0])
    results = await asyncio.gather(*(insight.generate_load_overview() for _ in range(3)))
    assert len(calls) == 1
    assert all(result == {"result": 1} for result in results)
    assert insight._OVERVIEW_CACHE["timestamp"] == 180
    assert await insight.generate_load_overview() == {"result": 1}
    hour[0] += pd.Timedelta(hours=1)
    assert await insight.generate_load_overview() == {"result": 2}
    assert await insight.generate_load_overview(force_refresh=True) == {"result": 3}


@pytest.mark.asyncio
async def test_overview_cache_does_not_extend_original_generation_expiry(monkeypatch):
    from realtime_api.services import prediction_insight as insight, live_forecast as live
    import time
    now = pd.Timestamp("2026-10-01 04:30")
    hour = now.floor("h")
    old = {"data": {"input_quality": {"components": {"load": {
        "status": "cached", "generated_at": str(now - pd.Timedelta(hours=6, seconds=1))}}}}}
    monkeypatch.setattr(live, "eastern_now", lambda: now.to_pydatetime())
    monkeypatch.setattr(insight, "_eastern_now_hour", lambda: hour)
    monkeypatch.setattr(insight, "_OVERVIEW_CACHE", {"data": old, "timestamp": time.time(), "hour": hour})
    monkeypatch.setattr(insight, "_overview_inflight", None)
    async def compute():
        return {"refreshed": True}
    monkeypatch.setattr(insight, "_generate_load_overview_impl", compute)
    assert await insight.generate_load_overview() == {"refreshed": True}
