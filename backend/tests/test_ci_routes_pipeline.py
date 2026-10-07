"""Prediction pipeline contracts with deterministic service doubles, no model writes."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from realtime_api.services import prediction_pipeline as pipeline

NOW = datetime(2026, 10, 7, 12)
FEATURES = {"past": [[1]], "future": [[2]]}


@pytest.fixture
def model_services(monkeypatch):
    load_result = {"hourly": [{"hour": (NOW + timedelta(hours=i + 1)).hour, "timestamp": (NOW + timedelta(hours=i + 1)).isoformat(),
        "load_forecast_mw": 12000 + i, "price_p10": 10, "price_p50": 20, "price_p90": 30} for i in range(24)],
        "inference_time_ms": 100, "data_source": "fixture", "origin": NOW.isoformat()}
    pv_result = {"hourly_pv_mw": [1000] * 24, "timestamps": [(NOW + timedelta(hours=i)).isoformat() for i in range(24)]}
    load = Mock(MODEL_NAME="tf_load_split_v1")
    load.predict_features.return_value = load_result
    load.predict.return_value = load_result
    load.get_model_info.return_value = {"load": {"loaded": True, "num_params": 100, "weight": 1}, "price": {}}
    pv = Mock(MODEL_NAME="pv_v2")
    pv.predict_features.return_value = pv_result
    pv.predict.return_value = pv_result
    pv.get_model_info.return_value = {"pv": {}}
    provider = Mock()
    provider.build.return_value = {"load_price": FEATURES, "pv": FEATURES, "data_source": "real_source",
        "input_quality": {"status": "complete"}, "origin_hour_end": NOW.isoformat()}
    monkeypatch.setattr(pipeline.services, "tf_load_price_service", load)
    monkeypatch.setattr(pipeline.services, "tf_pv_service", pv)
    monkeypatch.setattr(pipeline.services, "tf_realtime_feature_provider", provider)
    monkeypatch.setattr(pipeline, "tf_load_backend_active", lambda: True)
    monkeypatch.setattr(pipeline, "tf_pv_backend_active", lambda: True)
    monkeypatch.setattr(pipeline, "get_engine_config", lambda: {"inference_mode": "live"})
    monkeypatch.setattr(pipeline, "eastern_now", lambda: NOW)
    return load, pv, provider


def test_request_data_conversion_preserves_optional_fields_and_timestamp():
    point = SimpleNamespace(timestamp=NOW, temperature_2m=12, dew_point_2m=6,
        relative_humidity_2m=60, wind_speed_10m=None, cloud_cover=30, shortwave_radiation=100)
    frame = pipeline.weather_points_to_df([point])
    assert frame.iloc[0].temperature_2m == 12
    assert frame.iloc[0].timestamp == NOW
    assert "wind_speed_10m" not in frame.columns
    load = pipeline.load_points_to_df([SimpleNamespace(timestamp=NOW, system_load=12000)])
    assert load.System_Load.tolist() == [12000]


@pytest.mark.parametrize("mode", ["live", "demo"])
def test_aligned_outputs_net_load_and_model_inventory(model_services, monkeypatch, mode):
    monkeypatch.setattr(pipeline, "get_engine_config", lambda: {"inference_mode": mode})
    response = pipeline.dispatch_prediction(pd.DataFrame(), tf_load_price_features=FEATURES if mode == "live" else None,
        tf_pv_features=FEATURES if mode == "live" else None)
    assert len(response.predictions) == 24
    assert response.predictions[0].net_load_mw == 11000
    assert response.predictions[-1].timestamp == (NOW + timedelta(hours=24)).isoformat()
    assert response.predictions[0].price_p50 == 20
    assert len(response.model_info) == 3
    assert response.inference_time_ms >= 100
    if mode == "demo":
        model_services[0].predict.assert_called_once()
        model_services[1].predict.assert_called_once()
    else:
        model_services[0].predict_features.assert_called_once_with([[1]], [[2]])


def test_live_missing_features_are_prepared_once_with_provenance(model_services):
    frame = pd.DataFrame({"temperature_2m": [12]})
    response = pipeline.run_tf_prediction_pipeline(frame)
    model_services[2].build.assert_called_once_with(frame)
    assert response.data_source == "real_source"
    assert response.input_quality == {"status": "complete"}
    assert response.origin == NOW.isoformat()


def test_live_shared_snapshot_path_avoids_independent_model_inference(model_services, monkeypatch):
    from realtime_api.services import live_forecast
    snapshot = object()
    expected = object()
    monkeypatch.setattr(live_forecast, "get_live_snapshot", lambda: snapshot)
    convert = Mock(return_value=expected)
    monkeypatch.setattr(live_forecast, "snapshot_response", convert)
    assert pipeline.run_tf_prediction_pipeline() is expected
    convert.assert_called_once_with(snapshot)
    model_services[0].predict.assert_not_called()


@pytest.mark.parametrize("backend,error", [("tf_load_backend_active", "负荷与电价"), ("tf_pv_backend_active", "光伏模型")])
def test_unready_backend_reports_component(model_services, monkeypatch, backend, error):
    monkeypatch.setattr(pipeline, backend, lambda: False)
    with pytest.raises(RuntimeError, match=error):
        pipeline.run_tf_prediction_pipeline(pd.DataFrame())


def test_live_provider_absence_is_explicit(model_services, monkeypatch):
    monkeypatch.setattr(pipeline.services, "tf_realtime_feature_provider", None)
    with pytest.raises(RuntimeError, match="实时特征服务未初始化"):
        pipeline.run_tf_prediction_pipeline(pd.DataFrame())


@pytest.mark.parametrize("component", ["load_price", "pv"])
def test_incomplete_live_feature_bundle_does_not_create_fake_prediction(model_services, component):
    model_services[2].build.return_value[component] = None
    with pytest.raises((ValueError, RuntimeError), match="缺少.*特征"):
        pipeline.run_tf_prediction_pipeline(pd.DataFrame())


@pytest.mark.parametrize("component", ["load", "pv"])
def test_short_model_output_is_rejected(model_services, component):
    if component == "load":
        model_services[0].predict_features.return_value["hourly"] = []
    else:
        model_services[1].predict_features.return_value["hourly_pv_mw"] = []
    with pytest.raises(RuntimeError, match="输出异常"):
        pipeline.run_tf_prediction_pipeline(tf_load_price_features=FEATURES, tf_pv_features=FEATURES)


def test_pv_failure_keeps_original_cause(model_services):
    original = ValueError("invalid shape")
    model_services[1].predict_features.side_effect = original
    with pytest.raises(RuntimeError, match="光伏在线预测失败") as exc:
        pipeline.run_tf_prediction_pipeline(tf_load_price_features=FEATURES, tf_pv_features=FEATURES)
    assert exc.value.__cause__ is original


def test_hour_start_pv_and_hour_end_load_must_match_exactly(model_services):
    model_services[1].predict_features.return_value["timestamps"][0] = (NOW + timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError, match="预测窗口不一致"):
        pipeline.run_tf_prediction_pipeline(tf_load_price_features=FEATURES, tf_pv_features=FEATURES)
