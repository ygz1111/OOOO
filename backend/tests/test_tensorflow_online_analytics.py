"""Regression tests for TensorFlow-only online accuracy statistics.

These tests use no model weights, database, or network.  They ensure that the
analytics layer does not fall back to a retired ``ensemble`` record label
when TensorFlow is the active production engine.
"""

from datetime import datetime
from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from realtime_api.routers import analytics


@pytest.mark.parametrize("value", ["2026-09-22T13:00:00Z", "2026-09-22T09:00:00-04:00", "2026-09-22T09:00:00"])
def test_analytics_normalizes_offsets_before_removing_timezone(value):
    assert analytics._as_naive_datetime(value) == datetime(2026, 9, 22, 9)


@pytest.mark.asyncio
async def test_online_accuracy_reads_only_active_tf_model_and_returns_window_metadata(monkeypatch):
    seen = {}

    async def fake_get_predictions(**kwargs):
        seen.update(kwargs)
        return [
            {"load_forecast_mw": 100.0, "actual_load_mw": 110.0},
            {"load_forecast_mw": 130.0, "actual_load_mw": 100.0},
        ]

    monkeypatch.setattr(analytics, "tf_load_backend_active", lambda: True)
    monkeypatch.setattr(analytics, "eastern_now_hour", lambda: datetime(2026, 9, 7, 12))
    monkeypatch.setattr(
        analytics.LoadPredictionsCRUD,
        "get_predictions_by_time_range",
        fake_get_predictions,
    )

    result = await analytics._compute_accuracy_from_db(hours=24 * 30)

    assert seen["model_type"] == "tf_split_v1"
    assert seen["dedupe_target"] is False  # Keep vintages for lead-time groups; overall still dedupes.
    assert result["model_type"] == "tf_split_v1"
    assert result["window_hours"] == 720
    assert result["count"] == 2
    assert result["mae"] == pytest.approx(20.0)
    assert result["mape"] == pytest.approx((10 / 110 + 30 / 100) / 2 * 100)


@pytest.mark.asyncio
async def test_active_records_keep_tensorflow_label_when_service_is_temporarily_unready(monkeypatch):
    seen = {}

    async def fake_get_predictions(**kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(analytics, "tf_load_backend_active", lambda: False)
    monkeypatch.setattr(
        analytics.LoadPredictionsCRUD,
        "get_predictions_by_time_range",
        fake_get_predictions,
    )

    await analytics._get_active_prediction_records(datetime(2026, 9, 1), datetime(2026, 9, 2))

    assert seen["model_type"] == "tf_split_v1"
    assert seen["dedupe_target"] is True


@pytest.mark.asyncio
async def test_prediction_crud_excludes_after_the_fact_records_by_default(monkeypatch):
    from realtime_api.crud import core

    captured = {}

    async def fake_execute_sql(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return []

    monkeypatch.setattr(core.db_manager, "execute_sql", fake_execute_sql)

    await core.LoadPredictionsCRUD.get_predictions_by_time_range(
        datetime(2026, 9, 17),
        datetime(2026, 9, 22),
        model_type="tf_split_v1",
        dedupe_target=True,
    )

    assert "prediction_timestamp < target_timestamp" in captured["sql"]
    assert captured["params"] == (
        datetime(2026, 9, 17),
        datetime(2026, 9, 22),
        "tf_split_v1",
    )
