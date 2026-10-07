"""TF 在线特征适配层的离线契约测试（不访问网络）。"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from realtime_api.pv_capacity import btm_pv_capacity_mw
from realtime_api.tf_realtime_feature_provider import (
    LOAD_FUTURE_COLS,
    LOAD_PAST_COLS,
    PV_CAPACITY_FALLBACK_MW,
    TFRealtimeFeatureProvider,
    _solar_coszen,
)


PV_STATIONS = ("boston", "burlington", "hartford", "manchester", "portland", "providence")


def test_reuses_only_fresh_same_hour_same_weather_bundle(monkeypatch):
    provider = TFRealtimeFeatureProvider(cache_ttl=300)
    cached = {"origin_hour_end": "2026-09-21 09:00:00", "marker": "cached"}
    provider._cached = cached
    provider._cached_at = 3500.0
    provider._cached_hour = pd.Timestamp("2026-09-21 09:00:00")
    provider._cached_weather = pd.DataFrame()

    monkeypatch.setattr(
        provider, "_current_eastern_hour", lambda: pd.Timestamp("2026-09-21 09:00:00")
    )
    monkeypatch.setattr("realtime_api.tf_realtime_feature_provider.time.time", lambda: 3600.0)
    monkeypatch.setattr(
        provider,
        "_market_frames",
        lambda _today: pytest.fail("当前小时快照不应重新下载 ISO-NE 历史数据"),
    )

    assert provider.build(pd.DataFrame()) is cached


@pytest.mark.parametrize("change", ["expired", "weather", "hour", "force"])
def test_rebuilds_bundle_when_inputs_or_freshness_change(monkeypatch, change):
    provider = TFRealtimeFeatureProvider(cache_ttl=300)
    provider._cached = {"marker": "old"}
    provider._cached_at = 3500.0 if change != "expired" else 0.0
    provider._cached_hour = pd.Timestamp("2026-09-21 09:00")
    provider._cached_weather = pd.DataFrame({"value": [1]})
    monkeypatch.setattr(provider, "_current_eastern_hour", lambda: pd.Timestamp(
        "2026-09-21 10:00" if change == "hour" else "2026-09-21 09:00"))
    monkeypatch.setattr("realtime_api.tf_realtime_feature_provider.time.time", lambda: 3600.0)
    def rebuilding(_weather):
        raise ValueError("rebuilding")
    monkeypatch.setattr(provider, "_weather", rebuilding)
    weather = pd.DataFrame({"value": [2 if change == "weather" else 1]})
    with pytest.raises(ValueError, match="rebuilding"):
        provider.build(weather, force_refresh=change == "force")


def test_daily_cache_refreshes_recent_days_without_redownloading_history(monkeypatch):
    provider = TFRealtimeFeatureProvider(cache_ttl=300)
    clock = [0.0]
    calls = []
    monkeypatch.setattr(provider, "_current_eastern_hour", lambda: pd.Timestamp("2026-09-21 09:00"))
    monkeypatch.setattr("realtime_api.tf_realtime_feature_provider.time.monotonic", lambda: clock[0])
    def fetch(kind, day):
        calls.append((kind, day))
        return kind, day, [{"revision": len(calls)}]
    monkeypatch.setattr(provider, "_fetch_day", fetch)
    old, recent = date(2026, 9, 15), date(2026, 9, 21)
    for day in [old, recent]:
        provider._fetch_day_cached("pv", day)
        provider._fetch_day_cached("pv", day)
    assert len(calls) == 2
    clock[0] = 301
    provider._fetch_day_cached("pv", old)
    provider._fetch_day_cached("pv", recent)
    assert len(calls) == 3
    clock[0] = 21601
    provider._fetch_day_cached("pv", old)
    assert len(calls) == 4


def test_daily_cache_does_not_store_empty_or_failed_requests(monkeypatch):
    provider = TFRealtimeFeatureProvider()
    key = ("pv", date(2026, 9, 15))
    monkeypatch.setattr(provider, "_fetch_day", lambda kind, day: (kind, day, []))
    provider._fetch_day_cached(*key)
    assert key not in provider._day_cache
    def fail(*args):
        raise RuntimeError("upstream unavailable")
    monkeypatch.setattr(provider, "_fetch_day", fail)
    with pytest.raises(RuntimeError):
        provider._fetch_day_cached(*key)
    assert key not in provider._day_cache
    assert key not in provider._day_inflight


def test_recent_day_cache_expires_at_hour_boundary(monkeypatch):
    from unittest.mock import Mock
    provider = TFRealtimeFeatureProvider()
    hour = [pd.Timestamp("2026-09-21 09:00")]
    monkeypatch.setattr(provider, "_current_eastern_hour", lambda: hour[0])
    fetch = Mock(return_value=("pv", date(2026, 9, 21), [{"value": 1}]))
    monkeypatch.setattr(provider, "_fetch_day", fetch)
    provider._fetch_day_cached("pv", date(2026, 9, 21))
    hour[0] += pd.Timedelta(hours=1)
    provider._fetch_day_cached("pv", date(2026, 9, 21))
    assert fetch.call_count == 2


def _with_pv_stations(frame: pd.DataFrame) -> pd.DataFrame:
    """把区域天气测试夹具展开为生产 pv_v2 要求的六个站点。"""
    source = frame.drop(columns=["location"], errors="ignore")
    return pd.concat(
        [source.assign(location=station) for station in PV_STATIONS],
        ignore_index=True,
    )


def test_online_backtest_skips_one_incomplete_hour_without_breaking_forecast():
    """单个历史回测点缺失时，在线未来预测仍应可以生成。"""
    provider = TFRealtimeFeatureProvider()
    index = pd.date_range("2026-08-01 00:00", periods=400, freq="h")
    market = pd.DataFrame({"ts_local": index, "RT_Demand": 11000.0})
    for column in set(LOAD_PAST_COLS + LOAD_FUTURE_COLS):
        if column not in market:
            market[column] = 1.0

    # 为每个回测目标保留完整的 24 小时 future 特征区间。
    latest = index[-25]
    first_target = latest - pd.Timedelta(hours=23)
    first_past_start = first_target - pd.Timedelta(hours=168)
    market.loc[market["ts_local"] == first_past_start, "rt_lag168"] = np.nan

    windows = provider._build_load_backtest_windows(
        market, latest, skip_incomplete=True
    )

    assert len(windows) == 23
    assert pd.Timestamp(windows[0]["target_time"]) == first_target + pd.Timedelta(hours=1)


def test_solar_coszen_follows_new_england_daylight_in_summer():
    index = pd.date_range("2026-09-11 00:00:00", periods=24, freq="h")
    values = _solar_coszen(index)

    assert values[0] == 0.0
    assert values[6] == 0.0
    assert values[8] > 0.0
    assert values[13] == values.max()
    assert values[19] <= 0.02
    assert values[23] == 0.0


def test_solar_coszen_follows_new_england_daylight_in_winter():
    index = pd.date_range("2026-01-15 00:00:00", periods=24, freq="h")
    values = _solar_coszen(index)

    assert values[0] == 0.0
    assert values[8] > 0.0
    assert values[12] == values.max()
    assert values[17] == 0.0


def test_empty_iso_ne_response_keeps_datetime_indexes(monkeypatch):
    """上游失败应报告空数据，不能在时间对齐阶段抛出索引类型异常。"""
    provider = TFRealtimeFeatureProvider()

    def fail_fetch(*_args, **_kwargs):
        raise RuntimeError("ISO-NE unavailable")

    monkeypatch.setattr(provider, "_fetch_day", fail_fetch)
    frames = provider._market_frames_for_range(
        actual_start=date(2026, 9, 1),
        actual_end=date(2026, 9, 1),
        da_end=date(2026, 9, 1),
    )

    assert all(frame.empty for frame in frames.values())
    assert all(isinstance(frame.index, pd.DatetimeIndex) for frame in frames.values())


def test_fills_hourly_rt_lmp_gaps_from_official_five_minute(monkeypatch):
    """小时 RT-LMP 缺口应由同一官方五分钟接口聚合补齐。"""
    provider = TFRealtimeFeatureProvider()
    hourly = pd.DataFrame(
        {"rt_lmp": [30.0, 40.0]},
        index=pd.DatetimeIndex([
            "2026-09-11 23:00:00",
            "2026-09-12 02:00:00",
        ], name="ts_local"),
    )

    def five_minute_rows(_kind, day):
        assert _kind == "rt_lmp_5min"
        if day == date(2026, 9, 11):
            starts = pd.date_range("2026-09-11 23:00", periods=11, freq="5min")
            value = 34.0
        else:
            starts = pd.date_range("2026-09-12 00:00", periods=8, freq="5min")
            value = 36.0
        rows = [
            {
                "BeginDate": timestamp.isoformat(),
                "LmpTotal": value,
                "Location": {"@LocId": "4000"},
            }
            for timestamp in starts
        ]
        return _kind, day, rows

    monkeypatch.setattr(provider, "_fetch_day", five_minute_rows)
    filled = provider._fill_rt_lmp_gaps_from_five_minute(hourly)

    assert list(filled.index) == list(pd.date_range(
        "2026-09-11 23:00", "2026-09-12 02:00", freq="h"
    ))
    assert filled.loc[pd.Timestamp("2026-09-12 00:00"), "rt_lmp"] == 34.0
    assert filled.loc[pd.Timestamp("2026-09-12 01:00"), "rt_lmp"] == 36.0
    assert filled.loc[pd.Timestamp("2026-09-12 01:00"), "rt_lmp_source"] == "iso_ne_five_minute_aggregate"
    assert filled.loc[pd.Timestamp("2026-09-12 01:00"), "rt_lmp_samples"] == 8
    assert not filled.loc[pd.Timestamp("2026-09-12 01:00"), "rt_lmp_label_valid"]
    again = provider._fill_rt_lmp_gaps_from_five_minute(filled)
    assert not again.loc[pd.Timestamp("2026-09-12 01:00"), "rt_lmp_label_valid"]
    assert again.loc[pd.Timestamp("2026-09-12 02:00"), "rt_lmp_label_valid"]


def test_rejects_five_minute_lmp_hour_below_coverage_threshold(monkeypatch):
    """少于 8 个五分钟点时不得伪造完整小时 RT-LMP。"""
    provider = TFRealtimeFeatureProvider()
    hourly = pd.DataFrame(
        {"rt_lmp": [30.0, 40.0]},
        index=pd.DatetimeIndex([
            "2026-09-12 00:00:00",
            "2026-09-12 02:00:00",
        ], name="ts_local"),
    )
    starts = pd.date_range("2026-09-12 00:00", periods=7, freq="5min")
    rows = [
        {
            "BeginDate": timestamp.isoformat(),
            "LmpTotal": 35.0,
            "Location": {"@LocId": "4000"},
        }
        for timestamp in starts
    ]
    monkeypatch.setattr(
        provider,
        "_fetch_day",
        lambda kind, day: (kind, day, rows),
    )

    filled = provider._fill_rt_lmp_gaps_from_five_minute(hourly)

    assert pd.Timestamp("2026-09-12 01:00") not in filled.index


@pytest.mark.parametrize("valid_samples", [7, 8])
def test_lmp_fallback_counts_unique_aligned_finite_hub_samples(monkeypatch, valid_samples):
    provider = TFRealtimeFeatureProvider()
    hourly = pd.DataFrame({"rt_lmp": [30., 40.]}, index=pd.DatetimeIndex(["2026-09-12 00:00", "2026-09-12 02:00"]))
    # UTC timestamps normalize to Eastern interval starts; negative prices remain valid.
    starts = pd.date_range("2026-09-12 04:00Z", periods=valid_samples, freq="5min")
    rows = [{"BeginDate": ts.isoformat(), "LmpTotal": -20., "Location": {"@LocId": "4000"}} for ts in starts]
    rows += [rows[0]] * 5
    rows += [{"BeginDate": "2026-09-12T04:41:00Z", "LmpTotal": 100.},
             {"BeginDate": "2026-09-12T04:45:00Z", "LmpTotal": float("inf")},
             {"BeginDate": "2026-09-12T04:50:00Z", "LmpTotal": 100., "Location": {"@LocId": "4001"}}]
    monkeypatch.setattr(provider, "_fetch_day_cached", lambda kind, day: (kind, day, rows))
    monkeypatch.setattr(provider, "_current_eastern_hour", lambda: pd.Timestamp("2026-09-12 02:00"))
    filled = provider._fill_rt_lmp_gaps_from_five_minute(hourly)
    target = pd.Timestamp("2026-09-12 01:00")
    if valid_samples == 7:
        assert target not in filled.index
    else:
        assert filled.loc[target, "rt_lmp"] == -20.
        assert filled.loc[target, "rt_lmp_samples"] == 8
        assert not filled.loc[target, "rt_lmp_label_valid"]


def test_lmp_fallback_does_not_fill_open_hour(monkeypatch):
    provider = TFRealtimeFeatureProvider()
    hourly = pd.DataFrame({"rt_lmp": [30., 40.]}, index=pd.DatetimeIndex(["2026-09-12 00:00", "2026-09-12 02:00"]))
    rows = [{"BeginDate": ts.isoformat(), "LmpTotal": 20.} for ts in pd.date_range("2026-09-12 00:00", periods=12, freq="5min")]
    monkeypatch.setattr(provider, "_fetch_day_cached", lambda kind, day: (kind, day, rows))
    monkeypatch.setattr(provider, "_current_eastern_hour", lambda: pd.Timestamp("2026-09-12 00:00"))
    filled = provider._fill_rt_lmp_gaps_from_five_minute(hourly)
    assert pd.Timestamp("2026-09-12 01:00") not in filled.index


@pytest.mark.parametrize("rows, expected", [
    ([{"BeginDate": "2026-09-12T00:00:00-04:00", "LmpTotal": -20.},
      {"BeginDate": "2026-09-12T00:05:00-04:00", "LmpTotal": 99.},
      {"BeginDate": "2026-09-12T01:00:00-04:00", "LmpTotal": float("inf")},
      {"BeginDate": "2026-09-12T02:00:00-04:00", "LmpTotal": 99., "Location": {"@LocId": "4001"}}], [-20.]),
    ([{"BeginDate": "2026-11-01T01:00:00-04:00", "LmpTotal": 10.},
      {"BeginDate": "2026-11-01T01:00:00-05:00", "LmpTotal": 30.}], []),
])
def test_hourly_lmp_rejects_invalid_or_dst_ambiguous_records(monkeypatch, rows, expected):
    provider = TFRealtimeFeatureProvider()
    monkeypatch.setattr(provider, "_fetch_day_cached", lambda kind, day: (kind, day, rows if kind == "rt_lmp" else []))
    frames = provider._market_frames_for_range(date(2026, 9, 12), date(2026, 9, 12), date(2026, 9, 12))
    assert frames["rt_lmp"]["rt_lmp"].tolist() == expected


def test_keeps_completed_pv_hour_with_two_thirds_five_minute_coverage(monkeypatch):
    """八个分区均有 8/12 点时应保留小时，不能让滚动窗口倒退数天。"""
    provider = TFRealtimeFeatureProvider()
    starts = pd.date_range("2026-09-17 10:00", periods=8, freq="5min")

    def rows_for(kind, day):
        assert day == date(2026, 9, 17)
        if kind == "pv":
            rows = [
                {
                    "interval_begin_date": timestamp.isoformat(),
                    "load_zone_id": zone,
                    "estimated_btm_pv_mw": 100.0,
                    "estimated_load_mw": 1000.0,
                }
                for zone in range(4001, 4009)
                for timestamp in starts
            ]
        elif kind == "rt_lmp":
            rows = [{
                "BeginDate": "2026-09-17 10:00:00",
                "LmpTotal": 30.0,
                "Location": {"@LocId": "4000"},
            }]
        elif kind == "da_demand":
            rows = [{
                "BeginDate": "2026-09-17 10:00:00",
                "Load": 8000.0,
                "Location": {"@LocId": "32"},
            }]
        else:
            rows = [{
                "BeginDate": "2026-09-17 10:00:00",
                "LmpTotal": 28.0,
                "Location": {"@LocId": "4000"},
            }]
        return kind, day, rows

    monkeypatch.setattr(provider, "_fetch_day", rows_for)
    frames = provider._market_frames_for_range(
        actual_start=date(2026, 9, 17),
        actual_end=date(2026, 9, 17),
        da_end=date(2026, 9, 17),
    )

    hour = pd.Timestamp("2026-09-17 10:00")
    assert hour in frames["pv"].index
    assert frames["pv"].loc[hour, "minimum_samples"] == 8
    assert frames["pv"].loc[hour, "pv_mw"] == 800.0
    assert frames["load"].loc[hour + pd.Timedelta(hours=1), "load"] == 8000.0


def test_builds_rolling_window_from_latest_actual_hour(monkeypatch):
    weather_index = pd.date_range("2026-08-20 00:00", "2026-09-08 23:00", freq="h")
    weather = _with_pv_stations(pd.DataFrame({
        "timestamp": weather_index,
        "temperature_2m": 20 + np.sin(np.arange(len(weather_index)) / 24),
        "dew_point_2m": 12.0,
        "cloud_cover": 30.0,
        "shortwave_radiation": np.maximum(0, 700 * np.sin(
            np.pi * (weather_index.hour.to_numpy() - 6) / 12)),
    }))
    # 即使上游包含当前未结束小时的部分采样，也不能将它作为完整实况。
    actual_end = pd.date_range("2026-08-20 01:00", "2026-09-07 07:00", freq="h")
    da_end = pd.date_range("2026-08-20 01:00", "2026-09-08 00:00", freq="h")
    pv_start = pd.date_range("2026-08-20 00:00", "2026-09-07 06:00", freq="h")
    frames = {
        "load": pd.DataFrame({"load": 11000 + np.arange(len(actual_end))}, index=actual_end),
        "da_demand": pd.DataFrame({"da_demand": 11200.0}, index=da_end),
        "rt_lmp": pd.DataFrame({"rt_lmp": 35.0}, index=actual_end),
        "da_lmp": pd.DataFrame({"da_lmp": 32.0}, index=da_end),
        "pv": pd.DataFrame({"pv_mw": 500.0, "rt_demand": 11000.0}, index=pv_start),
    }
    provider = TFRealtimeFeatureProvider()
    monkeypatch.setattr(provider, "_market_frames", lambda _today: frames)
    monkeypatch.setattr(
        provider, "_current_eastern_hour", lambda: pd.Timestamp("2026-09-07 06:00")
    )

    bundle = provider.build(weather)

    assert bundle["origin_hour_end"] == "2026-09-07 06:00:00"
    assert len(bundle["load_price"]["past"]) == 168
    assert len(bundle["load_price"]["future"]) == 24
    assert len(bundle["load_price_backtest"]) == 24
    assert len(bundle["pv"]["past"]) == 96
    assert len(bundle["pv"]["future"]) == 24
    assert len(bundle["pv_backtest"]) == 24
    assert bundle["load_price"]["future"][0]["ts_local"] == pd.Timestamp("2026-09-07 07:00")
    assert bundle["load_price"]["future"][-1]["ts_local"] == pd.Timestamp("2026-09-08 06:00")
    assert bundle["pv"]["future"][0]["ts_start"] == pd.Timestamp("2026-09-07 06:00")
    assert len(bundle["input_quality"]["day_ahead_imputed"]) == 12
    assert "day_ahead_persistence" in bundle["data_source"]
    # rt_yest 只能来自预测时点 24h 前已发生的负荷。
    first_future = bundle["load_price"]["future"][0]
    expected = frames["load"].loc[pd.Timestamp("2026-09-06 07:00"), "load"]
    assert first_future["rt_yest"] == expected
    # 每个回测窗口第 0 步恰好对应 target_time，最后一个目标是当前锚点。
    first_backtest = bundle["load_price_backtest"][0]
    last_backtest = bundle["load_price_backtest"][-1]
    assert first_backtest["target_time"] == "2026-09-06 07:00:00"
    assert first_backtest["future"][0]["ts_local"] == pd.Timestamp("2026-09-06 07:00")
    assert last_backtest["target_time"] == bundle["origin_hour_end"]
    # 光伏采用 hour-start：每个窗口的未来第 0 步与目标时刻一致，历史
    # 输入严格截止在目标前一小时，真实值来自 ISO-NE estimated BTM PV。
    first_pv_backtest = bundle["pv_backtest"][0]
    last_pv_backtest = bundle["pv_backtest"][-1]
    assert first_pv_backtest["future"][0]["ts_start"] == pd.Timestamp(
        first_pv_backtest["target_time"]
    )
    assert first_pv_backtest["past"][-1]["ts_start"] == (
        pd.Timestamp(first_pv_backtest["target_time"]) - pd.Timedelta(hours=1)
    )
    assert last_pv_backtest["target_time"] == bundle["origin_hour_start"]
    assert last_pv_backtest["actual_pv_mw"] == 500.0
    last_past = last_pv_backtest["past"][-1]
    # pv_v2 当前直接学习 ISO-NE 官方 BTM MW，不再按装机容量归一化。
    assert last_past["pv_mw_ISONE"] == 500.0


def test_celt_capacity_is_date_aligned_without_using_year_end_early():
    fallback = PV_CAPACITY_FALLBACK_MW
    january = btm_pv_capacity_mw("2026-01-31 23:59:59", fallback_mw=fallback)
    september = btm_pv_capacity_mw("2026-09-30 23:59:59", fallback_mw=fallback)
    year_end = btm_pv_capacity_mw("2026-12-31 23:59:59", fallback_mw=fallback)

    assert january == 5131.0 + 363.0 * 0.06
    assert september == 5131.0 + 363.0 * 0.63
    assert year_end == 5494.0
    assert january < september < year_end


def test_rejects_missing_day_ahead_feature(monkeypatch):
    weather_index = pd.date_range("2026-08-20", "2026-09-08 23:00", freq="h")
    weather = _with_pv_stations(pd.DataFrame({
        "timestamp": weather_index, "temperature_2m": 20.0,
        "dew_point_2m": 10.0, "cloud_cover": 20.0,
        "shortwave_radiation": 100.0,
    }))
    actual_end = pd.date_range("2026-08-20 01:00", "2026-09-07 06:00", freq="h")
    da_end = pd.date_range("2026-08-20 01:00", "2026-09-08 00:00", freq="h")
    pv_start = actual_end - pd.Timedelta(hours=1)
    da_values = pd.Series(11000.0, index=da_end)
    da_values.loc[pd.Timestamp("2026-09-07 12:00")] = np.nan
    frames = {
        "load": pd.DataFrame({"load": 11000.0}, index=actual_end),
        "da_demand": da_values.to_frame("da_demand"),
        "rt_lmp": pd.DataFrame({"rt_lmp": 30.0}, index=actual_end),
        "da_lmp": pd.DataFrame({"da_lmp": 31.0}, index=da_end),
        "pv": pd.DataFrame({"pv_mw": 400.0, "rt_demand": 11000.0}, index=pv_start),
    }
    provider = TFRealtimeFeatureProvider()
    monkeypatch.setattr(provider, "_market_frames", lambda _today: frames)
    monkeypatch.setattr(
        provider, "_current_eastern_hour", lambda: pd.Timestamp("2026-09-07 06:00")
    )

    try:
        provider.build(weather)
    except ValueError as exc:
        assert "已发布区间存在内部缺口" in str(exc)
    else:
        raise AssertionError("缺失日前需求时不应生成在线输入")


def test_builds_tensorflow_windows_for_a_completed_historical_day(monkeypatch):
    """按日回测必须为 24 个目标小时各生成严格 168h/24h 的 tf_v2 输入。"""
    day = pd.Timestamp("2026-08-30").date()
    weather_index = pd.date_range("2026-08-13 00:00", "2026-08-31 23:00", freq="h")
    weather = pd.DataFrame({
        "timestamp": weather_index,
        "location": "Regional",
        "temperature_2m": 20.0,
        "dew_point_2m": 12.0,
        "cloud_cover": 30.0,
        "shortwave_radiation": 200.0,
    })
    actual_index = pd.date_range("2026-08-13 00:00", "2026-08-30 23:00", freq="h")
    da_index = pd.date_range("2026-08-13 00:00", "2026-08-31 23:00", freq="h")
    pv_index = actual_index - pd.Timedelta(hours=1)
    frames = {
        "load": pd.DataFrame({"load": 11000.0}, index=actual_index),
        "da_demand": pd.DataFrame({"da_demand": 11200.0}, index=da_index),
        "rt_lmp": pd.DataFrame({"rt_lmp": 35.0}, index=actual_index),
        "da_lmp": pd.DataFrame({"da_lmp": 32.0}, index=da_index),
        "pv": pd.DataFrame({"pv_mw": 500.0, "rt_demand": 11000.0}, index=pv_index),
    }
    provider = TFRealtimeFeatureProvider()
    monkeypatch.setattr(provider, "_market_frames_for_range", lambda **_kwargs: frames)

    windows = provider.build_day_backtest(day, weather)

    assert len(windows) == 24
    assert windows[0]["target_time"] == "2026-08-30 00:00:00"
    assert windows[-1]["target_time"] == "2026-08-30 23:00:00"
    assert all(len(window["past"]) == 168 for window in windows)
    assert all(len(window["future"]) == 24 for window in windows)
    assert windows[0]["future"][0]["ts_local"] == pd.Timestamp("2026-08-30 00:00")
