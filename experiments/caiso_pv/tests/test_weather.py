from datetime import date
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from weather_data import OpenMeteoClient, SITES, VARIABLES, normalize_weather


def payload(suffix=""):
    units = {"temperature_2m": "°C", "relative_humidity_2m": "%", "cloud_cover": "%",
             "wind_speed_10m": "m/s", "surface_pressure": "hPa"}
    units.update({v: "W/m²" for v in VARIABLES[3:7]})
    return {"utc_offset_seconds": 0, "hourly_units": {k + suffix: v for k, v in units.items()},
            "hourly": {"time": [1717243200, 1717246800], **{v + suffix: [1, 2] for v in VARIABLES}}}


def normalize(mode="previous_day2", **kwargs):
    return normalize_weather(payload("_previous_day2" if mode == "previous_day2" else ""),
        site=SITES[0], mode=mode, model="gfs_global", retrieved_at="2026-10-04T00:00Z",
        source_url="https://previous-runs-api.open-meteo.com/v1/forecast", **kwargs)


def test_radiation_is_the_preceding_physical_hour_and_day2_is_not_exact_issuance():
    frame = normalize()
    assert frame.interval_end_utc.iloc[0] - frame.interval_start_utc.iloc[0] == pd.Timedelta(hours=1)
    assert frame.availability_upper_bound_utc.iloc[0] == frame.interval_end_utc.iloc[0] - pd.Timedelta(hours=42)
    assert frame.issued_at_utc.isna().all()
    assert frame.run_initialization_utc.isna().all()
    assert frame.source_kind.eq("forecast_fixed_lead_day2").all()


def test_single_run_initialization_is_not_publication():
    frame = normalize("single_run", run_initialization="2024-06-01T00:00Z")
    assert frame.availability_upper_bound_utc.iloc[0] == pd.Timestamp("2024-06-01T06:00Z")
    assert frame.issued_at_utc.isna().all()
    assert frame.batch_id.nunique() == 1
    assert "assumed" in frame.availability_basis.iloc[0]


def test_verified_publication_is_retained_and_cannot_precede_initialization():
    frame = normalize("single_run", run_initialization="2024-06-01T00:00Z", published_at="2024-06-01T07:00Z")
    assert frame.issued_at_utc.iloc[0] == pd.Timestamp("2024-06-01T07:00Z")
    with pytest.raises(ValueError, match="precede"):
        normalize("single_run", run_initialization="2024-06-01T00:00Z", published_at="2024-05-31T23:00Z")


def test_null_variable_is_not_replaced_by_a_fake_night_zero():
    data = payload("_previous_day2")
    data["hourly"]["shortwave_radiation_previous_day2"][0] = None
    frame = normalize_weather(data, site=SITES[0], mode="previous_day2", model="gfs_global",
                              retrieved_at="2026-10-04T00:00Z", source_url="official")
    assert np.isnan(frame.shortwave_radiation.iloc[0])


def test_missing_variable_wrong_units_duplicate_or_naive_times_are_rejected():
    for mutate in (lambda d: d["hourly"].pop("cloud_cover_previous_day2"),
                   lambda d: d["hourly_units"].update({"wind_speed_10m_previous_day2": "km/h"}),
                   lambda d: d["hourly"].update({"time": [1717243200, 1717243200]})):
        data = payload("_previous_day2"); mutate(data)
        with pytest.raises(ValueError):
            normalize_weather(data, site=SITES[0], mode="previous_day2", model="gfs_global",
                              retrieved_at="2026-10-04T00:00Z", source_url="official")
    with pytest.raises(ValueError, match="naive"):
        normalize("single_run", run_initialization="2024-06-01T00:00")


def test_sample_client_refuses_bulk_dates_before_network_call():
    class NoNetwork:
        def get(self, *args, **kwargs):
            raise AssertionError("Must reject before a request")
    with pytest.raises(ValueError, match="one or two"):
        OpenMeteoClient(session=NoNetwork()).fetch_sample(site=SITES[0], start=date(2024,1,1),
            end=date(2024,1,31), mode="previous_day2", model="gfs_global")
