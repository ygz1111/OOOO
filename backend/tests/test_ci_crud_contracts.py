"""Database boundary contracts: parameterized SQL, causal labels and error propagation."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from realtime_api.crud import core
from realtime_api.services import container
from realtime_api.utils.iso_ne_intervals import ACTUAL_REGION, ACTUAL_SOURCE

NOW = datetime(2026, 10, 7, 12)


@pytest.fixture
def db(monkeypatch):
    query = AsyncMock(return_value=[{"id": 7}])
    insert = AsyncMock(return_value=7)
    monkeypatch.setattr(core.db_manager, "execute_sql", query)
    monkeypatch.setattr(core.db_manager, "execute_sql_insert", insert)
    monkeypatch.setattr(container, "eastern_now_hour", lambda: NOW)
    return query, insert


INSERT_CASES = [
    (core.WeatherDataCRUD.insert_weather_data, {"timestamp": NOW, "location": "Boston"}, "weather_data"),
    (core.LoadPredictionsCRUD.insert_prediction, {"prediction_timestamp": NOW, "target_timestamp": NOW + timedelta(hours=1), "load_forecast_mw": 12000, "model_weights": {"tf_load": 1}}, "load_predictions"),
    (core.ModelPerformanceCRUD.insert_performance, {"model_name": "tf_load"}, "model_performance"),
    (core.APILogsCRUD.insert_log, {"request_id": "req", "endpoint": "/api/health", "method": "GET"}, "api_request_logs"),
    (core.SystemMetricsCRUD.insert_metrics, {"cpu_percent": 42}, "system_metrics"),
    (core.CachePerformanceCRUD.insert_cache_metrics, {"cache_hits": 3, "cache_misses": 1}, "cache_performance"),
    (core.PerformanceAlertsCRUD.insert_alert, {"alert_type": "warning", "metric_name": "cpu"}, "performance_alerts"),
    (core.ActualLoadDataCRUD.insert_actual_load, {"timestamp": NOW, "actual_load_mw": 12000}, "actual_load_data"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,kwargs,table", INSERT_CASES)
async def test_insert_keeps_values_parameterized_and_returns_id(db, method, kwargs, table):
    assert await method(**kwargs) == 7
    sql, params = db[1].await_args.args
    assert table in sql
    assert sql.count("%s") == len(params)
    if table == "load_predictions":
        assert params[9] == '{"tf_load": 1}'
        assert "INSERT IGNORE" in sql
    if table == "weather_data":
        assert "ON DUPLICATE KEY UPDATE" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("method,kwargs,table", INSERT_CASES)
async def test_insert_failure_is_visible_to_caller(db, method, kwargs, table):
    db[1].side_effect = RuntimeError("database disconnected")
    with pytest.raises(RuntimeError, match="database disconnected"):
        await method(**kwargs)


QUERY_CASES = [
    (core.WeatherDataCRUD.get_weather_by_location_and_time, {"location": "Boston", "start_time": NOW - timedelta(hours=24), "end_time": NOW}, ("Boston", NOW - timedelta(hours=24), NOW)),
    (core.WeatherDataCRUD.get_latest_weather_data, {"location": "Boston", "limit": 12}, ("Boston", 12)),
    (core.LoadPredictionsCRUD.get_latest_predictions, {"limit": 12}, (12,)),
    (core.ModelPerformanceCRUD.get_performance_by_model, {"model_name": "tf_load", "hours": 6}, ("tf_load", NOW - timedelta(hours=6))),
    (core.APILogsCRUD.get_logs_by_endpoint, {"endpoint": "/api/health", "hours": 6, "limit": 12}, ("/api/health", NOW - timedelta(hours=6), 12)),
    (core.SystemMetricsCRUD.get_metrics, {"hours": 6, "limit": 12}, (NOW - timedelta(hours=6), 12)),
    (core.ActualLoadDataCRUD.get_actual_load_by_time_range, {"start_time": NOW - timedelta(hours=6), "end_time": NOW}, (NOW - timedelta(hours=6), NOW, ACTUAL_REGION, ACTUAL_SOURCE)),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,kwargs,expected", QUERY_CASES)
async def test_queries_forward_timezone_aligned_bounds(db, method, kwargs, expected):
    assert await method(**kwargs) == [{"id": 7}]
    assert db[0].await_args.args[1] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("method,kwargs,expected", QUERY_CASES)
async def test_query_disconnect_is_not_silent_empty_data(db, method, kwargs, expected):
    db[0].side_effect = RuntimeError("database disconnected")
    with pytest.raises(RuntimeError, match="database disconnected"):
        await method(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("dedupe,causal,model,descending,limit", [(True, True, "tf_load", True, 12), (False, False, None, False, None)])
async def test_prediction_query_selects_latest_causal_forecast(db, dedupe, causal, model, descending, limit):
    await core.LoadPredictionsCRUD.get_predictions_by_time_range(NOW - timedelta(hours=6), NOW, model, limit, descending, dedupe, causal)
    sql, params = db[0].await_args.args
    assert ("ROW_NUMBER()" in sql) == dedupe
    assert ("prediction_timestamp < target_timestamp" in sql) == causal
    assert ("model_type = %s" in sql) == bool(model)
    assert ("LIMIT 12" in sql) == (limit is not None)
    assert ("ORDER BY target_timestamp DESC" in sql) == descending
    assert params == ((NOW - timedelta(hours=6), NOW, model) if model else (NOW - timedelta(hours=6), NOW))


@pytest.mark.asyncio
async def test_prediction_query_failure_and_model_weights_decode(db):
    db[0].side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError):
        await core.LoadPredictionsCRUD.get_predictions_by_time_range(NOW, NOW)
    db[0].side_effect = None
    db[0].return_value = [{"model_weights": '{"tf_load":1}'}, {"model_weights": None}]
    rows = await core.LoadPredictionsCRUD.get_predictions_by_prediction_id("id")
    assert rows == [{"model_weights": {"tf_load": 1}}, {"model_weights": None}]
    db[0].return_value = [{"model_weights": "invalid"}]
    with pytest.raises(ValueError):
        await core.LoadPredictionsCRUD.get_predictions_by_prediction_id("id")


@pytest.mark.asyncio
async def test_actual_duplicates_and_bounds(db):
    db[1].return_value = 0
    assert await core.ActualLoadDataCRUD.insert_actual_load(NOW, 12000) == 0
    db[0].return_value = [{"earliest": NOW, "latest": NOW + timedelta(hours=1)}]
    assert (await core.ActualLoadDataCRUD.get_time_bounds())["earliest"] == NOW
    db[0].return_value = []
    assert await core.ActualLoadDataCRUD.get_time_bounds() == {"earliest": None, "latest": None}
    db[0].side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError):
        await core.ActualLoadDataCRUD.get_time_bounds()


@pytest.mark.asyncio
async def test_alert_resolution_is_parameterized_and_failure_visible(db):
    assert await core.PerformanceAlertsCRUD.resolve_alert(7, "operator") is True
    assert db[0].await_args.args[1] == ("operator", 7)
    db[0].side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError):
        await core.PerformanceAlertsCRUD.resolve_alert(7)
