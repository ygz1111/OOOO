from datetime import datetime, timedelta

import pytest

from realtime_api.routers import analytics


def _row(ts, forecast, actual, model="tf_split_v1", prediction_time=None):
    return {
        "id": 1,
        "target_timestamp": ts,
        "prediction_timestamp": prediction_time or ts,
        "load_forecast_mw": forecast,
        "actual_load_mw": actual,
        "model_type": model,
        "inference_time_ms": 100.0,
        "data_source": "test",
    }


@pytest.mark.asyncio
async def test_error_distribution_uses_forecast_minus_actual(monkeypatch):
    rows = [
        _row(datetime(2026, 9, 12, 1), 120.0, 100.0),
        _row(datetime(2026, 9, 12, 2), 110.0, 100.0),
    ]

    async def fake_records(*args, **kwargs):
        return rows

    monkeypatch.setattr(analytics, "_get_active_prediction_records", fake_records)
    result = await analytics.analyze_error_distribution(days=1)
    data = result["data"]

    assert data["mean_error"] == pytest.approx(15.0)
    assert data["bias"] == "over_predict"
    assert data["max_absolute_error"] == pytest.approx(20.0)
    assert data["error_definition"] == "forecast_minus_actual"


@pytest.mark.asyncio
async def test_hourly_trends_exact_window_and_paired_average(monkeypatch):
    now = datetime(2026, 9, 12, 23)
    captured = {}
    rows = [
        _row(now - timedelta(hours=1), 120.0, 100.0),
        _row(now, 300.0, None),
    ]

    async def fake_records(start_time, end_time, **kwargs):
        captured["start"] = start_time
        captured["end"] = end_time
        return rows

    monkeypatch.setattr(analytics, "eastern_now_hour", lambda: now)
    monkeypatch.setattr(analytics, "_get_active_prediction_records", fake_records)
    result = await analytics.analyze_temporal_trends(time_window="hourly", days=1)
    trends = result["data"]["trends"]

    assert captured["start"] == now - timedelta(hours=23)
    assert len(trends) == 2
    assert trends[0]["time_label"] == "09-12 22:00"
    assert trends[0]["predicted_load"] == pytest.approx(120.0)
    assert trends[0]["actual_load"] == pytest.approx(100.0)
    assert trends[0]["error"] == pytest.approx(20.0)
    assert trends[1]["actual_load"] is None


@pytest.mark.asyncio
async def test_weekly_trends_group_by_calendar_week(monkeypatch):
    rows = [
        _row(datetime(2026, 9, 1), 105.0, 100.0),
        _row(datetime(2026, 9, 8), 110.0, 100.0),
    ]

    async def fake_records(*args, **kwargs):
        return rows

    monkeypatch.setattr(analytics, "_get_active_prediction_records", fake_records)
    result = await analytics.analyze_temporal_trends(time_window="weekly", days=30)

    assert [point["time_label"] for point in result["data"]["trends"]] == ["08-31周", "09-07周"]


@pytest.mark.asyncio
async def test_drift_improvement_does_not_raise_alarm(monkeypatch):
    start = datetime(2026, 9, 1)
    rows = []
    for index in range(100):
        error = 10.0 if index < 70 else 5.0
        rows.append(_row(start + timedelta(hours=index), 100.0 + error, 100.0))

    async def fake_records(*args, **kwargs):
        return rows

    monkeypatch.setattr(analytics, "_get_active_prediction_records", fake_records)
    result = await analytics.check_model_drift(monitoring_service=None)
    data = result["data"]

    assert data["drift_detected"] is False
    assert data["drift_score"] == 0.0
    assert data["drift_direction"] == "improved"
    assert data["change_percent"] == pytest.approx(-50.0)


@pytest.mark.asyncio
async def test_model_comparison_uses_common_target_hours(monkeypatch):
    target1 = datetime(2026, 9, 12, 1)
    target2 = datetime(2026, 9, 12, 2)
    target3 = datetime(2026, 9, 12, 3)
    generated = datetime(2026, 9, 12, 0)
    rows = [
        _row(target1, 110.0, 100.0, "a", generated),
        _row(target2, 120.0, 100.0, "a", generated),
        _row(target2, 90.0, 100.0, "b", generated),
        _row(target3, 70.0, 100.0, "b", generated),
    ]

    class FakeDatabase:
        async def execute_sql(self, sql, params):
            return rows

    monkeypatch.setattr(analytics, "eastern_now", lambda: datetime(2026, 9, 12, 4))
    monkeypatch.setattr(analytics, "_active_load_model_type", lambda: "a")
    result = await analytics.compare_models(hours=24, db_manager=FakeDatabase())

    assert result["data"]["a"]["metric_count"] == 1
    assert result["data"]["b"]["metric_count"] == 1
    assert result["data"]["a"]["mae"] == pytest.approx(20.0)
    assert result["data"]["b"]["mae"] == pytest.approx(10.0)
    assert result["data"]["a"]["lifecycle"] == "active"
    assert result["data"]["b"]["lifecycle"] == "archived"
