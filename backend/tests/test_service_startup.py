"""Production startup uses each TensorFlow model's own frozen scaler contract."""

from unittest.mock import Mock

import pytest

from realtime_api.services import container
from realtime_api.feature_generator import FeatureGenerator
from realtime_api.normalization_adapter import NormalizationAdapter


def test_startup_does_not_require_unused_legacy_processed_assets(monkeypatch):
    def legacy_asset_access(*args, **kwargs):
        raise AssertionError("Production must not load legacy processed/*.pkl")

    monkeypatch.setattr(FeatureGenerator, "__init__", legacy_asset_access)
    monkeypatch.setattr(NormalizationAdapter, "__init__", legacy_asset_access)
    monkeypatch.setattr(container, "services", container.ServiceContainer())
    monkeypatch.setattr(container, "tf_engines_enabled", lambda: False)
    monkeypatch.setattr(container, "OpenMeteoClient", Mock())
    container.init_services()
    assert container.services.openmeteo_client is not None
    assert container.services.weather_validator is not None


def test_missing_selected_model_still_stops_strict_startup(monkeypatch):
    from realtime_api.tf_split_service import TFSplitService

    def missing_weights(_self):
        raise FileNotFoundError("load_best.weights.h5")

    monkeypatch.setattr(container, "services", container.ServiceContainer())
    monkeypatch.setattr(container, "OpenMeteoClient", Mock())
    monkeypatch.setattr(container, "tf_engines_enabled", lambda: True)
    monkeypatch.setattr(container, "get_engine_config", lambda: {"strict_startup": True})
    monkeypatch.setattr(TFSplitService, "load_models", missing_weights)
    with pytest.raises(RuntimeError, match="load_best.weights.h5"):
        container.init_services()
