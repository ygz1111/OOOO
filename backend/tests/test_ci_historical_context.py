"""Legacy historical-context fallback is explicitly tested without reading real training assets."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, mock_open

import pandas as pd
import pytest

from realtime_api import historical_load_provider as history
from realtime_api.services import container

NOW = datetime(2026, 10, 7, 12, 30)


@pytest.fixture
def inputs(monkeypatch):
    actual = AsyncMock(return_value=[])
    predicted = AsyncMock(return_value=[])
    monkeypatch.setattr(history.ActualLoadDataCRUD, "get_actual_load_by_time_range", actual)
    monkeypatch.setattr(history.LoadPredictionsCRUD, "get_predictions_by_time_range", predicted)
    monkeypatch.setattr(container, "eastern_now", lambda: NOW)
    monkeypatch.setattr(container, "selected_load_backend", lambda: "tf_load_split_v1")
    return actual, predicted


@pytest.mark.asyncio
async def test_actual_values_take_priority_latest_prediction_only_fills_missing_hours(inputs):
    h = NOW.replace(minute=0)
    inputs[0].return_value = [{"timestamp": h - timedelta(hours=3), "actual_load_mw": 12000},
                              {"timestamp": h - timedelta(hours=1), "actual_load_mw": 14000}]
    inputs[1].return_value = [
        {"target_timestamp": h - timedelta(hours=3), "load_forecast_mw": 9999},
        {"target_timestamp": h - timedelta(hours=2), "prediction_timestamp": h - timedelta(hours=6), "load_forecast_mw": 12500},
        {"target_timestamp": h - timedelta(hours=2), "prediction_timestamp": h - timedelta(hours=5), "load_forecast_mw": 13000},
    ]
    result = await history.HistoricalLoadProvider.get_historical_load(hours=6)
    assert result.System_Load.tolist() == [12000, 13000, 14000]
    assert result.timestamp.tolist() == list(pd.date_range(h - timedelta(hours=3), periods=3, freq="h"))
    assert inputs[1].await_args.kwargs["dedupe_target"] is True
    assert inputs[0].await_args.args == (h - timedelta(hours=6), h)


@pytest.mark.asyncio
async def test_database_failure_uses_remaining_source_and_fills_gap(inputs):
    inputs[0].side_effect = RuntimeError("actual store offline")
    h = NOW.replace(minute=0)
    inputs[1].return_value = [{"target_timestamp": h - timedelta(hours=3), "load_forecast_mw": 12000},
                              {"target_timestamp": h - timedelta(hours=1), "load_forecast_mw": 14000}]
    result = await history.HistoricalLoadProvider.get_historical_load(NOW)
    assert result.System_Load.tolist() == [12000, 12000, 14000]


@pytest.mark.asyncio
async def test_no_data_and_both_stores_failed_use_fallback(inputs, monkeypatch):
    fallback = pd.DataFrame({"timestamp": [NOW], "System_Load": [12000]})
    monkeypatch.setattr(history.HistoricalLoadProvider, "_cold_start_fallback", lambda *args: fallback)
    assert (await history.HistoricalLoadProvider.get_historical_load()) is fallback
    inputs[0].side_effect = RuntimeError("offline")
    inputs[1].side_effect = RuntimeError("offline")
    assert (await history.HistoricalLoadProvider.get_historical_load()) is fallback


@pytest.mark.asyncio
async def test_malformed_join_falls_back(inputs, monkeypatch):
    inputs[0].return_value = [{"timestamp": NOW, "actual_load_mw": 12000}]
    monkeypatch.setattr(history.pd, "concat", lambda *args: (_ for _ in ()).throw(ValueError("bad timestamp")))
    monkeypatch.setattr(history.HistoricalLoadProvider, "_cold_start_fallback", lambda *args: None)
    assert await history.HistoricalLoadProvider.get_historical_load() is None


@pytest.mark.parametrize("frame", [None, pd.DataFrame(), pd.DataFrame({"System_Load": [10000, 11000, 12000]})])
def test_cold_start_remaps_only_requested_tail(monkeypatch, frame):
    monkeypatch.setattr(container, "eastern_now", lambda: NOW)
    monkeypatch.setattr(history.os.path, "exists", lambda _: True)
    monkeypatch.setattr("builtins.open", mock_open(read_data=b"fixture"))
    monkeypatch.setattr(history.pickle, "load", lambda _: frame)
    result = history.HistoricalLoadProvider._cold_start_fallback(hours=2)
    if frame is None or frame.empty:
        assert result is None
    else:
        assert result.System_Load.tolist() == [11000, 12000]
        assert result.timestamp.iloc[-1] == NOW.replace(minute=0) - timedelta(hours=1)


def test_cold_start_missing_file_or_corrupt_pickle_returns_none(monkeypatch):
    monkeypatch.setattr(history.os.path, "exists", lambda _: False)
    assert history.HistoricalLoadProvider._cold_start_fallback(NOW) is None
    monkeypatch.setattr(history.os.path, "exists", lambda _: True)
    monkeypatch.setattr("builtins.open", mock_open(read_data=b"fixture"))
    monkeypatch.setattr(history.pickle, "load", lambda _: (_ for _ in ()).throw(ValueError("corrupt")))
    assert history.HistoricalLoadProvider._cold_start_fallback(NOW) is None
