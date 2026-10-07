"""Overview regressions with isolated clock/model/snapshot inputs; no live I/O."""
from types import SimpleNamespace

import pandas as pd
import pytest

from realtime_api.services import live_forecast as live
from realtime_api.services import prediction_insight as insight
from tests.test_day_backtest import stubs  # Reuse the existing isolated date/DB/weather fixture.


def first_step_service(calls):
    def predict(past, future):
        assert len(future) == 1
        target = pd.Timestamp(future[0]["ts_local"])
        assert pd.Timestamp(past[-1]["ts_local"]) == target - pd.Timedelta(hours=1)
        calls.append(target)
        return {"hourly": [{"timestamp": str(target), "load_forecast_mw": 11000.0}]}

    def full_horizon(*args):
        raise AssertionError("First-step replay must not require unpublished later hours")

    return SimpleNamespace(predict_load_first_step_features=predict, predict_task_features=full_horizon)


def replay_window(target, actual=10500.0):
    return {
        "target_time": str(target), "actual_load_mw": actual,
        "past": [{"ts_local": target - pd.Timedelta(hours=1), "RT_Demand": 10400.0}],
        "future": [{"ts_local": target, "DA_Demand": 10900.0}],
    }


def test_first_step_replay_cache_reuses_inputs_and_rechecks_revised_actuals(monkeypatch):
    calls = []
    monkeypatch.setattr(insight.services, "tf_load_price_service", first_step_service(calls))
    monkeypatch.setattr(insight, "_TF_BACKTEST_CACHE", {})
    target = pd.Timestamp("2026-10-04 02:00")
    windows = [replay_window(target)]
    initial = insight._run_tf_historical_backtest(windows)
    initial[0]["historical_actual"] = 0
    cached = insight._run_tf_historical_backtest(windows)
    assert cached[0]["historical_actual"] == 10500.0 and len(calls) == 1
    windows[0]["actual_load_mw"] = 10600.0
    revised = insight._run_tf_historical_backtest(windows)
    assert revised[0]["historical_actual"] == 10600.0 and len(calls) == 2


@pytest.mark.asyncio
async def test_overview_replays_new_observed_hours_from_one_to_five_without_restart(monkeypatch):
    hour = [pd.Timestamp("2026-10-04 01:00")]
    seconds = [100.0]
    calls = []
    sources = []
    monkeypatch.setattr(insight.services, "tf_load_price_service", first_step_service(calls))
    monkeypatch.setattr(insight, "get_engine_config", lambda: {"inference_mode": "live"})
    monkeypatch.setattr(insight, "_TF_BACKTEST_CACHE", {})
    monkeypatch.setattr(insight, "_OVERVIEW_CACHE", {"data": None, "timestamp": 0})
    monkeypatch.setattr(insight, "_overview_inflight", None)
    monkeypatch.setattr(insight, "_eastern_now_hour", lambda: hour[0])
    monkeypatch.setattr(insight.time, "time", lambda: seconds[0])

    async def snapshot():
        sources.append(hour[0])
        targets = pd.date_range(hour[0] - pd.Timedelta(hours=23), hour[0], freq="h")
        return {
            "current": {"time": str(hour[0]), "actual_load_mw": 10500.0},
            "history": [{"target_time": str(t), "historical_actual": 10500.0,
                         "historical_forecast": None} for t in targets],
            "load_backtest": [replay_window(t) for t in targets],
        }

    monkeypatch.setattr(live, "request_live_snapshot", snapshot)
    monkeypatch.setattr(live, "snapshot_response", lambda snap: SimpleNamespace(
        status="success", timestamp=str(hour[0]), predictions=[], input_quality={},
        data_source="isolated-test", engine="tf_split_v1", pv_engine="tf_pv_v2"))
    for ending_hour in range(1, 6):
        hour[0] = pd.Timestamp(f"2026-10-04 {ending_hour:02d}:00")
        seconds[0] += 1  # Cache TTL has not elapsed: the ET hour must invalidate it.
        overview = (await insight.generate_load_overview())["data"]
        pairs = overview["historical"]["pairs"]
        assert len(pairs) == 24
        assert pd.Timestamp(pairs[-1]["target_time"]) == hour[0]
        assert all(p["historical_forecast"] is not None for p in pairs)
        assert overview["historical"]["metrics"]["mae_mw"] == 500.0
        assert "事后天气" in overview["historical"]["note"]
        assert (await insight.generate_load_overview())["data"] == overview
    assert len(sources) == 5
    assert pd.Timestamp("2026-10-04 02:00") in calls
    assert pd.Timestamp("2026-10-04 03:00") in calls
    assert pd.Timestamp("2026-10-04 05:00") in calls


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_missing_replay_is_explained_and_not_counted_as_real_error(monkeypatch, failed):
    target = pd.Timestamp("2026-10-04 05:00")
    snapshot = {"current": {}, "history": [{"target_time": str(target),
        "historical_actual": 10500.0, "historical_forecast": None}], "load_backtest": []}
    async def get_snapshot():
        return snapshot
    def replay(windows):
        if failed:
            raise RuntimeError("isolated replay failure")
        return []
    monkeypatch.setattr(insight, "get_engine_config", lambda: {"inference_mode": "live"})
    monkeypatch.setattr(live, "request_live_snapshot", get_snapshot)
    monkeypatch.setattr(insight, "_run_tf_historical_backtest", replay)
    monkeypatch.setattr(live, "snapshot_response", lambda snap: SimpleNamespace(
        status="success", timestamp=str(target), predictions=[], input_quality={},
        data_source="isolated-test", engine="tf_split_v1", pv_engine="tf_pv_v2"))
    historical = (await insight._generate_tf_overview_impl())["data"]["historical"]
    assert historical["metrics"] is None
    assert historical["pairs"][0]["historical_forecast"] is None
    assert "1个小时暂缺回测结果" in historical["note"]
    assert ("计算暂时失败" if failed else "资料更新中") in historical["note"]


@pytest.mark.asyncio
async def test_date_replay_selects_first_step_and_does_not_require_next_day_weather(stubs, monkeypatch):
    requested = []
    day = stubs["day"]
    start = pd.Timestamp(day)
    targets = pd.date_range(start, periods=24, freq="h")
    calls = []
    monkeypatch.setattr(insight.services, "tf_load_price_service", first_step_service(calls))

    def windows(target_day, weather, future_hours=24):
        assert target_day == day and future_hours == 1
        return [replay_window(t, actual=10000.0) for t in targets]

    async def weather(weather_start, weather_end):
        requested.append(pd.Timestamp(weather_end))
        return pd.DataFrame({"timestamp": targets, "temperature_2m": 20.0,
            "wind_speed_10m": 3.0, "cloud_cover": 30.0, "shortwave_radiation": 300.0})

    monkeypatch.setattr(insight.services, "tf_realtime_feature_provider", SimpleNamespace(build_day_backtest=windows))
    monkeypatch.setattr(insight, "_load_historical_weather", weather)
    result = await insight.generate_day_backtest(day)
    assert len(result["pairs"]) == 24 and len(calls) == 24
    assert pd.Timestamp(result["pairs"][-1]["target_time"]) == targets[-1]
    assert requested == [targets[-1]]
    assert result["metrics"]["mae_mw"] == 1000.0
