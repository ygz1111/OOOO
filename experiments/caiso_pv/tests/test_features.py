import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from features import build_weather_features, calendar_solar_features
from weather_data import SITES, TIMEZONE, VARIABLES


def test_nrel_spa_california_noon_is_day_and_midnight_is_night_in_each_season():
    times = pd.DatetimeIndex(pd.to_datetime(["2024-06-21T00:00:00-07:00", "2024-06-21T12:00:00-07:00",
                             "2024-12-21T00:00:00-08:00", "2024-12-21T12:00:00-08:00"], utc=True))
    frame = calendar_solar_features(times)
    assert frame.sun_up_any.tolist() == [0, 1, 0, 1]
    assert (frame.loc[times[[1,3]], "coszen_mean"] > 0).all()
    assert np.isfinite(frame.to_numpy()).all()


@pytest.mark.parametrize("day,hours", [("2024-03-10",23), ("2024-11-03",25)])
def test_dst_days_keep_all_physical_hours_with_local_calendar_features(day, hours):
    begin = pd.Timestamp(day).tz_localize(TIMEZONE)
    end = (pd.Timestamp(day)+pd.Timedelta(days=1)).tz_localize(TIMEZONE)
    axis = pd.date_range(begin.tz_convert("UTC"), end.tz_convert("UTC"), inclusive="left", freq="h")
    frame = calendar_solar_features(axis)
    assert len(frame) == hours
    assert frame.index.is_unique
    if hours == 25:
        repeated = frame[frame.index.tz_convert(TIMEZONE).hour == 1]
        assert len(repeated) == 2
        assert repeated.hour_sin.nunique() == 1


def test_missing_site_cannot_be_hidden_by_skipna_regional_mean():
    axis = pd.date_range("2024-06-01T00:00Z", periods=2, freq="h")
    rows = []
    for time in axis:
        for site in SITES:
            if time == axis[-1] and site == SITES[-1]:
                continue
            rows.append({"interval_start_utc": time, "interval_end_utc": time+pd.Timedelta(hours=1),
                "site_id": site.site_id, "source_kind": "historical_reanalysis", "model": "era5",
                "batch_id": "reanalysis", "availability_upper_bound_utc": pd.NaT, "availability_basis": "retrospective",
                **{v: 10 for v in VARIABLES}})
    table = build_weather_features(pd.DataFrame(rows))
    assert table.frame.complete_weather.tolist() == [True,False]
    assert np.isnan(table.frame.shortwave_radiation__mean.iloc[-1])
    assert len(table.feature_names) == 35
