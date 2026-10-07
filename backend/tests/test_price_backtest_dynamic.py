"""Offline checks for post-July price replay; no ISO-NE/Weather/model calls."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from realtime_api.services import price_backtest as backtest
from realtime_api.services.container import services
from realtime_api.tf_realtime_feature_provider import (
    LOAD_FUTURE_COLS, LOAD_PAST_COLS, TFRealtimeFeatureProvider,
)


class FakePriceService:
    is_ready = True

    def __init__(self):
        self.frozen_calls = []
        self.live_calls = 0

    def price_backtest(self, selected_date=None):
        self.frozen_calls.append(selected_date)
        base = {
            "available_date_range": {"earliest": "2017-01-08", "latest": "2026-07-31"},
            "date": selected_date, "points": [], "metrics": None,
        }
        if selected_date:
            base["data_source"] = "frozen_historical_backtest"
        return base

    def predict_task_features(self, task, past, future):
        assert task == "price"
        assert len(past) == 168 and len(future) == 24
        self.live_calls += 1
        return {
            "model": "tf_split_v1", "inference_time_ms": 12.0,
            "hourly": [
                {"hour": index, "timestamp": str(row["ts_local"]),
                 "price_p10": 40.0, "price_p50": 50.0, "price_p90": 60.0}
                for index, row in enumerate(future)
            ],
        }


class FakeProvider:
    def __init__(self):
        self.calls = []

    def build_price_day_backtest(self, day, weather):
        assert not weather.empty
        self.calls.append(day)
        first = pd.Timestamp(day) + pd.Timedelta(hours=1)
        future = [{"ts_local": first + pd.Timedelta(hours=index)} for index in range(24)]
        return {
            "past": [{"ts_local": pd.Timestamp(day)}] * 168,
            "future": future,
            "actual": [{"ts_local": row["ts_local"], "RT_LMP": 55.0} for row in future],
        }


@pytest.fixture
def setup_replay(monkeypatch):
    service, provider = FakePriceService(), FakeProvider()
    monkeypatch.setattr(services, "tf_load_price_service", service)
    monkeypatch.setattr(services, "tf_realtime_feature_provider", provider)
    monkeypatch.setattr(backtest, "get_engine_config", lambda: {"inference_mode": "live"})
    monkeypatch.setattr(backtest, "get_credentials", lambda: ("test-account", "test-password"))
    import realtime_api.services.prediction_insight as insight

    weather_calls = []

    async def historical_weather(start, end):
        weather_calls.append((start, end))
        return pd.DataFrame({"timestamp": [start], "temperature_2m": [20.0]})

    monkeypatch.setattr(insight, "_load_historical_weather", historical_weather)
    return service, provider, weather_calls


@pytest.mark.asyncio
async def test_range_is_fast_candidate_window_without_downloading(setup_replay):
    service, provider, weather_calls = setup_replay
    result = await backtest.generate_price_backtest()
    assert result["available_date_range"]["earliest"] == "2017-01-08"
    expected_latest = (datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)).isoformat()
    assert result["available_date_range"]["latest"] == max("2026-07-31", expected_latest)
    assert service.frozen_calls == [None]
    assert provider.calls == weather_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("day", [date(2026, 8, 15), date(2026, 9, 20)])
async def test_august_september_replay_pairs_24_hours_without_retraining(setup_replay, day):
    service, provider, weather_calls = setup_replay
    result = await backtest.generate_price_backtest(day)
    assert provider.calls == [day]
    assert service.live_calls == 1
    assert weather_calls == [
        (datetime.combine(day - timedelta(days=16), datetime.min.time()),
         datetime.combine(day + timedelta(days=1), datetime.min.time()))
    ]
    assert result["data_source"] == "iso_ne+open_meteo:historical_replay"
    assert len(result["points"]) == 24
    assert result["points"][0]["timestamp"] == str(pd.Timestamp(day) + pd.Timedelta(hours=1))
    assert result["points"][-1]["timestamp"] == str(pd.Timestamp(day) + pd.Timedelta(days=1))
    assert result["points"][0]["error_p50"] == -5.0
    assert result["metrics"] == {
        "count": 24, "mae_usd": 5.0, "rmse_usd": 5.0, "mape_pct": 9.09,
        "median_ae_usd": 5.0, "bias_usd": -5.0, "p10_p90_coverage": 100.0,
    }


@pytest.mark.asyncio
async def test_frozen_dates_do_not_download_or_call_live_model(setup_replay):
    service, provider, weather_calls = setup_replay
    result = await backtest.generate_price_backtest(date(2026, 7, 31))
    assert result["data_source"] == "frozen_historical_backtest"
    assert service.frozen_calls == [None, "2026-07-31"]
    assert service.live_calls == 0
    assert provider.calls == weather_calls == []


@pytest.mark.asyncio
async def test_frozen_dst_window_rejected_before_model_or_weather_calls(setup_replay):
    service, provider, weather_calls = setup_replay
    with pytest.raises(ValueError, match="夏令时"):
        await backtest.generate_price_backtest(date(2026, 3, 8))
    assert service.frozen_calls == [None]
    assert service.live_calls == 0
    assert provider.calls == weather_calls == []


@pytest.mark.asyncio
async def test_future_candidate_and_missing_credentials_are_rejected(setup_replay, monkeypatch):
    service, provider, weather_calls = setup_replay
    future = date.today() + timedelta(days=2)
    with pytest.raises(ValueError, match="不在可选范围"):
        await backtest.generate_price_backtest(future)
    monkeypatch.setattr(backtest, "get_credentials", lambda: (None, None))
    range_only = await backtest.generate_price_backtest()
    assert range_only["available_date_range"]["latest"] == "2026-07-31"
    assert service.live_calls == 0
    assert provider.calls == weather_calls == []


def test_replay_rejects_missing_or_misaligned_actuals():
    day = date(2026, 8, 15)
    first = pd.Timestamp(day) + pd.Timedelta(hours=1)
    times = [first + pd.Timedelta(hours=index) for index in range(24)]
    prediction = {"hourly": [
        {"timestamp": str(ts), "price_p10": 40, "price_p50": 50, "price_p90": 60}
        for ts in times
    ]}
    inputs = {"actual": [{"ts_local": ts, "RT_LMP": 55} for ts in times[:-1]]}
    with pytest.raises(ValueError, match="完整的 24"):
        backtest._replay_result(day, {}, inputs, prediction)
    inputs["actual"].append({"ts_local": first + pd.Timedelta(hours=25), "RT_LMP": 55})
    with pytest.raises(ValueError, match="小时不一致"):
        backtest._replay_result(day, {}, inputs, prediction)


@pytest.mark.parametrize("day", [date(2026, 8, 15), date(2026, 9, 30)])
def test_provider_requires_features_but_preserves_missing_target_labels(monkeypatch, day):
    provider = TFRealtimeFeatureProvider()
    day_start = pd.Timestamp(day)
    times = pd.date_range(day_start - pd.Timedelta(hours=167), periods=192, freq="h")
    columns = set(LOAD_PAST_COLS + LOAD_FUTURE_COLS + ["RT_LMP"])
    market = pd.DataFrame({"ts_local": times, **{name: 1.0 for name in columns}})
    weather = pd.DataFrame({"timestamp": [day_start], "temperature_2m": [20.0]})
    monkeypatch.setattr(provider, "_weather", lambda _: weather)
    monkeypatch.setattr(provider, "_market_frames_for_range", lambda **_: {
        name: pd.DataFrame({"x": [1]}) for name in ("load", "da_demand", "rt_lmp", "da_lmp")
    })
    monkeypatch.setattr(provider, "_prepare_load_market", lambda *_: market)
    result = provider.build_price_day_backtest(day, weather)
    assert len(result["past"]) == 168
    assert len(result["future"]) == len(result["actual"]) == 24
    assert "RT_LMP" not in result["future"][0]
    assert result["future"][0]["ts_local"] == day_start + pd.Timedelta(hours=1)
    missing_index = market.index[-3]
    market.drop(index=missing_index, inplace=True)
    with pytest.raises(ValueError, match="不完整"):
        provider.build_price_day_backtest(day, weather)
    market.loc[missing_index, :] = {"ts_local": day_start + pd.Timedelta(hours=22),
                                    **{name: 1.0 for name in columns}}
    market.loc[market["ts_local"] == day_start + pd.Timedelta(hours=22), "RT_LMP"] = float("nan")
    result = provider.build_price_day_backtest(day, weather)
    assert len(result["future"]) == len(result["actual"]) == 24
    assert pd.isna(result["actual"][21]["RT_LMP"])
    assert result["actual"][-1]["ts_local"] == day_start + pd.Timedelta(days=1)


def test_hourly_preliminary_empty_uses_final(monkeypatch):
    provider = TFRealtimeFeatureProvider()
    paths = []

    def get(path):
        paths.append(path)
        if "/prelim/" in path:
            return {"HourlyLmps": {"HourlyLmp": []}}
        return {"HourlyLmps": {"HourlyLmp": [{"BeginDate": "2026-08-15T00:00:00"}]}}

    monkeypatch.setattr(provider, "_get", get)
    _, _, rows = provider._fetch_day("rt_lmp", date(2026, 8, 15))
    assert len(rows) == 1
    assert rows[0]["_rt_lmp_source"] == "iso_ne_hourly_final"
    assert len(paths) == 2 and "/final/" in paths[-1]


@pytest.mark.parametrize("all_missing", [False, True])
def test_missing_and_derived_labels_never_enter_real_errors(all_missing):
    import json
    day = date(2026, 9, 30)
    times = pd.date_range(pd.Timestamp(day) + pd.Timedelta(hours=1), periods=24, freq="h")
    prediction = {"hourly": [{"timestamp": str(ts), "price_p10": -40., "price_p50": -20., "price_p90": 10.} for ts in times]}
    actual = [{"ts_local": ts, "RT_LMP": -25., "rt_lmp_source": "iso_ne_hourly_final", "rt_lmp_label_valid": True} for ts in times]
    if all_missing:
        for row in actual:
            row["RT_LMP"] = float("nan")
    else:
        actual[0].update(RT_LMP=999., rt_lmp_source="iso_ne_five_minute_aggregate", rt_lmp_samples=12, rt_lmp_label_valid=False)
        actual[1]["RT_LMP"] = float("nan")
    result = backtest._replay_result(day, {}, {"actual": actual}, prediction)
    assert len(result["points"]) == 24
    assert result["points"][0]["price_actual"] is None
    assert result["points"][0]["error_p50"] is None
    assert result["points"][-1]["timestamp"] == "2026-10-01 00:00:00"
    if all_missing:
        assert result["metrics"] is None
        assert result["label_quality"]["missing_hours"] == 24
    else:
        assert result["metrics"]["count"] == 22
        assert result["metrics"]["mae_usd"] == 5.
        assert result["label_quality"]["input_only_hours"] == 1
        assert result["label_quality"]["missing_hours"] == 1
        assert result["points"][0]["samples_per_hour"] == 12
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("day", [date(2026, 3, 8), date(2026, 11, 1), date(2026, 11, 8)])
def test_price_model_rejects_dst_target_or_history_before_downloading(monkeypatch, day):
    provider = TFRealtimeFeatureProvider()
    monkeypatch.setattr(provider, "_market_frames_for_range", lambda **_: pytest.fail("DST窗口不应下载电网数据"))
    with pytest.raises(ValueError, match="夏令时"):
        provider.build_price_day_backtest(day, pd.DataFrame())
