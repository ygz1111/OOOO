from pathlib import Path

import numpy as np
import pandas as pd

from realtime_api.tf_pv_v2_service import TFPVV2Service
from realtime_api.tf_realtime_feature_provider import TFRealtimeFeatureProvider


BACKEND = Path(__file__).resolve().parents[1]


def test_pv_v2_frozen_tail_prediction_is_valid():
    service = TFPVV2Service()
    service.load_models()
    result = service.predict()
    assert result["model_type"] == "tf_pv_v2"
    assert len(result["hourly_pv_mw"]) == 24
    assert len(result["timestamps"]) == 24
    assert np.isfinite(result["hourly_pv_mw"]).all()
    assert min(result["hourly_pv_mw"]) >= 0
    assert result["peak_mw"] > 0


def test_pv_weather_maps_six_stations_to_eight_zones():
    locations = ["Boston", "Manchester", "Hartford", "Portland", "Providence", "Burlington"]
    rows = []
    for timestamp in pd.date_range("2026-09-10", periods=2, freq="h"):
        for offset, location in enumerate(locations):
            rows.append({
                "timestamp": timestamp,
                "location": location,
                "temperature_2m": 20 + offset,
                "dew_point_2m": 10 + offset,
                "cloud_cover": 30 + offset,
                "shortwave_radiation": 100 + offset,
            })
    result = TFRealtimeFeatureProvider._pv_weather(pd.DataFrame(rows))
    expected = {
        *(f"ghi_{zone}" for zone in ("ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA")),
        *(f"cloud_{zone}" for zone in ("ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA")),
        "temp_mean", "dew_mean",
    }
    assert expected.issubset(result.columns)
    assert len(result) == 2
    assert not result.isna().any().any()
