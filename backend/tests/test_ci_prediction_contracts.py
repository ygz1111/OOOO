"""Offline checks for historical inputs, model contracts and overview recovery."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pandas as pd
import pytest
import requests

from realtime_api.services import prediction_insight as insight
from realtime_api.tf_load_price_service import TFLoadPriceService, FrozenScaler
from models.tensorflow_load import tf_v2_models as model_contract


@pytest.fixture
def isolated_archive(monkeypatch):
    monkeypatch.setattr(insight, "_ARCHIVE_CACHE", {"key": None, "data": None, "timestamp": 0})
    monkeypatch.setattr(insight, "_ARCHIVE_REQUEST_INTERVAL", 0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    config = SimpleNamespace(get_weather_locations=lambda: [{"name": "Boston", "lat": 42, "lon": -71}])
    monkeypatch.setattr("realtime_api.config_manager.get_config", lambda: config)


def archive_reply(code=200):
    reply = Mock(status_code=code)
    reply.json.return_value = {"hourly": {"time": ["2026-06-01T00:00", "2026-06-01T01:00"],
                                         "temperature_2m": [12, 13]}}
    if code >= 400:
        reply.raise_for_status.side_effect = requests.HTTPError(str(code))
    return reply


def test_archive_cache_preserves_same_range_and_refetches_different_range(monkeypatch, isolated_archive):
    fetch = Mock(return_value=archive_reply())
    monkeypatch.setattr(requests, "get", fetch)
    start, end = datetime(2026, 6, 1), datetime(2026, 6, 2)
    first = insight._fetch_archive_weather(start, end)
    pd.testing.assert_frame_equal(first, insight._fetch_archive_weather(start, end))
    assert fetch.call_count == 1
    assert first.temperature_2m.tolist() == [12, 13]
    assert first.location.tolist() == ["Boston", "Boston"]
    assert first.surface_pressure.isna().all()
    assert fetch.call_args.kwargs["params"]["timezone"] == "America/New_York"
    insight._fetch_archive_weather(start, end + timedelta(days=1))
    assert fetch.call_count == 2


@pytest.mark.parametrize("failure", [archive_reply(429), requests.Timeout("offline")])
def test_archive_retries_then_recovers(monkeypatch, isolated_archive, failure):
    fetch = Mock(side_effect=[failure, archive_reply()])
    monkeypatch.setattr(requests, "get", fetch)
    frame = insight._fetch_archive_weather(datetime(2026, 6, 1), datetime(2026, 6, 1))
    assert fetch.call_count == 2 and len(frame) == 2


def test_archive_persistent_failure_returns_empty_input(monkeypatch, isolated_archive):
    fetch = Mock(side_effect=requests.Timeout("offline"))
    monkeypatch.setattr(requests, "get", fetch)
    assert insight._fetch_archive_weather(datetime(2026, 6, 1), datetime(2026, 6, 1)).empty
    assert fetch.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("archive_ok,forecast_ok", [(True, True), (True, False), (False, True), (False, False)])
async def test_weather_source_priority_and_failure_fallback(monkeypatch, archive_ok, forecast_ok):
    start, end = datetime(2026, 6, 1), datetime(2026, 6, 1, 2)
    monkeypatch.setattr(insight, "_eastern_now_hour", lambda: datetime(2026, 6, 2))
    archive = Mock(return_value=pd.DataFrame({"timestamp": [start], "location": ["Boston"], "temperature_2m": [12]}))
    forecast = Mock(return_value=(pd.DataFrame({"timestamp": [start, end, end + timedelta(hours=1)],
                                              "location": ["Boston"] * 3, "temperature_2m": [90, 14, 99]}), None))
    if not archive_ok:
        archive.side_effect = requests.Timeout("archive offline")
    if not forecast_ok:
        forecast.side_effect = requests.Timeout("forecast offline")
    monkeypatch.setattr(insight, "_fetch_archive_weather", archive)
    monkeypatch.setattr(insight, "_get_openmeteo_client", lambda: SimpleNamespace(fetch_weather_data=forecast))
    frame = await insight._load_historical_weather(start, end)
    if archive_ok or forecast_ok:
        assert frame.iloc[0].temperature_2m == (12 if archive_ok else 90)
        assert frame.timestamp.max() <= end
        assert not frame.duplicated(["timestamp", "location"]).any()
        assert len(frame) == (2 if forecast_ok else 1)
    else:
        assert frame.empty


@pytest.mark.asyncio
async def test_recent_weather_does_not_request_unarchived_day(monkeypatch):
    now = datetime(2026, 6, 2)
    monkeypatch.setattr(insight, "_eastern_now_hour", lambda: now)
    archive = Mock(side_effect=AssertionError("today has no archived weather"))
    monkeypatch.setattr(insight, "_fetch_archive_weather", archive)
    monkeypatch.setattr(insight, "_get_openmeteo_client", lambda: SimpleNamespace(fetch_weather_data=lambda: (pd.DataFrame(), None)))
    assert (await insight._load_historical_weather(now, now + timedelta(hours=1))).empty
    archive.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["complete", "gap", "empty", "no_fallback"])
async def test_historical_load_uses_actuals_before_controlled_fallback(monkeypatch, mode):
    from realtime_api.historical_load_provider import HistoricalLoadProvider
    start, end = datetime(2026, 6, 1), datetime(2026, 6, 1, 4)
    rows = [{"timestamp": start + timedelta(hours=h), "actual_load_mw": 100 + h} for h in range(5)]
    if mode == "gap":
        rows = [rows[0], rows[-1]]
    if mode in ("empty", "no_fallback"):
        rows = []
    monkeypatch.setattr(insight.ActualLoadDataCRUD, "get_actual_load_by_time_range", AsyncMock(return_value=rows))
    fallback = Mock(return_value=pd.DataFrame({"timestamp": [start], "System_Load": [55]}) if mode == "empty" else None)
    monkeypatch.setattr(HistoricalLoadProvider, "_cold_start_fallback", fallback)
    result = await insight._load_historical_load(start, end)
    if mode == "complete":
        assert result.System_Load.tolist() == [100, 101, 102, 103, 104]
        fallback.assert_not_called()
    elif mode == "gap":
        assert result.System_Load.tolist() == [100, 100, 100, 100, 104]
        fallback.assert_not_called()
    elif mode == "empty":
        assert result.System_Load.tolist() == [55]
        fallback.assert_called_once_with(end_time=end, hours=4)
    else:
        assert result.empty


def test_metrics_exclude_zero_actual_from_percentage_error_and_average_stations():
    metrics = insight._compute_metrics([2, 12], [0, 10])
    assert metrics == {"mae_mw": 2.0, "rmse_mw": 2.0, "mape": 20.0}
    assert insight._compute_metrics([1, 2], [0, 0])["mape"] is None
    start = datetime(2026, 6, 1)
    assert insight._regional_hourly_weather(None, start) == []
    weather = pd.DataFrame({"timestamp": [start] * 2, "temperature_2m": [10, 20],
                            "wind_speed_10m": [2, 4], "cloud_cover": [50, None], "shortwave_radiation": [100, 200]})
    result = insight._regional_hourly_weather(weather, start, hours=2)
    assert result[0]["temperature_2m"] == 15 and result[0]["shortwave_radiation"] == 150
    assert result[1]["target_time"] == (start + timedelta(hours=1)).isoformat()
    assert result[1]["temperature_2m"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("pv", ["available", "unavailable", "failure"])
async def test_demo_overview_keeps_other_tasks_and_marks_frozen_inputs(monkeypatch, pv):
    monkeypatch.setattr(insight, "get_engine_config", lambda: {"inference_mode": "demo"})
    load = SimpleNamespace(MODEL_NAME="test-load", predict=lambda: {
        "hourly": [{"timestamp": "2026-06-01 01:00:00", "load_forecast_mw": 100}],
        "origin": "2026-06-01 00:00:00", "anchor_actual_load_mw": 90,
        "anchor_history_actual": [{"target_time": "2026-06-01 00:00:00", "actual_load_mw": 90}],
        "data_source": "frozen_tail_demo"})
    solar = Mock(return_value={"hourly_pv_mw": [12.3]})
    if pv == "failure":
        solar.side_effect = RuntimeError("PV failed")
    monkeypatch.setattr(insight.services, "tf_load_price_service", load)
    monkeypatch.setattr(insight.services, "tf_pv_service", SimpleNamespace(predict=solar))
    monkeypatch.setattr(insight, "tf_pv_backend_active", lambda: pv != "unavailable")
    result = await insight._generate_tf_overview_impl()
    data = result["data"]
    assert data["current"]["actual_load_mw"] == 90
    assert data["historical"]["pairs"][0]["historical_forecast"] is None
    assert data["historical"]["metrics"] is None
    assert data["future"]["predictions"][0]["future_forecast"] == 100
    assert data["future"]["predictions"][0]["pv_forecast_mw"] == (12.3 if pv == "available" else None)
    assert data["data_source"] == "frozen_tail_demo"


@pytest.mark.asyncio
async def test_overview_failed_task_is_cleared_and_next_request_recovers(monkeypatch):
    monkeypatch.setattr(insight, "_OVERVIEW_CACHE", {"data": None, "timestamp": 0})
    monkeypatch.setattr(insight, "_overview_inflight", None)
    generate = AsyncMock(side_effect=[RuntimeError("provider offline"), {"status": "success", "data": {}}])
    monkeypatch.setattr(insight, "_generate_load_overview_impl", generate)
    with pytest.raises(RuntimeError, match="provider offline"):
        await insight.generate_load_overview()
    assert insight._overview_inflight is None
    recovered = await insight.generate_load_overview()
    assert recovered["status"] == "success" and generate.await_count == 2
    assert insight._OVERVIEW_CACHE["data"] == recovered


@pytest.mark.asyncio
async def test_demo_overview_requires_ready_load_model(monkeypatch):
    monkeypatch.setattr(insight, "get_engine_config", lambda: {"inference_mode": "demo"})
    monkeypatch.setattr(insight, "tf_load_backend_active", lambda: False)
    with pytest.raises(RuntimeError, match="未就绪"):
        await insight._generate_load_overview_impl()


@pytest.fixture
def frozen_model():
    """Pure model stub; no weight or scaler files are changed or trained."""
    service = TFLoadPriceService()
    service._loaded = True
    service._frame = pd.DataFrame(1.0, index=range(450), columns=list(dict.fromkeys(model_contract.PAST_COLS + model_contract.FUT_COLS)))
    service._frame["ts_local"] = pd.date_range("2026-06-01", periods=450, freq="h")
    service._origin_ts_local = service._frame.ts_local.iloc[192]
    service._sp = FrozenScaler({"cols": model_contract.PAST_COLS, "mean": [0] * len(model_contract.PAST_COLS), "scale": [1] * len(model_contract.PAST_COLS)})
    service._sf = FrozenScaler({"cols": model_contract.FUT_COLS, "mean": [0] * len(model_contract.FUT_COLS), "scale": [1] * len(model_contract.FUT_COLS)})
    service._sl = FrozenScaler({"cols": ["load"], "mean": [10], "scale": [1]})
    service._sy = FrozenScaler({"cols": ["price"], "mean": [0], "scale": [1]})
    service._model = Mock()
    service._model.predict.return_value = {"load": np.zeros((1, 24, 1)), "price": np.log1p(np.tile([0, 1, 2], (1, 24, 1)))}
    return service


def test_frozen_demo_and_price_backtest_have_aligned_labels_and_error_units(frozen_model):
    result = frozen_model.predict()
    assert result["data_source"] == "frozen_tail_demo" and len(result["hourly"]) == 24
    assert result["hourly"][0]["timestamp"] == "2026-06-09 01:00:00"
    assert result["anchor_actual_load_mw"] == 1.0 and len(result["anchor_history_actual"]) == 24
    dates = frozen_model.price_backtest()
    assert dates["available_date_range"] == {"earliest": "2026-06-08", "latest": "2026-06-18"}
    backtest = frozen_model.price_backtest("2026-06-09")
    assert len(backtest["points"]) == 24
    assert backtest["points"][0]["timestamp"] == result["hourly"][0]["timestamp"]
    assert backtest["data_source"] == "frozen_historical_backtest"
    assert backtest["metrics"]["mae_usd"] == 0 and backtest["metrics"]["p10_p90_coverage"] == 100
    assert backtest["metrics"]["count"] == 24
    frozen_model._frame["RT_LMP"] = 0
    assert frozen_model.price_backtest("2026-06-09")["metrics"]["mape_pct"] is None


@pytest.mark.parametrize("mode,expected", [("unloaded", "未加载"), ("missing_lmp", "RT_LMP"),
                                          ("too_short", "行数不足"), ("no_midnight", "整日"),
                                          ("outside", "不可用"), ("missing_actual", "缺失值")])
def test_price_backtest_rejects_invalid_or_missing_inputs(frozen_model, mode, expected):
    if mode == "unloaded":
        frozen_model._loaded = False
    elif mode == "missing_lmp":
        frozen_model._frame = frozen_model._frame.drop(columns="RT_LMP")
    elif mode == "too_short":
        frozen_model._frame = frozen_model._frame.iloc[:50]
    elif mode == "no_midnight":
        frozen_model._frame["ts_local"] += pd.Timedelta(minutes=30)
        frozen_model._frame = frozen_model._frame[frozen_model._frame.ts_local.dt.hour != 0].reset_index(drop=True)
    elif mode == "missing_actual":
        frozen_model._frame.loc[193, "RT_LMP"] = np.nan
    day = "2020-01-01" if mode == "outside" else "2026-06-09"
    with pytest.raises((RuntimeError, ValueError), match=expected):
        frozen_model.price_backtest(day)


@pytest.mark.parametrize("mode,expected", [("missing", "必须包含"), ("parse", "无法解析"),
                                          ("duplicate", "严格升序"), ("reverse", "严格升序")])
def test_model_timestamps_reject_invalid_order(mode, expected):
    times = ["2026-06-01 00:00", "2026-06-01 01:00"]
    frame = pd.DataFrame({"timestamp": times})
    if mode == "missing":
        frame = pd.DataFrame({"value": [1, 2]})
    elif mode == "parse":
        frame.iloc[1, 0] = "invalid"
    elif mode == "duplicate":
        frame.iloc[1, 0] = times[0]
    else:
        frame = frame.iloc[::-1]
    with pytest.raises(ValueError, match=expected):
        TFLoadPriceService._timestamps(frame, 2, "input")


@pytest.mark.parametrize("mode,expected", [("past_shape", "过去输入 Shape"), ("future_shape", "未来输入 Shape"),
                                          ("output_shape", "输出 Shape"), ("nonfinite", "NaN/Inf")])
def test_model_rejects_invalid_input_and_output_shapes(frozen_model, mode, expected):
    past = np.ones((168, len(model_contract.PAST_COLS)))
    future = np.ones((24, len(model_contract.FUT_COLS)))
    if mode == "past_shape":
        past = past[:2]
    elif mode == "future_shape":
        future = future[:2]
    elif mode == "output_shape":
        frozen_model._model.predict.return_value["load"] = np.zeros((1, 1, 1))
    else:
        frozen_model._model.predict.return_value["price"][0, 0, 0] = np.inf
    with pytest.raises((ValueError, RuntimeError), match=expected):
        frozen_model._predict_matrices(past, future, [pd.Timestamp("2026-06-01")], origin=pd.Timestamp("2026-05-31"), data_source="test")


def test_demo_feature_sensitivity_reports_all_groups_without_modifying_input(frozen_model):
    before = frozen_model._frame.copy(deep=True)
    result = frozen_model.calculate_demo_feature_sensitivity()
    assert len(result) == 4
    assert {r["feature_group"] for r in result} == {"负荷与需求", "电价", "气象", "时间与日历"}
    assert all(r["mean_absolute_impact_mw"] == 0 and r["feature_count"] > 0 for r in result)
    pd.testing.assert_frame_equal(frozen_model._frame, before)
    frozen_model.release()
    assert not frozen_model.is_ready and frozen_model._model is None
    with pytest.raises(RuntimeError, match="未加载"):
        frozen_model.calculate_demo_feature_sensitivity()
    with pytest.raises(RuntimeError, match="未加载"):
        frozen_model.predict()
    with pytest.raises(RuntimeError, match="未加载"):
        frozen_model.predict_features([], [])


def test_demo_predict_rejects_outside_or_incomplete_anchor(frozen_model):
    with pytest.raises(ValueError, match="不在尾部"):
        frozen_model.predict("2020-01-01")
    with pytest.raises(ValueError, match="距尾部不足"):
        frozen_model.predict(str(frozen_model._frame.ts_local.iloc[1]))
    with pytest.raises(ValueError, match="缺少训练特征"):
        frozen_model._feature_matrix(pd.DataFrame({"a": [1]}), ["b"], 1, "test")
    with pytest.raises(ValueError, match="NaN/Inf"):
        frozen_model._feature_matrix(pd.DataFrame({"a": [np.nan]}), ["a"], 1, "test")
