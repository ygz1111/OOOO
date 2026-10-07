"""HTTP handler contracts with isolated service doubles and no database/network access."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pandas as pd
import pytest
from fastapi import HTTPException

from realtime_api.routers import prediction, system, weather
from realtime_api.schemas import BatchPredictionRequest, HourlyPrediction, LoadPredictionRequest, LoadPredictionResponse

NOW = datetime(2026, 10, 7, 12)


def response(quality=None, engine="tf_load_split_v1", target=None):
    target = target or NOW + timedelta(hours=1)
    return LoadPredictionResponse(status="success", predictions=[HourlyPrediction(hour=target.hour,
        timestamp=target.isoformat(), load_forecast_mw=12000, pv_estimation_mw=1000, net_load_mw=11000)],
        model_info=[], ensemble_weights={engine: 1, "pv_v2": 1}, inference_time_ms=10,
        data_source="verified_fixture", timestamp=NOW.isoformat(), engine=engine, origin=NOW.isoformat(), input_quality=quality)


@pytest.fixture
def setup_prediction(monkeypatch):
    run = Mock(return_value=response())
    writes = AsyncMock(return_value=1)
    performance = AsyncMock(return_value=1)
    pending = []
    monkeypatch.setattr(prediction, "get_engine_config", lambda: {"inference_mode": "demo"})
    monkeypatch.setattr(prediction, "prediction_backend_ready", lambda: True)
    monkeypatch.setattr(prediction, "tf_load_backend_active", lambda: True)
    monkeypatch.setattr(prediction, "run_prediction_pipeline", run)
    monkeypatch.setattr(prediction.LoadPredictionsCRUD, "insert_prediction", writes)
    monkeypatch.setattr(prediction.ModelPerformanceCRUD, "insert_performance", performance)
    monkeypatch.setattr(prediction, "active_model_runtime_stats", lambda: {"total_inferences": 3, "device": "tensorflow"})
    monkeypatch.setattr(prediction, "eastern_now", lambda: NOW)
    monkeypatch.setattr(prediction, "eastern_now_hour", lambda: NOW)
    monkeypatch.setattr(prediction, "fire_and_forget", lambda factory, name: pending.append(factory))
    monkeypatch.setattr(prediction.services, "openmeteo_client", Mock(fetch_weather_data=Mock(return_value=(pd.DataFrame(), {}))))
    return run, writes, performance, pending


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["tf_load_split_v1", "tf_split_v1", "tf_v2", "legacy"])
async def test_demo_response_persistence_and_performance_are_best_effort(setup_prediction, engine):
    run, write, performance, pending = setup_prediction
    run.return_value = response(engine=engine)
    result = await prediction.predict_load(LoadPredictionRequest(), False)
    assert result.predictions[0].timestamp == (NOW + timedelta(hours=1)).isoformat()
    assert write.await_args.kwargs["prediction_timestamp"] == NOW
    assert write.await_args.kwargs["target_timestamp"] == NOW + timedelta(hours=1)
    assert result.data_source == ("frozen_tail_demo" if engine == "legacy" else "verified_fixture")
    await pending[0]()
    assert performance.await_count == 2
    assert performance.await_args_list[0].kwargs["successful_inferences"] == 3


@pytest.mark.asyncio
async def test_cached_and_failed_storage_never_change_successful_forecast(setup_prediction):
    run, write, performance, pending = setup_prediction
    run.return_value = response({"components": {"load": {"status": "cached"}}})
    assert (await prediction.predict_load(LoadPredictionRequest(), False)).status == "success"
    write.assert_not_awaited()
    performance.side_effect = RuntimeError("offline")
    await pending[0]()
    run.return_value = response()
    write.side_effect = RuntimeError("offline")
    assert (await prediction.predict_load(LoadPredictionRequest(), False)).status == "success"


@pytest.mark.asyncio
async def test_live_persistence_skips_unavailable_or_cached_rows(setup_prediction):
    run, write, performance, pending = setup_prediction
    result = response()
    await prediction._persist_live_response(result)
    assert write.await_count == 1
    write.reset_mock()
    result.input_quality = {"components": {"load": {"status": "cached"}}}
    await prediction._persist_live_response(result)
    write.assert_not_awaited()
    result.input_quality = None
    result.predictions = []
    await prediction._persist_live_response(result)
    write.assert_not_awaited()
    write.side_effect = RuntimeError("offline")
    await prediction._persist_live_response(response())


@pytest.mark.asyncio
async def test_provided_weather_and_stale_live_prediction_rejection(setup_prediction, monkeypatch):
    monkeypatch.setattr(prediction, "get_engine_config", lambda: {"inference_mode": "live"})
    request = LoadPredictionRequest(weather_data=[{"timestamp": NOW, "temperature_2m": 12, "dew_point_2m": 6}])
    assert (await prediction.predict_load(request, False)).data_source == "verified_fixture"
    assert setup_prediction[0].call_args.args[0].temperature_2m.tolist() == [12]
    setup_prediction[1].reset_mock()
    setup_prediction[0].return_value = response(target=NOW)
    with pytest.raises(HTTPException) as exc:
        await prediction.predict_load(request, False)
    assert exc.value.status_code == 500
    assert "目标时间未晚于当前小时" in exc.value.detail
    setup_prediction[1].assert_not_awaited()


@pytest.mark.asyncio
async def test_unready_and_weather_or_pipeline_errors_have_distinct_statuses(setup_prediction, monkeypatch):
    monkeypatch.setattr(prediction, "prediction_backend_ready", lambda: False)
    with pytest.raises(HTTPException) as exc:
        await prediction.predict_load(LoadPredictionRequest(), False)
    assert exc.value.status_code == 503
    monkeypatch.setattr(prediction, "prediction_backend_ready", lambda: True)
    monkeypatch.setattr(prediction, "tf_load_backend_active", lambda: False)
    prediction.services.openmeteo_client.fetch_weather_data.side_effect = RuntimeError("weather unavailable")
    with pytest.raises(HTTPException) as exc:
        await prediction.predict_load(LoadPredictionRequest(), False)
    assert exc.value.status_code == 502
    prediction.services.openmeteo_client.fetch_weather_data.side_effect = None
    setup_prediction[0].side_effect = ValueError("invalid shape")
    with pytest.raises(HTTPException) as exc:
        await prediction.predict_load(LoadPredictionRequest(), False)
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_batch_keeps_successful_items_when_one_model_call_fails(setup_prediction, monkeypatch):
    setup_prediction[0].side_effect = [response(), RuntimeError("invalid input")]
    batch = BatchPredictionRequest(requests=[LoadPredictionRequest(), LoadPredictionRequest()])
    result = await prediction.batch_predict(batch)
    assert result.status == "partial"
    assert [item.status for item in result.results] == ["success", "error"]
    assert result.results[1].predictions == []
    monkeypatch.setattr(prediction, "prediction_backend_ready", lambda: False)
    with pytest.raises(HTTPException) as exc:
        await prediction.batch_predict(batch)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_batch_provided_weather_and_inactive_backend_skip_weather_fetch(setup_prediction, monkeypatch):
    monkeypatch.setattr(prediction, "tf_load_backend_active", lambda: False)
    batch = BatchPredictionRequest(requests=[LoadPredictionRequest(weather_data=[{"timestamp": NOW, "temperature_2m": 12, "dew_point_2m": 6}]), LoadPredictionRequest()])
    result = await prediction.batch_predict(batch)
    assert result.status == "success"
    assert setup_prediction[0].call_args_list[0].args[0].temperature_2m.tolist() == [12]
    assert setup_prediction[0].call_args_list[1].args[0].empty
    prediction.services.openmeteo_client.fetch_weather_data.assert_not_called()


@pytest.mark.asyncio
async def test_history_defaults_filters_ranges_and_validation(setup_prediction, monkeypatch):
    latest = AsyncMock(return_value=[{"model_type": "active"}, {"model_type": "archived"}])
    ranged = AsyncMock(return_value=[])
    monkeypatch.setattr(prediction.LoadPredictionsCRUD, "get_latest_predictions", latest)
    monkeypatch.setattr(prediction.LoadPredictionsCRUD, "get_predictions_by_time_range", ranged)
    assert (await prediction.get_prediction_history(None, None, "active", 2000)).data == [{"model_type": "active"}]
    latest.assert_awaited_once_with(limit=1000)
    await prediction.get_prediction_history(NOW.isoformat(), None, None, -1)
    assert ranged.await_args.kwargs["limit"] == 1
    assert ranged.await_args.kwargs["end_time"] == NOW
    await prediction.get_prediction_history(None, NOW.isoformat(), None, 12)
    assert ranged.await_args.kwargs["start_time"] == NOW - timedelta(hours=24)
    with pytest.raises(HTTPException) as exc:
        await prediction.get_prediction_history("invalid", None, None, 12)
    assert exc.value.status_code == 400
    latest.side_effect = RuntimeError("offline")
    with pytest.raises(HTTPException) as exc:
        await prediction.get_prediction_history(None, None, None, 12)
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_overview_incomplete_inputs_are_503_other_validation_stays_visible(monkeypatch):
    from realtime_api.services import prediction_insight
    build = AsyncMock(return_value={"status": "preparing"})
    monkeypatch.setattr(prediction_insight, "generate_load_overview", build)
    assert (await prediction.get_load_overview(True))["status"] == "preparing"
    build.assert_awaited_once_with(force_refresh=True)
    build.side_effect = ValueError("ISO-NE inputs missing")
    with pytest.raises(HTTPException) as exc:
        await prediction.get_load_overview(False)
    assert exc.value.status_code == 503
    build.side_effect = ValueError("bad configuration")
    with pytest.raises(ValueError, match="bad configuration"):
        await prediction.get_load_overview(False)


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded,expected", [(3, "healthy"), (1, "degraded"), (0, "error")])
async def test_system_status_model_counts_and_memory_units(monkeypatch, loaded, expected):
    import psutil
    stats = {"models_loaded": loaded, "models_total": 3, "device": "tensorflow", "total_inferences": 5,
        "average_time_ms": 10, "ensemble_weights": {"tf": 1}}
    monkeypatch.setattr(system, "active_model_runtime_stats", lambda: stats)
    monkeypatch.setattr(psutil, "Process", lambda: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=128 * 1024**2)))
    monkeypatch.setattr(system.services, "start_time", system.time.time() - 30)
    status = await system.get_system_status()
    assert status.status == expected
    assert status.memory_usage_mb == 128
    assert status.uptime_seconds >= 30


@pytest.mark.asyncio
async def test_system_metrics_bounds_failure_and_recovery(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(system.SystemMetricsCRUD, "get_metrics", query)
    await system.get_system_metrics(1000, -1)
    query.assert_awaited_once_with(hours=168, limit=1)
    query.side_effect = RuntimeError("offline")
    with pytest.raises(HTTPException) as exc:
        await system.get_system_metrics()
    assert exc.value.status_code == 500


@pytest.mark.asyncio
@pytest.mark.parametrize("db_state,model_state,expected", [("healthy", "healthy", "ready"),
    ("unhealthy", "healthy", "not_ready"), ("healthy", "unhealthy", "not_ready")])
async def test_health_readiness_checks_real_dependencies(monkeypatch, db_state, model_state, expected):
    service = Mock()
    service.check_database_health = AsyncMock(return_value=SimpleNamespace(status=db_state))
    service.check_model_service_health.return_value = SimpleNamespace(status=model_state)
    service.comprehensive_health_check = AsyncMock(return_value={"status": "healthy"})
    monkeypatch.setattr(system, "get_health_check_service", lambda: service)
    monkeypatch.setattr(system, "active_load_service", lambda: object())
    assert (await system.readiness_check())["status"] == expected
    assert (await system.health_check())["status"] == "healthy"
    assert (await system.liveness_check())["status"] == "alive"
    service.check_database_health.side_effect = RuntimeError("database unavailable")
    assert (await system.readiness_check())["status"] == "not_ready"


@pytest.mark.asyncio
async def test_weather_current_uses_nearest_hour_and_persistence_failure_isolated(monkeypatch):
    locations = [SimpleNamespace(name="Boston", lat=42, lon=-71), SimpleNamespace(name="Missing", lat=43, lon=-72)]
    frame = pd.DataFrame([{"location": "Boston", "timestamp": NOW - timedelta(hours=1), "temperature_2m": 1, "dew_point_2m": 0},
        {"location": "Boston", "timestamp": NOW, "temperature_2m": 12, "dew_point_2m": 6}])
    client = SimpleNamespace(locations=locations, fetch_weather_data=Mock(return_value=(frame, {})))
    pending = []
    monkeypatch.setattr(weather.services, "openmeteo_client", client)
    monkeypatch.setattr(weather, "eastern_now", lambda: NOW)
    monkeypatch.setattr(weather, "fire_and_forget", lambda factory, name: pending.append(factory))
    insert = AsyncMock(side_effect=[RuntimeError("offline"), 1])
    monkeypatch.setattr(weather.WeatherDataCRUD, "insert_weather_data", insert)
    result = await weather.get_current_weather(False)
    assert len(result.stations) == 1
    assert result.stations[0].temperature_2m == 12
    assert result.regional_average["temperature_2m"] == 12
    assert "relative_humidity_2m" not in result.regional_average
    await pending[0]()
    await pending[0]()
    assert insert.await_args.kwargs["timestamp"] == NOW
    client.fetch_weather_data.side_effect = RuntimeError("weather API unavailable")
    with pytest.raises(HTTPException) as exc:
        await weather.get_current_weather(False)
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_weather_history_selected_station_bounds_and_query_failures(monkeypatch):
    ranged = AsyncMock(return_value=[])
    latest = AsyncMock(return_value=[])
    monkeypatch.setattr(weather.WeatherDataCRUD, "get_weather_by_location_and_time", ranged)
    monkeypatch.setattr(weather.WeatherDataCRUD, "get_latest_weather_data", latest)
    monkeypatch.setattr(weather, "eastern_now_hour", lambda: NOW)
    assert (await weather.get_weather_history("Boston", 6, 12)).data == []
    ranged.assert_awaited_once_with(location="Boston", start_time=NOW - timedelta(hours=6), end_time=NOW)
    await weather.get_weather_history(None, 6, 2000)
    latest.assert_awaited_once_with(location="Boston", limit=1000)
    latest.side_effect = RuntimeError("offline")
    with pytest.raises(HTTPException) as exc:
        await weather.get_weather_history(None, 6, 12)
    assert exc.value.status_code == 500
