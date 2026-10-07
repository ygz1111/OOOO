"""Offline regression coverage for delayed feeds, shared snapshots and interval semantics."""
from concurrent.futures import Future, ThreadPoolExecutor
import asyncio
import threading
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from realtime_api.services import live_forecast as live
from realtime_api.tf_realtime_feature_provider import TFRealtimeFeatureProvider, LOAD_PAST_COLS, LOAD_FUTURE_COLS


@pytest.fixture
def scenario(monkeypatch, tmp_path):
    from realtime_api.services import forecast_cache, forecast_archive
    monkeypatch.setattr(forecast_cache, "CACHE_PATH", tmp_path / "live_forecast.json")
    monkeypatch.setattr(forecast_cache, "model_signature", lambda: "test-model-contract")
    monkeypatch.setattr(forecast_archive, "ARCHIVE_DIR", tmp_path / "forecast_inputs")
    monkeypatch.setattr(forecast_archive, "model_signature", lambda: "test-model-contract")
    clock = [pd.Timestamp("2026-09-22 07:00")]
    idx = pd.date_range(clock[0] - pd.Timedelta(days=18), clock[0], freq="h")
    future = pd.date_range(idx[0], clock[0] + pd.Timedelta(hours=24), freq="h")
    frames = {name: pd.DataFrame({name: value}, index=future if name.startswith("da_") else idx)
              for name, value in [("load", 11000.), ("rt_lmp", 35.), ("da_demand", 11100.), ("da_lmp", 32.)]}
    frames["pv"] = pd.DataFrame({"pv_mw": 500., "rt_demand": 11000., "minimum_samples": 12}, index=idx[:-1])
    weather = pd.concat([pd.DataFrame({"timestamp": future, "location": station, "temperature_2m": 20.,
        "dew_point_2m": 12., "cloud_cover": 30., "shortwave_radiation": 500.})
        for station in ("boston", "burlington", "hartford", "manchester", "portland", "providence")], ignore_index=True)
    calls, failures = [], set()
    provider = TFRealtimeFeatureProvider()
    monkeypatch.setattr(provider, "_market_frames", lambda today: frames)
    def predict(task, past, fut):
        calls.append(task)
        if task in failures:
            raise RuntimeError("simulated model failure")
        required = LOAD_PAST_COLS if task == "price" else LOAD_PAST_COLS[:21]
        assert len(past) == 168 and len(fut) == 24
        assert set(required).issubset(past[-1])
        assert set(LOAD_FUTURE_COLS).issubset(fut[-1])
        rows = [{"hour": i, "timestamp": str(r["ts_local"]), "load_forecast_mw": 12000. if task == "load" else None,
            "price_p10": 20., "price_p50": 30., "price_p90": 40.} for i, r in enumerate(fut)]
        return {"hourly": rows, "timestamps": [r["timestamp"] for r in rows], "origin": str(past[-1]["ts_local"]), "inference_time_ms": 5.}
    def solar(past, fut):
        calls.append("pv")
        if "pv" in failures:
            raise RuntimeError("simulated PV failure")
        assert len(past) == 96 and len(fut) == 24
        return {"timestamps": [str(r["ts_start"]) for r in fut], "hourly_pv_mw": [100.] * 24,
            "hourly_pv_kw": [100000.] * 24, "hourly_capacity_mw": [5000.] * 24,
            "total_mwh": 2400., "peak_mw": 100., "capacity_factor": .02, "horizon": 24, "inference_time_ms": 3.}
    load = SimpleNamespace(MODEL_NAME="tf_split_v1", predict_task_features=predict)
    monkeypatch.setattr(live.services, "tf_realtime_feature_provider", provider)
    monkeypatch.setattr(live.services, "openmeteo_client", SimpleNamespace(fetch_weather_data=lambda *args: (weather, {})))
    monkeypatch.setattr(live.services, "tf_load_price_service", load)
    monkeypatch.setattr(live.services, "tf_pv_service", SimpleNamespace(predict_features=solar))
    monkeypatch.setattr(live, "eastern_now_hour", lambda: clock[0].to_pydatetime())
    monkeypatch.setattr(live, "eastern_now", lambda: (clock[0] + pd.Timedelta(minutes=7)).to_pydatetime())
    monkeypatch.setattr(live, "_previous", {})
    monkeypatch.setattr(live, "_cached", None)
    monkeypatch.setattr(live, "_cache_key", None)
    monkeypatch.setattr(live, "_inflight", None)
    return SimpleNamespace(clock=clock, frames=frames, calls=calls, failures=failures, provider=provider)


def test_restart_restores_original_provenance_without_waiting_for_upstream(scenario, monkeypatch):
    original = live.get_live_snapshot()
    generated = original["components"]["load"]["generated_at"]
    started, release = threading.Event(), threading.Event()
    def delayed(*args):
        started.set()
        assert release.wait(5)
        return original
    monkeypatch.setattr(live, "get_live_snapshot", delayed)
    try:
        live.start_live_preload()
        assert started.wait(1)
        cached = live._waiting_snapshot()
        assert cached["quality"]["refresh_in_progress"]
        assert cached["quality"]["components"]["load"]["status"] == "cached"
        for task in ("load", "price", "pv"):
            assert cached["components"][task]["generated_at"] == generated
            assert cached["components"][task]["data_source"] == original["components"][task]["data_source"]
            assert cached["components"][task]["timestamps"] == original["components"][task]["timestamps"]
    finally:
        release.set()
        live._inflight.result(timeout=5)


def test_cache_rejects_expired_future_corrupt_or_changed_models(scenario, monkeypatch):
    from realtime_api.services import forecast_cache as cache
    import json
    live.get_live_snapshot()
    content = cache.CACHE_PATH.read_text(encoding="utf-8")
    assert len(cache.read_previous(live.eastern_now(), live.validate_component)) == 3
    assert not cache.read_previous(live.eastern_now() + pd.Timedelta(hours=6, seconds=1), live.validate_component)
    assert not cache.read_previous(live.eastern_now() - pd.Timedelta(hours=1), live.validate_component)
    payload = json.loads(content)
    payload["components"]["price"]["result"]["hourly"][1]["timestamp"] = "2026-09-22 08:00"
    cache.CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    assert set(cache.read_previous(live.eastern_now(), live.validate_component)) == {"load", "pv"}
    monkeypatch.setattr(cache, "model_signature", lambda: "changed")
    assert not cache.read_previous(live.eastern_now(), live.validate_component)
    cache.CACHE_PATH.write_text("broken JSON", encoding="utf-8")
    assert not cache.read_previous(live.eastern_now(), live.validate_component)


def test_cache_age_uses_eastern_elapsed_hours_at_month_and_dst_boundaries():
    from realtime_api.services.forecast_cache import age_hours
    assert age_hours("2026-09-30 23:30", "2026-10-01 00:30") == 1
    assert age_hours("2026-03-08 00:30", "2026-03-08 04:30") == 3
    assert age_hours("2026-11-01 00:30", "2026-11-01 04:30") == 5
    with pytest.raises(Exception):
        age_hours("2026-11-01 01:30", "2026-11-01 04:30")


@pytest.mark.parametrize("day", ["2026-03-08", "2026-11-01"])
def test_restart_cache_rejects_ambiguous_or_nonexistent_target_intervals(scenario, day):
    from realtime_api.services import forecast_cache as cache
    import json
    live.get_live_snapshot()
    payload = json.loads(cache.CACHE_PATH.read_text(encoding="utf-8"))
    entry = payload["components"]["load"]
    origin = pd.Timestamp(day)
    generated = str(origin + pd.Timedelta(minutes=7))
    targets = [str(t) for t in pd.date_range(origin + pd.Timedelta(hours=1), periods=24, freq="h")]
    entry["origin_hour"] = str(origin)
    entry["result"].update(generated_at=generated, timestamps=targets)
    entry["quality"]["generated_at"] = generated
    for row, target in zip(entry["result"]["hourly"], targets):
        row["timestamp"] = target
    payload["components"] = {"load": entry}
    cache.CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    assert not cache.read_previous(origin + pd.Timedelta(minutes=8), live.validate_component)


@pytest.mark.asyncio
async def test_snapshot_cache_does_not_extend_original_six_hour_expiry(scenario, monkeypatch):
    snap = live.get_live_snapshot()
    generated = pd.Timestamp(snap["components"]["load"]["generated_at"])
    monkeypatch.setattr(live, "eastern_now", lambda: (generated + pd.Timedelta(hours=6, seconds=1)).to_pydatetime())
    monkeypatch.setattr(live, "_cache_key", (live._service_identity(), pd.Timestamp(live.eastern_now_hour())))
    assert not live.snapshot_response(await live.request_live_snapshot()).predictions


class ImmediateExecutor:
    """Complete work synchronously while keeping the request's Future contract."""
    def submit(self, function, *args):
        pending = Future()
        try:
            pending.set_result(function(*args))
        except Exception as error:
            pending.set_exception(error)
        return pending


async def read_snapshot(entry, *, force=False):
    return (await live.request_live_snapshot(force_refresh=force) if entry == "request"
            else live.get_live_snapshot(force_refresh=force))


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["request", "direct"])
@pytest.mark.parametrize("input_quality", ["fresh", "estimated_inputs"])
async def test_complete_cache_reuses_at_107_seconds_expires_at_300_and_keeps_generation(scenario, monkeypatch, entry, input_quality):
    clock = [1000.]
    monkeypatch.setattr(live.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(live, "_executor", ImmediateExecutor())
    if input_quality == "estimated_inputs":
        # Real operating case: load/price use a bounded trailing estimate,
        # PV stays fresh, and all three still have complete 24-hour results.
        scenario.frames["load"] = scenario.frames["load"].iloc[:-1]
    original = live.get_live_snapshot()
    expected_states = {"load": input_quality, "price": input_quality, "pv": "fresh"}
    assert {task: item["status"] for task, item in original["quality"]["components"].items()} == expected_states
    if input_quality == "estimated_inputs":
        assert original["quality"]["estimated_inputs"]
    for elapsed in (107., 299.9):
        clock[0] = 1000. + elapsed
        snapshot = await read_snapshot(entry)
        assert scenario.calls == ["load", "price", "pv"]
        assert not snapshot["quality"].get("refresh_in_progress")
        assert live._cached_at == 1000.  # Reading cannot restart the five-minute TTL.
        for task in ("load", "price", "pv"):
            assert snapshot["quality"]["components"][task]["status"] == expected_states[task]
            assert snapshot["quality"]["components"][task] == original["quality"]["components"][task]
            assert snapshot["components"][task]["generated_at"] == original["components"][task]["generated_at"]
            assert snapshot["components"][task]["timestamps"] == original["components"][task]["timestamps"]
            assert snapshot["components"][task]["data_source"] == original["components"][task]["data_source"]
        assert snapshot["quality"]["estimated_inputs"] == original["quality"]["estimated_inputs"]
    clock[0] = 1300.
    await read_snapshot(entry)
    assert scenario.calls == ["load", "price", "pv"] * 2
    assert live._cached_at == 1300.


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["request", "direct"])
async def test_force_and_new_eastern_hour_bypass_complete_cache(scenario, monkeypatch, entry):
    clock = [1000.]
    monkeypatch.setattr(live.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(live, "_executor", ImmediateExecutor())
    original = live.get_live_snapshot()
    clock[0] = 1010.
    await read_snapshot(entry, force=True)
    assert scenario.calls == ["load", "price", "pv"] * 2
    scenario.clock[0] += pd.Timedelta(hours=1)
    await read_snapshot(entry)
    assert scenario.calls == ["load", "price", "pv"] * 3
    # The hour key bypass keeps the 24-hour forecast moving, rather than
    # extending the original target's generation or moving old timestamps.
    assert pd.Timestamp(live._cached["components"]["load"]["timestamps"][0]) == scenario.clock[0] + pd.Timedelta(hours=1)
    assert original["components"]["load"]["timestamps"][0] == "2026-09-22 08:00:00"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["request", "direct"])
@pytest.mark.parametrize("degradation", ["unavailable", "cached"])
async def test_degraded_cache_retries_after_60_seconds_and_recovers_to_five_minutes(scenario, monkeypatch, entry, degradation):
    clock = [1000.]
    monkeypatch.setattr(live.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(live, "_executor", ImmediateExecutor())
    originals = {name: frame.copy() for name, frame in scenario.frames.items()}
    if degradation == "cached":
        live.get_live_snapshot()
        scenario.failures.add("price")
    else:
        scenario.failures.add("price")
    initial = live.get_live_snapshot(force_refresh=True)
    states = {value["status"] for value in initial["quality"]["components"].values()}
    assert {degradation} <= states
    initial_calls = list(scenario.calls)
    scenario.frames.update(originals)
    scenario.failures.clear()
    clock[0] = 1059.9
    await read_snapshot(entry)
    assert scenario.calls == initial_calls
    clock[0] = 1060.
    await read_snapshot(entry)
    assert scenario.calls == initial_calls + ["load", "price", "pv"]
    assert all(item["status"] == "fresh" for item in live._cached["quality"]["components"].values())
    clock[0] = 1167.
    recovered = await read_snapshot(entry)
    assert scenario.calls == initial_calls + ["load", "price", "pv"]
    assert not recovered["quality"].get("refresh_in_progress")


@pytest.mark.asyncio
@pytest.mark.parametrize("uptime", [100.0, 10000.0])
async def test_refresh_serves_existing_cache_immediately_and_shares_preload(scenario, monkeypatch, uptime):
    # A fresh Linux runner may have less than five minutes of monotonic uptime.
    # Isolate this clock from asyncio's real scheduling/deadline clock.
    monkeypatch.setattr(live, "time", SimpleNamespace(
        monotonic=lambda: uptime, perf_counter=live.time.perf_counter,
    ))
    live.get_live_snapshot()
    started, release = threading.Event(), threading.Event()
    calls = []
    def delayed(*args):
        calls.append(1)
        started.set()
        assert release.wait(5)
        return {"finished": True}
    monkeypatch.setattr(live, "get_live_snapshot", delayed)
    monkeypatch.setattr(live, "_cached_at", uptime - live.COMPLETE_CACHE_SECONDS - 1)
    pending = None
    try:
        first = await asyncio.wait_for(live.request_live_snapshot(), .5)
        pending = live._inflight
        assert pending is not None
        second = await asyncio.wait_for(live.request_live_snapshot(), .5)
        assert live._inflight is pending
        assert await asyncio.to_thread(started.wait, 1)
        assert len(calls) == 1
        assert first["components"]["load"] == second["components"]["load"]
        assert first["quality"]["refresh_in_progress"]
    finally:
        release.set()
        if pending is not None:
            pending.result(timeout=5)


def test_one_snapshot_shared_with_interval_end_alignment(scenario):
    with ThreadPoolExecutor(4) as pool:
        snapshots = list(pool.map(lambda _: live.get_live_snapshot(), range(4)))
    assert scenario.calls == ["load", "price", "pv"]
    response = live.snapshot_response(snapshots[0])
    assert response.status == "success"
    assert len(response.predictions) == 24
    assert response.predictions[0].timestamp == "2026-09-22T08:00:00"
    assert response.predictions[-1].timestamp == "2026-09-23T07:00:00"
    assert response.predictions[0].pv_estimation_mw == 100.
    snapshots[0]["current"]["actual_load_mw"] = -1
    assert live.get_live_snapshot()["current"]["actual_load_mw"] == 11000.


def test_archive_retains_exact_inputs_and_failure_cache_does_not_reissue(scenario):
    from realtime_api.services import forecast_archive as archive
    original = live.get_live_snapshot()
    identifier = original["quality"]["input_archive"]["archive_id"]
    payload = archive.read_forecast_inputs(identifier, "test-model-contract")
    assert set(payload["components"]) == {"load", "price", "pv"}
    assert len(payload["components"]["load"]["past"]) == 168
    assert len(payload["components"]["pv"]["past"]) == 96
    assert len(payload["components"]["price"]["future"]) == 24
    assert payload["components"]["load"]["prediction"] == original["components"]["load"]
    assert original["components"]["load"]["data_source"].endswith("+input_quality_complete")
    assert live.get_live_snapshot()["quality"]["input_archive"]["archive_id"] == identifier
    scenario.clock[0] += pd.Timedelta(hours=1)
    scenario.failures.update(("load", "price", "pv"))
    degraded = live.get_live_snapshot()
    assert degraded["quality"]["input_archive"] == {"status": "not_created"}
    for task in ("load", "price", "pv"):
        assert degraded["quality"]["components"][task]["status"] == "cached"
        assert degraded["quality"]["components"][task]["input_archive"]["archive_id"] == identifier
        assert degraded["components"][task]["generated_at"] == original["components"][task]["generated_at"]
    assert len(list(archive.ARCHIVE_DIR.glob("*.json.gz"))) == 1
    scenario.failures.clear()
    recovered = live.get_live_snapshot(force_refresh=True)
    assert recovered["quality"]["input_archive"]["status"] == "saved"
    assert recovered["quality"]["input_archive"]["archive_id"] != identifier
    assert len(list(archive.ARCHIVE_DIR.glob("*.json.gz"))) == 2


def test_archive_disk_failure_is_reported_without_masking_prediction_status(scenario, monkeypatch):
    from realtime_api.services import forecast_archive as archive
    def unavailable():
        raise OSError("test disk failure")
    monkeypatch.setattr(archive, "model_signature", unavailable)
    snapshot = live.get_live_snapshot()
    response = live.snapshot_response(snapshot)
    assert len(response.predictions) == 24
    assert response.input_quality["input_archive"]["status"] == "failed"
    assert all(value["input_archive"]["status"] == "failed"
               for value in response.input_quality["components"].values())


def test_weather_interpolation_is_not_classified_as_complete_input(scenario, monkeypatch):
    weather, _ = live.services.openmeteo_client.fetch_weather_data()
    weather.attrs["forecast_provenance"] = {"quality": [
        {"location": "boston", "missing_values": 1, "outliers_corrected": 0}]}
    snapshot = live.get_live_snapshot()
    assert len(snapshot["quality"]["weather_corrections"]) == 1
    for task in ("load", "price", "pv"):
        assert snapshot["components"][task]["data_source"].endswith("+estimated_inputs")
        assert snapshot["quality"]["components"][task]["input_status"] == "estimated_inputs"
        assert "气象资料包含" in snapshot["quality"]["components"][task]["notice"]


def test_failed_weather_station_with_zero_missing_count_is_not_complete(scenario, monkeypatch):
    weather, _ = live.services.openmeteo_client.fetch_weather_data()
    weather = weather.loc[weather["location"] != "portland"].copy()
    failed = {"location": "portland", "is_valid": False, "missing_values": 0,
              "outliers_corrected": 0, "issues": ["API请求失败，未获取到数据"]}
    weather.attrs["forecast_provenance"] = {"quality": [failed]}
    monkeypatch.setattr(live.services.openmeteo_client, "fetch_weather_data", lambda *args: (weather, {}))

    snapshot = live.get_live_snapshot()

    assert snapshot["quality"]["weather_station_failures"] == [failed]
    assert snapshot["quality"]["weather_corrections"] == []
    for task in ("load", "price"):
        result = snapshot["components"][task]
        assert result is not None
        assert result["data_source"].endswith("+weather_station_failure+estimated_inputs")
        assert "input_quality_complete" not in result["data_source"]
        quality = snapshot["quality"]["components"][task]
        assert quality["input_status"] == "estimated_inputs"
        assert "站点缺失或质量校验失败（portland）" in quality["notice"]
        assert "插值" not in quality["notice"]
    assert snapshot["components"]["pv"] is None
    assert snapshot["quality"]["components"]["pv"]["status"] == "unavailable"


def test_valid_uncorrected_weather_stations_remain_complete(scenario):
    weather, _ = live.services.openmeteo_client.fetch_weather_data()
    weather.attrs["forecast_provenance"] = {"quality": [
        {"location": station, "is_valid": True, "missing_values": 0, "outliers_corrected": 0}
        for station in weather["location"].unique()]}

    snapshot = live.get_live_snapshot()

    assert snapshot["quality"]["weather_station_failures"] == []
    assert snapshot["quality"]["weather_corrections"] == []
    for task in ("load", "price", "pv"):
        assert snapshot["components"][task]["data_source"].endswith("+input_quality_complete")
        quality = snapshot["quality"]["components"][task]
        assert quality["status"] == quality["input_status"] == "fresh"
        assert "notice" not in quality


def test_generation_time_is_after_inference_not_upstream_request_start(scenario, monkeypatch):
    issued = [scenario.clock[0] + pd.Timedelta(minutes=7)]
    monkeypatch.setattr(live, "eastern_now", lambda: issued[0].to_pydatetime())
    service = live.services.tf_load_price_service
    original = service.predict_task_features
    def completing(task, past, future):
        result = original(task, past, future)
        issued[0] += pd.Timedelta(seconds=20)
        return result
    monkeypatch.setattr(service, "predict_task_features", completing)
    snapshot = live.get_live_snapshot()
    assert snapshot["components"]["load"]["generated_at"] == "2026-09-22T07:07:20"
    assert snapshot["components"]["price"]["generated_at"] == "2026-09-22T07:07:40"
    assert snapshot["generated_at"] == "2026-09-22T07:07:00"


def test_derived_price_inputs_are_marked_and_not_reported_as_latest_official_observation(scenario):
    price = scenario.frames["rt_lmp"]
    price["rt_lmp_source"] = "iso_ne_hourly_final"
    price["rt_lmp_label_valid"] = True
    price["rt_lmp_samples"] = np.nan
    price.loc[scenario.clock[0], ["rt_lmp_source", "rt_lmp_label_valid", "rt_lmp_samples"]] = ["iso_ne_five_minute_aggregate", False, 8]
    snapshot = live.get_live_snapshot()
    assert snapshot["quality"]["rt_lmp_derived_hours"] == [{"time": str(scenario.clock[0]), "samples_per_hour": 8}]
    assert snapshot["quality"]["components"]["price"]["status"] == "estimated_inputs"
    assert snapshot["quality"]["components"]["price"]["observed_through"] == str(scenario.clock[0] - pd.Timedelta(hours=1))
    assert snapshot["quality"]["components"]["pv"]["status"] == "fresh"


@pytest.mark.parametrize("defect", ["shift", "duplicate", "nan", "truncated"])
def test_bad_model_output_only_degrades_its_own_component(scenario, monkeypatch, defect):
    original = live.services.tf_load_price_service.predict_task_features
    def broken(task, past, future):
        result = original(task, past, future)
        if task == "load":
            if defect == "shift":
                result["timestamps"] = [str(pd.Timestamp(ts) + pd.Timedelta(hours=1)) for ts in result["timestamps"]]
            elif defect == "duplicate":
                result["hourly"][1]["timestamp"] = result["hourly"][0]["timestamp"]
            elif defect == "nan":
                result["hourly"][0]["load_forecast_mw"] = np.nan
            else:
                result["hourly"].pop()
        return result
    monkeypatch.setattr(live.services.tf_load_price_service, "predict_task_features", broken)
    snap = live.get_live_snapshot()
    assert snap["components"]["load"] is None
    assert snap["components"]["price"] and snap["components"]["pv"]


def test_partial_load_is_input_only_not_current_actual_or_backtest_label(scenario):
    frame = scenario.frames["load"]
    frame["minimum_samples"] = 12
    frame.loc[scenario.clock[0], "minimum_samples"] = 8
    snap = live.get_live_snapshot()
    assert snap["components"]["load"] is not None
    assert snap["current"]["time"] == str(scenario.clock[0] - pd.Timedelta(hours=1))
    assert snap["quality"]["partial_load_hours"]
    assert all(pd.Timestamp(w["target_time"]) != scenario.clock[0] for w in snap["load_backtest"])


@pytest.mark.asyncio
async def test_slow_fetch_returns_pending_and_survives_cancellation(scenario, monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []
    def slow(*args):
        calls.append(1)
        started.set()
        assert release.wait(5)
        return {"finished": True}
    monkeypatch.setattr(live, "get_live_snapshot", slow)
    monkeypatch.setattr(live, "REQUEST_WAIT_SECONDS", .03)
    try:
        results = await asyncio.gather(live.request_live_snapshot(), live.request_live_snapshot())
        assert started.is_set()
        assert len(calls) == 1
        assert all(r["quality"]["refresh_in_progress"] for r in results)
        assert all(r["components"]["load"] is None for r in results)
        task = asyncio.create_task(live.request_live_snapshot())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not live._inflight.cancelled()
    finally:
        release.set()
        await asyncio.wrap_future(live._inflight)


def test_waiting_result_cannot_extend_forecast_lifetime(scenario):
    live.get_live_snapshot()
    scenario.clock[0] += pd.Timedelta(hours=1)
    response = live.snapshot_response(live._waiting_snapshot())
    assert response.input_quality["refresh_in_progress"]
    assert len(response.predictions) == 23
    assert response.input_quality["components"]["load"]["status"] == "cached"
    scenario.clock[0] += pd.Timedelta(hours=6)
    assert live.snapshot_response(live._waiting_snapshot()).predictions == []


@pytest.mark.asyncio
async def test_persistence_deduplicates_same_generation_and_skips_cached(scenario, monkeypatch):
    from realtime_api.routers.prediction import _persist_live_response, LoadPredictionsCRUD
    rows = []
    async def insert(**kwargs):
        rows.append(kwargs)
    monkeypatch.setattr(LoadPredictionsCRUD, "insert_prediction", insert)
    response = live.snapshot_response(live.get_live_snapshot())
    await _persist_live_response(response)
    await _persist_live_response(response)
    assert len(rows) == 48
    assert len({row["prediction_id"] for row in rows}) == 1
    response.input_quality["components"]["load"]["status"] = "cached"
    await _persist_live_response(response)
    assert len(rows) == 48


def test_tail_estimates_are_not_actuals_or_metric_labels(scenario):
    end = scenario.clock[0] - pd.Timedelta(hours=2)
    for name in ("load", "rt_lmp"):
        scenario.frames[name] = scenario.frames[name].loc[:end]
    snap = live.get_live_snapshot()
    assert snap["current"]["time"] == str(end)
    assert snap["quality"]["components"]["load"]["status"] == "estimated_inputs"
    assert len(live.snapshot_response(snap).predictions) == 24
    assert all(pd.Timestamp(p["target_time"]) <= end for p in snap["history"])
    assert all(pd.Timestamp(p["target_time"]) <= end for p in snap["load_backtest"])
    assert scenario.frames["load"].index.max() == end
    assert len(snap["quality"]["estimated_inputs"]) == 4


@pytest.mark.parametrize("single_step", [False, True])
def test_hour_rollover_advances_observations_even_when_replay_future_da_is_unpublished(scenario, monkeypatch, single_step):
    """A 24h replay prerequisite can lag while real observations keep updating."""
    day = scenario.clock[0].normalize()
    original = {name: frame.copy() for name, frame in scenario.frames.items()}
    if single_step:
        monkeypatch.setattr(live.services.tf_load_price_service,
                            "predict_load_first_step_features", lambda *args: None, raising=False)
    for name in ("da_demand", "da_lmp"):
        # A published DA interval-start day reaches next-day hour-end 00:00.
        scenario.frames[name] = original[name].loc[:day + pd.Timedelta(days=1)]

    snapshots = []
    for hour in (1, 5):
        scenario.clock[0] = day + pd.Timedelta(hours=hour)
        for name in ("load", "rt_lmp"):
            scenario.frames[name] = original[name].loc[:scenario.clock[0]]
        scenario.frames["pv"] = original["pv"].loc[original["pv"].index < scenario.clock[0]]
        snapshots.append(live.get_live_snapshot())

    first, later = snapshots
    assert first["current"]["time"] == str(day + pd.Timedelta(hours=1))
    assert later["current"]["time"] == str(day + pd.Timedelta(hours=5))
    actuals = {pd.Timestamp(row["target_time"]): row["historical_actual"] for row in later["history"]}
    assert all(actuals[day + pd.Timedelta(hours=hour)] == 11000. for hour in (1, 2, 3, 4, 5))
    assert later["components"]["load"]["timestamps"][0] == str(day + pd.Timedelta(hours=6))
    assert max(pd.Timestamp(window["target_time"]) for window in first["load_backtest"]) == day + pd.Timedelta(hours=1)
    expected_latest = day + pd.Timedelta(hours=5 if single_step else 1)
    assert max(pd.Timestamp(window["target_time"]) for window in later["load_backtest"]) == expected_latest
    assert len(first["load_backtest"]) == 24
    assert len(later["load_backtest"]) == (24 if single_step else 20)
    assert all(len(window["future"]) == (1 if single_step else 24)
               for window in later["load_backtest"])
    if single_step:
        targets = {pd.Timestamp(window["target_time"]) for window in later["load_backtest"]}
        assert all(day + pd.Timedelta(hours=hour) in targets for hour in (2, 3, 4, 5))
    assert scenario.calls == ["load", "price", "pv"] * 2
    # Online-only estimated DA inputs are kept out of the retrospective windows.
    assert later["quality"]["day_ahead_imputed"]


@pytest.mark.parametrize("failure", ["price", "pv"])
def test_independent_model_failure_does_not_hide_load(scenario, failure):
    scenario.failures.add(failure)
    snap = live.get_live_snapshot()
    response = live.snapshot_response(snap)
    assert response.status == "degraded"
    assert len(response.predictions) == 24
    assert snap["quality"]["components"][failure]["status"] == "unavailable"
    if failure == "pv":
        assert response.predictions[0].pv_estimation_mw is None
        assert response.predictions[0].net_load_mw is None
    else:
        assert response.predictions[0].price_p50 is None


def test_missing_pv_source_does_not_block_market(scenario):
    scenario.frames["pv"] = scenario.frames["pv"].iloc[:0]
    assert len(live.snapshot_response(live.get_live_snapshot()).predictions) == 24


def test_missing_prices_can_still_produce_pv(scenario):
    scenario.frames["rt_lmp"] = scenario.frames["rt_lmp"].iloc[:0]
    snap = live.get_live_snapshot()
    assert snap["components"]["load"] is None  # RT-LMP is a trained load input too.
    assert len(snap["components"]["pv"]["timestamps"]) == 24


def test_fallback_keeps_original_times_and_expires(scenario):
    first = live.get_live_snapshot()
    scenario.failures.update(["load", "price", "pv"])
    scenario.clock[0] += pd.Timedelta(hours=1)
    second = live.get_live_snapshot()
    response = live.snapshot_response(second)
    assert len(response.predictions) == 23
    assert response.timestamp == first["generated_at"]
    assert response.predictions[0].timestamp == "2026-09-22T09:00:00"
    assert response.input_quality["components"]["load"]["status"] == "cached"
    scenario.clock[0] += pd.Timedelta(hours=6)
    response = live.snapshot_response(live.get_live_snapshot())
    assert response.predictions == []
    assert response.input_quality["components"]["load"]["status"] == "unavailable"


def test_network_failure_reuses_only_future_points(scenario, monkeypatch):
    live.get_live_snapshot()
    def fail(*args):
        raise OSError("offline")
    monkeypatch.setattr(live.services.openmeteo_client, "fetch_weather_data", fail)
    scenario.clock[0] += pd.Timedelta(hours=2)
    assert len(live.snapshot_response(live.get_live_snapshot()).predictions) == 22


def test_cold_upstream_failure_recovers_in_same_process(scenario, monkeypatch):
    client = live.services.openmeteo_client
    fetch = client.fetch_weather_data
    def offline(*args):
        raise OSError("external source offline")
    monkeypatch.setattr(client, "fetch_weather_data", offline)
    failed = live.get_live_snapshot()
    assert all(result is None for result in failed["components"].values())
    assert not live._previous
    monkeypatch.setattr(client, "fetch_weather_data", fetch)
    recovered = live.get_live_snapshot(force_refresh=True)
    assert all(result is not None for result in recovered["components"].values())


def test_clock_rollover_during_fetch_trims_ended_intervals(scenario, monkeypatch):
    def fetching(today):
        scenario.clock[0] += pd.Timedelta(hours=1)
        return scenario.frames
    monkeypatch.setattr(scenario.provider, "_market_frames", fetching)
    response = live.snapshot_response(live.get_live_snapshot())
    assert len(response.predictions) == 23
    assert response.predictions[0].timestamp == "2026-09-22T09:00:00"


def test_bridge_does_not_fill_internal_holes_or_chain_estimates():
    end = pd.Timestamp("2026-09-22 00:00")
    idx = pd.date_range(end - pd.Timedelta(hours=48), end - pd.Timedelta(hours=1), freq="h")
    raw = pd.DataFrame({"load": np.arange(48.)}, index=idx).drop(idx[10])
    filled, provenance = live.bridge_tail(raw, "load", end)
    assert idx[10] not in filled.index
    assert filled.loc[end, "load"] == raw.loc[end - pd.Timedelta(hours=24), "load"]
    assert len(provenance) == 1
    with pytest.raises(ValueError):
        live.bridge_tail(raw.iloc[:-6], "load", end)


def test_live_feature_frames_reach_real_models(scenario, monkeypatch):
    """Use production weights, synthetic input data, no network and no training."""
    from realtime_api.tf_split_service import TFSplitService
    from realtime_api.tf_pv_v2_service import TFPVV2Service
    load, pv = TFSplitService(), TFPVV2Service()
    load.load_models()
    pv.load_models()
    monkeypatch.setattr(live.services, "tf_load_price_service", load)
    monkeypatch.setattr(live.services, "tf_pv_service", pv)
    response = live.snapshot_response(live.get_live_snapshot())
    assert response.status == "success", response.input_quality
    assert len(response.predictions) == 24
    assert all(np.isfinite(r.load_forecast_mw) and r.pv_estimation_mw is not None and r.price_p50 is not None for r in response.predictions)
    assert response.predictions[0].timestamp == "2026-09-22T08:00:00"


@pytest.mark.asyncio
async def test_routes_share_results_and_degrade_separately(scenario, monkeypatch):
    from realtime_api.routers import prediction, price, generation
    from realtime_api.services import prediction_insight as insight
    from realtime_api.schemas import LoadPredictionRequest
    for module in (prediction, price, generation, insight):
        monkeypatch.setattr(module, "get_engine_config", lambda: {"inference_mode": "live"})
    monkeypatch.setattr(prediction, "eastern_now_hour", lambda: scenario.clock[0].to_pydatetime())
    monkeypatch.setattr(price, "eastern_now", lambda: scenario.clock[0].to_pydatetime())
    monkeypatch.setattr(generation, "eastern_now_hour", lambda: scenario.clock[0].to_pydatetime())
    monkeypatch.setattr("realtime_api.services.container.eastern_now_hour", lambda: scenario.clock[0].to_pydatetime())
    async def insert(**kwargs):
        assert kwargs["target_timestamp"] > scenario.clock[0]
    monkeypatch.setattr(prediction.LoadPredictionsCRUD, "insert_prediction", insert)
    monkeypatch.setattr(prediction, "fire_and_forget", lambda *args: None)
    monkeypatch.setattr(insight, "_run_tf_historical_backtest", lambda windows: [])
    monkeypatch.setattr(generation, "_run_pv_historical_backtest", lambda windows: {"pairs": [], "metrics": None})
    scenario.failures.add("pv")
    result = await prediction.predict_load(LoadPredictionRequest(), False)
    overview = await insight._generate_tf_overview_impl()
    pricing = await price.get_price_forecast()
    solar = await generation.get_solar_generation(False)
    assert len(result.predictions) == len(overview["data"]["future"]["predictions"]) == len(pricing.predictions) == 24
    assert solar["timestamps"] == [] and solar["status"] == "degraded"
    assert scenario.calls == ["load", "price", "pv"]
