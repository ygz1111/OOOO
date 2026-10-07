# -*- coding: utf-8 -*-
"""
任意日期历史回测 —— 离线单元测试

通过 monkeypatch 注入假气象/假 TensorFlow 特征提供器/假推理服务（不触碰真实模型、DB、Open-Meteo），
验证 generate_day_backtest 的：
  - 24 个目标时刻对齐（预测对齐 t_i+1h）与误差字段/指标计算
  - 日期校验（未来 / 越界 / 目标日无真实数据）
  - 按日期缓存（60s TTL 内复用，不重复拉取）
  - day=None 范围模式（不触发任何重计算）
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import realtime_api.services.prediction_insight as pi
from realtime_api.services.container import services

# 假模型恒值输出（用于精确数值断言）
FORECAST_MW = 12000.0
ACTUAL_MW = 10000.0


def _make_weather_df(day_start):
    """覆盖 [D-192h, D+23h] 的双站点逐小时气象"""
    start = day_start - timedelta(hours=192)
    end = day_start + timedelta(hours=23)
    idx = pd.date_range(start, end, freq="h")
    rows = []
    for loc in ("Boston", "Hartford"):
        for t in idx:
            rows.append({
                "timestamp": t, "location": loc,
                "temperature_2m": 20.0, "dew_point_2m": 10.0,
                "relative_humidity_2m": 60.0, "wind_speed_10m": 3.0,
                "wind_direction_10m": 270.0, "cloud_cover": 50.0,
                "shortwave_radiation": 400.0, "direct_radiation": 300.0,
                "diffuse_radiation": 100.0, "surface_pressure": 1013.25,
            })
    return pd.DataFrame(rows)


def _make_load_df(day_start):
    start = day_start - timedelta(hours=192)
    end = day_start + timedelta(hours=23)
    idx = pd.date_range(start, end, freq="h")
    return pd.DataFrame({"timestamp": idx, "System_Load": ACTUAL_MW})


@pytest.fixture
def stubs(monkeypatch):
    """注入按日回测所需的全部离线假实现，并清空按日缓存"""
    today = pi._eastern_now_hour().date()
    day = today - timedelta(days=3)
    day_start = datetime(day.year, day.month, day.day)
    earliest = day_start - timedelta(days=10)
    latest = day_start + timedelta(hours=23)  # 目标日必须是完整实际负荷日

    calls = {"weather": 0, "load": 0, "infer": 0, "tf_infer": 0, "tf_windows": 0}
    state = {"with_actuals": True}

    weather_df = _make_weather_df(day_start)
    load_df = _make_load_df(day_start)

    async def fake_weather(start, end):
        calls["weather"] += 1
        return weather_df

    async def fake_load(start, end):
        calls["load"] += 1
        return load_df

    async def fake_actual_rows(start_time, end_time):
        if not state["with_actuals"]:
            return []
        rows = []
        t = start_time
        while t <= end_time:
            rows.append({"timestamp": t, "actual_load_mw": ACTUAL_MW})
            t += timedelta(hours=1)
        return rows

    async def fake_bounds():
        return {"earliest": earliest, "latest": latest}

    class FakeTFLoadPriceService:
        is_ready = True

        def predict_features(self, past, future):
            calls["tf_infer"] += 1
            return {
                "hourly": [{
                    "timestamp": str(future[0]["ts_local"]),
                    "load_forecast_mw": FORECAST_MW,
                }]
            }

    class FakeTFRealtimeFeatureProvider:
        def build_day_backtest(self, target_day, historical_weather):
            calls["tf_windows"] += 1
            assert not historical_weather.empty
            return [
                {
                    "target_time": str(day_start + timedelta(hours=hour)),
                    "actual_load_mw": ACTUAL_MW,
                    "past": [{"ts_local": day_start - timedelta(hours=168 - hour)}] * 168,
                    "future": [{"ts_local": day_start + timedelta(hours=hour)}] * 24,
                }
                for hour in range(24)
            ]

    class FakeNormalizer:
        def transform_features(self, features, clip=True):
            return np.zeros((len(features), 38))

    class FakeFeatureGenerator:
        def __init__(self, df):
            idx = pd.DatetimeIndex(sorted(pd.to_datetime(df["timestamp"]).unique()))
            self._features = pd.DataFrame(np.zeros((len(idx), 38)), index=idx)

        def generate(self, weather_df, historical_load=None):
            return self._features

        def build_sequence(self, features, lookback=168):
            return np.zeros((1, lookback, 38))

    monkeypatch.setattr(pi, "_load_historical_weather", fake_weather)
    monkeypatch.setattr(pi, "_load_historical_load", fake_load)
    monkeypatch.setattr(pi.ActualLoadDataCRUD, "get_actual_load_by_time_range", fake_actual_rows)
    monkeypatch.setattr(pi.ActualLoadDataCRUD, "get_time_bounds", fake_bounds)
    monkeypatch.setattr(services, "tf_load_price_service", FakeTFLoadPriceService(), raising=False)
    monkeypatch.setattr(services, "tf_realtime_feature_provider", FakeTFRealtimeFeatureProvider(), raising=False)
    monkeypatch.setattr(pi, "tf_load_backend_active", lambda: True)
    monkeypatch.setattr(services, "normalizer", FakeNormalizer(), raising=False)
    monkeypatch.setattr(services, "feature_generator", FakeFeatureGenerator(weather_df), raising=False)

    # 清空按日缓存，避免用例间串扰
    pi._DAY_BACKTEST_CACHE.update(key=None, data=None, timestamp=0.0)

    return {"day": day, "day_start": day_start, "earliest": earliest, "latest": latest,
            "calls": calls, "state": state}


class TestDayBacktest:
    async def test_returns_24_aligned_pairs_with_metrics_and_weather(self, stubs):
        data = await pi.generate_day_backtest(stubs["day"])

        assert data["date"] == stubs["day"].isoformat()
        assert data["timezone"] == "America/New_York"
        assert data["available_date_range"]["earliest"] == stubs["earliest"].date().isoformat()
        assert data["available_date_range"]["latest"] == stubs["latest"].date().isoformat()

        pairs = data["pairs"]
        assert len(pairs) == 24
        expected_times = [(stubs["day_start"] + timedelta(hours=h)).isoformat() for h in range(24)]
        assert [p["target_time"] for p in pairs] == expected_times
        # 假模型恒值输出：预测 12000、实际 10000 → 误差 2000（正=高估）
        for p in pairs:
            assert p["historical_actual"] == 10000.0
            assert p["historical_forecast"] == 12000.0
            assert p["error_mw"] == 2000.0
            assert p["absolute_error_mw"] == 2000.0
            assert p["percentage_error"] == 20.0
        # 24 个目标小时各调用一次 TensorFlow tf_v2。
        assert stubs["calls"]["tf_windows"] == 1
        assert stubs["calls"]["tf_infer"] == 24

        assert data["metrics"] == {"mae_mw": 2000.0, "rmse_mw": 2000.0, "mape": 20.0}

        weather = data["weather"]
        assert len(weather) == 24
        assert [w["target_time"] for w in weather] == expected_times
        assert weather[0]["temperature_2m"] == 20.0
        assert weather[0]["wind_speed_10m"] == 3.0
        assert weather[0]["cloud_cover"] == 50.0
        assert weather[0]["shortwave_radiation"] == 400.0

    async def test_future_date_rejected_without_inference(self, stubs):
        future = pi._eastern_now_hour().date() + timedelta(days=1)
        with pytest.raises(ValueError, match="晚于今天"):
            await pi.generate_day_backtest(future)
        assert stubs["calls"]["tf_infer"] == 0

    async def test_out_of_range_date_rejected(self, stubs):
        too_old = stubs["earliest"].date() - timedelta(days=1)
        with pytest.raises(ValueError, match="超出可用真实负荷范围"):
            await pi.generate_day_backtest(too_old)
        assert stubs["calls"]["tf_infer"] == 0

    async def test_no_actual_data_rejected_without_inference(self, stubs):
        stubs["state"]["with_actuals"] = False
        with pytest.raises(ValueError, match="无 ISO-NE 实际负荷数据"):
            await pi.generate_day_backtest(stubs["day"])
        assert stubs["calls"]["tf_infer"] == 0

    async def test_missing_actuals_yield_null_errors(self, stubs, monkeypatch):
        # 只提供前 12 个小时的实际 → 后半天空值，指标只按有效配对计算
        async def partial_rows(start_time, end_time):
            return [
                {"timestamp": start_time + timedelta(hours=h), "actual_load_mw": ACTUAL_MW}
                for h in range(12)
            ]

        monkeypatch.setattr(
            pi.ActualLoadDataCRUD, "get_actual_load_by_time_range", partial_rows
        )
        data = await pi.generate_day_backtest(stubs["day"])

        pairs = data["pairs"]
        assert len(pairs) == 24
        assert pairs[0]["historical_actual"] == 10000.0
        assert pairs[12]["historical_actual"] is None
        assert pairs[12]["error_mw"] is None
        assert pairs[12]["absolute_error_mw"] is None
        assert pairs[12]["percentage_error"] is None
        # 12 个有效配对（误差恒 2000）→ 指标与全量一致
        assert data["metrics"] == {"mae_mw": 2000.0, "rmse_mw": 2000.0, "mape": 20.0}

    async def test_cache_returns_same_object_without_refetch(self, stubs):
        first = await pi.generate_day_backtest(stubs["day"])
        assert stubs["calls"]["weather"] == 1

        second = await pi.generate_day_backtest(stubs["day"])
        assert second is first
        assert stubs["calls"]["weather"] == 1
        assert stubs["calls"]["tf_infer"] == 24  # 推理只发生一次

    async def test_force_refresh_bypasses_cache(self, stubs):
        first = await pi.generate_day_backtest(stubs["day"])
        second = await pi.generate_day_backtest(stubs["day"], force_refresh=True)

        assert second is not first
        assert stubs["calls"]["weather"] == 2
        assert stubs["calls"]["tf_infer"] == 48

    async def test_range_only_mode(self, stubs):
        data = await pi.generate_day_backtest(None)
        assert set(data.keys()) == {"available_date_range"}
        assert data["available_date_range"]["earliest"] == stubs["earliest"].date().isoformat()
        assert data["available_date_range"]["latest"] == stubs["latest"].date().isoformat()
        assert stubs["calls"]["weather"] == 0
        assert stubs["calls"]["tf_infer"] == 0
