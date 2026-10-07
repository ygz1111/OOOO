"""Offline prediction edge cases: no upstream, database, weights or cache IO."""

from datetime import date
import json

import numpy as np
import pandas as pd
import pytest

from realtime_api.tf_realtime_feature_provider import TFRealtimeFeatureProvider
from realtime_api.tf_split_service import TFSplitService


@pytest.mark.parametrize("actual", [0.0, 0.5, -0.5])
def test_frozen_price_backtest_near_zero_labels_have_no_mape(actual):
    service = TFSplitService()
    times = pd.date_range("2026-01-01", periods=12 * 24, freq="h")
    service._frame = pd.DataFrame({"ts_local": times, "RT_LMP": actual})
    targets = pd.date_range("2026-01-09 01:00", periods=24, freq="h")
    service.predict = lambda _: {
        "hourly": [{"timestamp": str(ts), "price_p10": -5.0,
                    "price_p50": 2.0, "price_p90": 5.0} for ts in targets]
    }

    result = service.price_backtest("2026-01-09")

    assert result["metrics"]["count"] == 24
    assert result["metrics"]["mae_usd"] == abs(2.0 - actual)
    assert result["metrics"]["mape_pct"] is None
    assert "无符合条件样本" in result["metric_note"]
    assert result["metrics"]["p10_p90_coverage"] == 100.0
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("kind,key,location", [
    ("da_demand", "Load", 32), ("da_lmp", "LmpTotal", 4000),
])
@pytest.mark.parametrize("invalid", [
    {"value": "unavailable"}, {"value": "inf"},
    {"location": "unknown"}, {"location": 4008},
    {"begin": "invalid-date"}, {"begin": "2026-01-31T23:30:00-05:00"},
    {"begin": "2026-03-08T02:00:00"},
    {"begin": "2026-11-01T01:00:00-04:00"},
])
def test_invalid_day_ahead_record_does_not_discard_independent_pv(
        monkeypatch, kind, key, location, invalid):
    provider = TFRealtimeFeatureProvider()
    start = pd.Timestamp("2026-01-31 23:00")
    monkeypatch.setattr(provider, "_current_eastern_hour", lambda: start + pd.Timedelta(hours=1))
    monkeypatch.setattr(provider, "_fill_rt_lmp_gaps_from_five_minute", lambda frame: frame)
    good = {
        "da_demand": [{"BeginDate": str(start), "Load": 16000., "Location": {"@LocId": 32}}],
        "da_lmp": [{"BeginDate": str(start), "LmpTotal": -15., "Location": {"@LocId": 4000}}],
        "rt_lmp": [{"BeginDate": str(start), "LmpTotal": -10., "Location": {"@LocId": 4000}}],
        "pv": [{"interval_begin_date": str(start + pd.Timedelta(minutes=minute)),
                "estimated_load_mw": 1000., "estimated_btm_pv_mw": 100., "load_zone_id": zone}
               for zone in range(4001, 4009) for minute in range(0, 60, 5)],
    }
    bad = {"BeginDate": invalid.get("begin", str(start)), key: invalid.get("value", 999.),
           "Location": {"@LocId": invalid.get("location", location)}}
    good[kind].append(bad)
    monkeypatch.setattr(provider, "_fetch_day_cached", lambda name, day: (name, day, good[name]))

    frames = provider._market_frames_for_range(date(2026, 1, 31), date(2026, 1, 31), date(2026, 1, 31))

    assert frames["pv"].loc[start, "pv_mw"] == 800.
    assert frames["load"].loc[start + pd.Timedelta(hours=1), "load"] == 8000.
    expected = 16000. if kind == "da_demand" else -15.
    assert frames[kind][kind].tolist() == [expected]
    assert np.isfinite(frames[kind][kind]).all()


@pytest.mark.parametrize("kind,key,location", [
    ("da_demand", "Load", 32), ("da_lmp", "LmpTotal", 4000),
])
def test_all_invalid_day_ahead_data_remains_missing(monkeypatch, kind, key, location):
    provider = TFRealtimeFeatureProvider()
    monkeypatch.setattr(provider, "_fill_rt_lmp_gaps_from_five_minute", lambda frame: frame)
    bad = {"BeginDate": "2026-01-31T23:00:00", key: "unavailable", "Location": {"@LocId": location}}
    monkeypatch.setattr(provider, "_fetch_day_cached", lambda name, day: (name, day, [bad] if name == kind else []))

    frames = provider._market_frames_for_range(date(2026, 1, 31), date(2026, 1, 31), date(2026, 1, 31))

    assert frames[kind].empty
    assert isinstance(frames[kind].index, pd.DatetimeIndex)
    with pytest.raises(ValueError, match="不完整"):
        provider._require_contiguous(frames[kind].reset_index(), "ts_local", pd.Timestamp("2026-02-01"), 24, "日前特征")
