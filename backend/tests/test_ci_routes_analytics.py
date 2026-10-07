"""Read-only analytics routes: paired samples, unavailable observations and failures."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
import pytest

from realtime_api.routers import analytics as api

NOW = datetime(2026, 10, 7, 12)


@pytest.fixture
def dependencies(monkeypatch):
    records = AsyncMock(return_value=[])
    database = SimpleNamespace(execute_sql=AsyncMock(return_value=[]))
    monitor = Mock()
    monitor.data_quality_monitor.get_quality_stats.return_value = {"total": 3}
    monitor.validate_data_quality.return_value = {"is_valid": True}
    analytics = Mock()
    analytics.analyze_load_patterns.return_value = {"peak_hour": 12}
    analytics.generate_comprehensive_report.return_value = {"count": 1}
    monkeypatch.setattr(api, "eastern_now", lambda: NOW)
    monkeypatch.setattr(api, "eastern_now_hour", lambda: NOW)
    monkeypatch.setattr(api, "_get_active_prediction_records", records)
    monkeypatch.setattr(api, "selected_load_backend", lambda: "tf_load_split_v1")
    return records, database, monitor, analytics


def row(offset=0, actual=1000, forecast=1100):
    return {"id": offset + 1, "prediction_timestamp": NOW - timedelta(hours=48),
        "target_timestamp": NOW - timedelta(hours=offset), "actual_load_mw": actual,
        "load_forecast_mw": forecast, "model_type": "tf_load_split_v1", "inference_time_ms": 12,
        "data_source": "iso_ne+open_meteo"}


def test_time_parser_converts_aware_timestamps_and_rejects_invalid():
    assert api._as_naive_datetime(datetime(2026, 10, 7, 16, tzinfo=timezone.utc)) == NOW
    assert api._as_naive_datetime("2026-10-07T16:00:00Z") == NOW
    assert api._as_naive_datetime("invalid") is None
    assert api._as_naive_datetime(None) is None
    assert api._window_start(NOW, 1) == NOW


@pytest.mark.asyncio
@pytest.mark.parametrize("name,builder", [("get_operation_situation", "build_operation_situation"),
    ("get_feature_sensitivity", "build_feature_sensitivity")])
async def test_operation_routes_keep_service_payload_and_status(monkeypatch, name, builder):
    build = AsyncMock(return_value={"available": False})
    monkeypatch.setattr(api, builder, build)
    assert (await getattr(api, name)())["data"] == {"available": False}
    for error, status in [(RuntimeError("preparing"), 503), (ValueError("bad data"), 500)]:
        build.side_effect = error
        with pytest.raises(HTTPException) as exc:
            await getattr(api, name)()
        assert exc.value.status_code == status


@pytest.mark.asyncio
async def test_backtest_range_date_and_service_errors(monkeypatch):
    build = AsyncMock(return_value={"dates": []})
    monkeypatch.setattr(api, "generate_day_backtest", build)
    assert (await api.get_day_backtest(None, False))["data"] == {"dates": []}
    build.assert_awaited_once_with(None)
    build.reset_mock()
    selected = date(2026, 10, 6)
    await api.get_day_backtest(selected, True)
    build.assert_awaited_once_with(selected, force_refresh=True)
    for error, status in [(ValueError("invalid date"), 400), (RuntimeError("missing inputs"), 503), (OSError("offline"), 500)]:
        build.side_effect = error
        with pytest.raises(HTTPException) as exc:
            await api.get_day_backtest(selected, False)
        assert exc.value.status_code == status


@pytest.mark.asyncio
async def test_hourly_diagnostics_include_zero_actual_without_percentage_error(dependencies):
    dependencies[0].return_value = [row(0, 0, 100), row(1, 1000, 1100), row(2, None)]
    result = (await api.get_hourly_error_diagnostics(7))["data"]
    assert result["sample_count"] == 2
    assert len(result["hourly"]) == 24
    assert result["hourly"][12]["mape"] is None
    assert result["hourly"][11]["bias_mw"] == 100
    assert result["hourly"][10]["mae_mw"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("window", ["hourly", "daily", "weekly"])
async def test_trends_pair_by_row_and_ignore_missing_real_values(dependencies, window):
    dependencies[0].return_value = [row(2, 1000, 1100), row(1, None, 9000), row(0, 0, 10),
                                   {"target_timestamp": "invalid", "load_forecast_mw": None}]
    result = (await api.analyze_temporal_trends(window, 7))["data"]
    assert result["summary"]["paired_records"] == 2
    assert result["summary"]["overall_mape"] == pytest.approx(10)
    assert result["summary"]["avg_predicted_load"] == 555
    assert all(point["paired_count"] <= point["prediction_count"] for point in result["trends"])
    with pytest.raises(HTTPException) as exc:
        await api.analyze_temporal_trends("monthly", 7)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("forecast,expected", [(1200, "over_predict"), (800, "under_predict"), (1000, "balanced")])
async def test_error_distribution_direction_and_count(dependencies, forecast, expected):
    dependencies[0].return_value = [row(0, 1000, forecast), row(1, None, 9000)]
    result = (await api.analyze_error_distribution(7))["data"]
    assert result["sample_count"] == 1
    assert result["bias"] == expected
    assert result["mean_error"] == forecast - 1000
    assert sum(item["count"] for item in result["histogram"]) == 1


@pytest.mark.asyncio
async def test_quality_results_include_issues_and_do_not_turn_errors_into_valid(dependencies):
    monitor = dependencies[2]
    assert (await api.get_data_quality_stats(monitor))["data"] == {"total": 3}
    assert "良好" in (await api.validate_weather_data({"temperature_2m": 12}, monitor))["message"]
    monitor.validate_data_quality.return_value = {"is_valid": False, "issues": ["missing humidity"]}
    assert "1 个质量问题" in (await api.validate_weather_data({}, monitor))["message"]
    monitor.validate_data_quality.side_effect = RuntimeError("validator offline")
    with pytest.raises(HTTPException) as exc:
        await api.validate_weather_data({}, monitor)
    assert exc.value.status_code == 500
    monitor.data_quality_monitor.get_quality_stats.side_effect = RuntimeError("stats offline")
    with pytest.raises(HTTPException):
        await api.get_data_quality_stats(monitor)


@pytest.mark.asyncio
async def test_report_patterns_dashboard_only_use_available_observations(dependencies):
    records, database, monitor, analytics = dependencies
    records.return_value = [row(0), row(1, None)]
    assert (await api.analyze_load_patterns(7, database, analytics))["data"] == {"peak_hour": 12}
    assert analytics.analyze_load_patterns.call_args.args[0] == [row(0)]
    assert (await api.generate_comprehensive_report(7, database, analytics))["data"] == {"count": 1}
    dashboard = (await api.get_dashboard_metrics(24, monitor, database, analytics))["data"]
    assert dashboard["system_status"] == "operational"
    assert dashboard["recent_analysis"]["recent_with_actual_count"] == 1


@pytest.mark.asyncio
async def test_recent_and_prediction_actual_serialize_and_order_same_hour(dependencies):
    database = dependencies[1]
    database.execute_sql.return_value = [row(0), row(1, 0, 10)]
    recent = (await api.get_recent_predictions(12, database))["data"]
    assert recent[0]["target_timestamp"] == NOW.isoformat()
    result = (await api.prediction_vs_actual(12, database))["data"]
    assert result["pairs"][0]["target_timestamp"] == (NOW - timedelta(hours=1)).isoformat()
    assert result["pairs"][0]["percentage_error"] is None
    assert result["summary"]["mape"] == 10
    assert result["summary"]["mae_mw"] == 55


@pytest.mark.asyncio
async def test_model_comparison_uses_only_common_observed_hours(dependencies):
    database = dependencies[1]
    database.execute_sql.return_value = [row(0), {**row(0, 1000, 1200), "model_type": "archived"},
        row(1), {"target_timestamp": None, "model_type": "ignored"}]
    result = (await api.compare_models(24, database))["data"]
    assert result["tf_load_split_v1"]["metric_count"] == 1
    assert result["tf_load_split_v1"]["mape"] == 10
    assert result["archived"]["lifecycle"] == "archived"
    assert result["archived"]["mape"] == 20
    database.execute_sql.return_value = [row(0), {**row(1), "model_type": "archived"}]
    result = (await api.compare_models(24, database))["data"]
    assert all(item["mape"] is None for item in result.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("baseline_error,recent_error,direction,drift", [(100, 200, "degraded", True),
    (200, 100, "improved", False), (100, 100, "stable", False), (0, 100, "stable", False)])
async def test_drift_only_alerts_for_deterioration(dependencies, baseline_error, recent_error, direction, drift):
    records = []
    for i in range(30):
        error = baseline_error if i < 21 else recent_error
        records.append(row(30 - i, 1000, 1000 + error))
    dependencies[0].return_value = records
    result = (await api.check_model_drift(dependencies[2]))["data"]
    assert result["sample_count"] == 30
    assert result["drift_direction"] == direction
    assert result["drift_detected"] == drift
    if not drift:
        assert result["drift_score"] <= result["threshold"]


@pytest.mark.asyncio
async def test_drift_rejects_invalid_timestamp_or_numeric_value(dependencies):
    dependencies[0].return_value = [row(i) for i in range(22)] + [
        {**row(23), "target_timestamp": "bad date"}, {**row(24), "load_forecast_mw": "invalid"}]
    result = (await api.check_model_drift(dependencies[2]))["data"]
    assert result["sample_count"] == 22
    assert result["drift_direction"] == "insufficient_data"
    dependencies[0].return_value = [row(i, 0, 0) for i in range(30)]
    result = (await api.check_model_drift(dependencies[2]))["data"]
    assert result["baseline_mape"] == 0
    assert result["recent_mape"] == 0
    assert result["drift_detected"] is False


@pytest.mark.asyncio
async def test_zero_actuals_have_no_spurious_accuracy_or_trend_percentages(dependencies):
    dependencies[0].return_value = [row(0, 0, 10), row(1, 0, 5)]
    stats = await api._compute_accuracy_from_db(24)
    assert stats["mae"] == 7.5
    assert stats["r2"] == 0
    assert stats["mape"] == 0
    trends = (await api.analyze_temporal_trends("daily", 7))["data"]
    assert trends["trends"][0]["mape"] == 0
    assert "overall_mape" not in trends["summary"]
    dependencies[0].return_value = [row(0, None, 10)]
    dashboard = (await api.get_dashboard_metrics(24, dependencies[2], dependencies[1], dependencies[3]))["data"]
    assert dashboard["recent_analysis"] == {}


@pytest.mark.asyncio
async def test_zero_actual_comparison_keeps_mape_unavailable(dependencies):
    dependencies[1].execute_sql.return_value = [row(0, 0, 10)]
    compare = (await api.compare_models(24, dependencies[1]))["data"]["tf_load_split_v1"]
    assert compare["mape"] is None
    assert compare["mae"] == 10
    result = (await api.prediction_vs_actual(24, dependencies[1]))["data"]
    assert result["summary"]["mape"] is None


CALLS = [
    ("get_hourly_error_diagnostics", lambda d: (7,)),
    ("get_accuracy_stats", lambda d: (7, d[2])),
    ("check_model_drift", lambda d: (d[2],)),
    ("analyze_temporal_trends", lambda d: ("daily", 7)),
    ("analyze_error_distribution", lambda d: (7,)),
    ("analyze_load_patterns", lambda d: (7, d[1], d[3])),
    ("generate_comprehensive_report", lambda d: (7, d[1], d[3])),
    ("get_dashboard_metrics", lambda d: (24, d[2], d[1], d[3])),
    ("get_recent_predictions", lambda d: (12, d[1])),
    ("compare_models", lambda d: (24, d[1])),
    ("prediction_vs_actual", lambda d: (12, d[1])),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args", CALLS)
async def test_empty_analytics_is_success_with_no_fabricated_metrics(dependencies, name, args):
    result = await getattr(api, name)(*args(dependencies))
    assert result["status"] == "success"
    if name == "get_dashboard_metrics":
        assert result["data"]["system_status"] == "warning"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args", CALLS)
async def test_analytics_database_failure_is_explicit_and_retry_recovers(dependencies, name, args):
    dependencies[0].side_effect = RuntimeError("database unavailable")
    dependencies[1].execute_sql.side_effect = RuntimeError("database unavailable")
    with pytest.raises(HTTPException) as exc:
        await getattr(api, name)(*args(dependencies))
    assert exc.value.status_code == 500
    assert "database unavailable" in str(exc.value.detail)
    dependencies[0].side_effect = None
    dependencies[1].execute_sql.side_effect = None
    assert (await getattr(api, name)(*args(dependencies)))["status"] == "success"
