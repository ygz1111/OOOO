"""Shared live snapshot. Market targets are hour-ending; PV inputs are hour-start.

Only short trailing observation gaps (<= 6 hours) may be estimated from an
observed previous-day value. Estimates never enter actuals or backtest labels.
On failure, reuse only unexpired targets from a <= 6h old successful component;
never move its timestamps, manufacture a 24th point, or use frozen demo data.
"""
from copy import deepcopy
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import threading
import time

import numpy as np
import pandas as pd

from realtime_api.services.container import services, eastern_now, eastern_now_hour
from realtime_api.services.forecast_cache import age_hours, read_previous, save_previous
from realtime_api.services.forecast_archive import save_forecast_inputs
from realtime_api.tf_realtime_feature_provider import (
    LOAD_PAST_COLS, LOAD_FUTURE_COLS, PV_PAST_COLS, PV_FUTURE_COLS,
    PV_TREND_START, _solar_coszen,
)

logger = logging.getLogger(__name__)
MAX_DELAY_HOURS = 6
_lock = threading.Lock()
_cached = None
_cache_key = None
_cached_at = 0.0
_previous = {}
_request_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live-forecast")
_weather_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live-weather")
_inflight = None
REQUEST_WAIT_SECONDS = 8
COMPLETE_CACHE_SECONDS = 300
DEGRADED_CACHE_SECONDS = 60


def _cache_is_current(key):
    """Reuse complete successful results for five minutes; retry missing/old results sooner."""
    if _cached is None or _cache_key != key:
        return False
    components = _cached.get("components", {})
    quality = _cached.get("quality", {}).get("components", {})
    complete = all(components.get(task) and len(components[task].get("timestamps", [])) == 24
                   and quality.get(task, {}).get("status") in ("fresh", "estimated_inputs")
                   for task in ("load", "price", "pv"))
    ttl = COMPLETE_CACHE_SECONDS if complete else DEGRADED_CACHE_SECONDS
    return time.monotonic() - _cached_at < ttl


def start_live_preload():
    """Restore auditable components, then share one nonblocking startup refresh."""
    global _cached, _cache_key, _cached_at, _previous, _inflight
    with _request_lock:
        if _inflight is not None and not _inflight.done():
            return
        now = pd.Timestamp(eastern_now_hour())
        _cached, _cache_key, _cached_at = None, None, 0.0
        _previous = read_previous(eastern_now(), validate_component)
        if _previous:
            _cached = _waiting_snapshot()
            for task, (result, quality, _) in _previous.items():
                _cached["components"][task] = valid_component(result, task, now)
                _cached["quality"]["components"][task] = {**quality, "status": "cached",
                    "notice": "重启恢复的此前预测；正在获取最新数据"}
            _cached = trim_snapshot(_cached, now)
            _cache_key = (_service_identity(), now)
        _inflight = _executor.submit(get_live_snapshot)
        logger.info("启动预测预加载，恢复 %s 项此前预测", len(_previous))


def _usable_age(result):
    try:
        return 0 <= age_hours(result["generated_at"], eastern_now()) <= MAX_DELAY_HOURS
    except Exception:
        return False


def quality_cache_valid(quality):
    return all(_usable_age(value) for value in (quality or {}).get("components", {}).values()
               if value.get("status") != "unavailable")


def _service_identity():
    return (id(services.tf_realtime_feature_provider), id(services.tf_load_price_service), id(services.tf_pv_service))


def _waiting_snapshot():
    """Do not wait for the compute lock or reset the age of a cached forecast."""
    now = pd.Timestamp(eastern_now_hour())
    if _cached is not None and _cache_key and _cache_key[0] == _service_identity():
        snapshot = deepcopy(_cached)
        for task, result in snapshot["components"].items():
            if result and _usable_age(result):
                snapshot["quality"]["components"][task].update(status="cached", notice="更新进行中，暂用此前未过期预测")
            else:
                snapshot["components"][task] = None
                snapshot["quality"]["components"][task] = {"status": "unavailable", "notice": "暂无未过期预测"}
        snapshot["load_backtest"], snapshot["pv_backtest"] = [], []
    else:
        snapshot = {"components": dict.fromkeys(("load", "price", "pv")),
            "quality": {"time_basis": "hour_end", "timezone": "America/New_York", "origin_lag_hours": 0, "day_ahead_imputed": [],
                "partial_pv_hours": [], "pv_minimum_samples_per_zone": 8, "components": {
                    task: {"status": "unavailable", "notice": "首次准备数据中"} for task in ("load", "price", "pv")}},
            "current": {"time": None, "actual_load_mw": None}, "history": [], "load_backtest": [], "pv_backtest": [],
            "generated_at": eastern_now().isoformat(), "inference_time_ms": 0}
    snapshot["quality"].update(refresh_in_progress=True,
        notice="正在后台获取资料与计算，页面会自动重试；首次准备可能较慢，不必反复点击刷新。")
    return trim_snapshot(snapshot, now)


async def request_live_snapshot(force_refresh=False):
    """One background computation; HTTP waits at most 8s, cancellation won't kill it."""
    global _inflight
    with _request_lock:
        if not force_refresh and _cache_is_current((_service_identity(), pd.Timestamp(eastern_now_hour()))):
            return trim_snapshot(deepcopy(_cached), pd.Timestamp(eastern_now_hour()))
        if _inflight is None or _inflight.done():
            _inflight = _executor.submit(get_live_snapshot, force_refresh)
        pending = _inflight
    waiting = _waiting_snapshot()
    if any(waiting["components"].values()):
        return waiting
    try:
        return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(pending)), REQUEST_WAIT_SECONDS)
    except asyncio.TimeoutError:
        return _waiting_snapshot()


def bridge_tail(frame, column, end):
    """Return a copy with bounded trailing estimates and auditable provenance."""
    result = frame.copy()
    observed = pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
    observed = observed.loc[observed.index <= end].dropna().sort_index()
    if observed.empty:
        raise ValueError(f"{column}没有可用观测")
    last = observed.index[-1]
    if (end - last) > pd.Timedelta(hours=MAX_DELAY_HOURS):
        raise ValueError(f"{column}观测超过{MAX_DELAY_HOURS}小时未更新")
    estimates = []
    for target in pd.date_range(last + pd.Timedelta(hours=1), end, freq="h"):
        source = target - pd.Timedelta(hours=24)
        value = observed.get(source, np.nan)
        if not np.isfinite(value):
            raise ValueError(f"{column}缺少昨日同小时观测")
        result.loc[target, column] = value
        estimates.append({"field": column, "target_time": str(target),
                          "source_time": str(source), "method": "previous_day_observation"})
    return result.sort_index(), estimates


def pv_frame(provider, weather, actual):
    frame = weather.join(actual, how="outer").sort_index()
    frame["pv_mw_ISONE"] = frame["pv_mw"]
    frame = frame.reset_index(names="ts_start")
    index = pd.DatetimeIndex(frame.ts_start)
    frame["coszen"] = _solar_coszen(index)
    frame["sun_up"] = (frame.coszen > 0.02).astype(int)
    frame["hour"] = index.hour
    provider._calendar(frame, "ts_start", "hour")
    frame["doy_sin"] = np.sin(2 * np.pi * index.dayofyear / 365.25)
    frame["doy_cos"] = np.cos(2 * np.pi * index.dayofyear / 365.25)
    frame["trend_days"] = (index - PV_TREND_START).total_seconds() / 86400
    return frame


def validate_component(result, task, now):
    """Reject shifted, duplicated, truncated or non-finite fresh model output."""
    expected = pd.date_range(now if task == "pv" else now + pd.Timedelta(hours=1), periods=24, freq="h")
    timestamps = pd.DatetimeIndex(result["timestamps"])
    if not timestamps.equals(expected):
        raise ValueError(f"{task}预测时间未与24个连续小时对齐")
    if task == "pv":
        arrays = [result["hourly_pv_mw"]]
        for key in ("hourly_pv_kw", "hourly_pu", "hourly_capacity_mw"):
            if key in result:
                arrays.append(result[key])
    else:
        rows = result["hourly"]
        if not pd.DatetimeIndex([row["timestamp"] for row in rows]).equals(expected):
            raise ValueError(f"{task}预测行与时间列表不一致")
        fields = ["load_forecast_mw"] if task == "load" else ["price_p10", "price_p50", "price_p90"]
        arrays = [[row[field] for row in rows] for field in fields]
    if any(len(values) != 24 or not np.isfinite(np.asarray(values, dtype=float)).all() for values in arrays):
        raise ValueError(f"{task}预测含缺失或无效数值")
    if task != "price" and any((np.asarray(values, dtype=float) < 0).any() for values in arrays):
        raise ValueError(f"{task}预测含负出力")
    if task == "price" and any(not row["price_p10"] <= row["price_p50"] <= row["price_p90"] for row in rows):
        raise ValueError("电价分位数次序异常")


def valid_component(result, task, now):
    """Drop ended intervals, preserving original target and generation times."""
    result = deepcopy(result)
    if task == "pv":
        indices = [i for i, ts in enumerate(result["timestamps"])
                   if pd.Timestamp(ts) + pd.Timedelta(hours=1) > now]
        size = len(result["timestamps"])
        for key in ("timestamps", "hourly_pv_mw", "hourly_pv_kw", "hourly_pu", "hourly_capacity_mw"):
            if key in result and len(result[key]) == size:
                result[key] = [result[key][i] for i in indices]
        values = result["hourly_pv_mw"]
        result["total_mwh"] = round(sum(values), 2)
        result["peak_mw"] = max(values, default=0)
        caps = result.get("hourly_capacity_mw", [])
        result["capacity_factor"] = sum(values) / sum(caps) if caps and sum(caps) else None
        result["horizon"] = len(values)
    else:
        result["hourly"] = [row for row in result["hourly"] if pd.Timestamp(row["timestamp"]) > now]
        result["timestamps"] = [row["timestamp"] for row in result["hourly"]]
    return result if result["timestamps"] else None


def get_live_snapshot(force_refresh=False):
    """All HTTP entry points share one compute under the same lock and TTL."""
    global _cached, _cache_key, _cached_at, _previous
    with _lock:
        now = pd.Timestamp(eastern_now_hour())
        identity = _service_identity()
        key = (identity, now)
        if not force_refresh and _cache_is_current(key):
            return trim_snapshot(deepcopy(_cached), now)
        if _cache_key and _cache_key[0] != identity:
            _previous = {}
        snapshot = _compute(now, force_refresh)
        # Inference/network I/O can cross an hour boundary. Never expose an ended target.
        snapshot = trim_snapshot(snapshot, pd.Timestamp(eastern_now_hour()))
        _cached, _cache_key, _cached_at = deepcopy(snapshot), key, time.monotonic()
        save_previous(_previous)
        logger.info("在线预测准备结束: 有效模块=%s/3, 输入准备及推理=%sms",
                    sum(result is not None for result in snapshot["components"].values()),
                    snapshot["quality"].get("preparation_time_ms"))
        return snapshot


def trim_snapshot(snapshot, now):
    for task, result in snapshot["components"].items():
        if result:
            snapshot["components"][task] = valid_component(result, task, now) if _usable_age(result) else None
            if snapshot["components"][task] is None:
                snapshot["quality"]["components"][task].update(status="unavailable", notice="此前预测已过期，等待新数据")
    snapshot["quality"]["forecast_hour_end_after"] = str(now)
    return snapshot


def _compute(now, force):
    started = time.perf_counter()
    provider = services.tf_realtime_feature_provider
    quality = {"time_basis": "hour_end", "timezone": "America/New_York",
               "origin_lag_hours": 0, "day_ahead_imputed": [], "partial_pv_hours": [],
               "rt_lmp_derived_hours": [], "weather_station_failures": [],
               "pv_minimum_samples_per_zone": 8, "components": {}, "estimated_inputs": [],
               "notice": "时间均为美东时间；负荷/电价图的08:00表示07:00–08:00，光伏独立页按小时开始标记。"}
    snapshot = {"components": {}, "quality": quality, "current": {"time": None, "actual_load_mw": None},
                "history": [], "load_backtest": [], "pv_backtest": [], "generated_at": eastern_now().isoformat()}
    frames, weather, source_error = None, None, None
    # Independent inputs download concurrently; existing weather/date cache
    # locks still merge requests from other pages and background sync.
    weather_future = _weather_executor.submit(services.openmeteo_client.fetch_weather_data, None, force)
    try:
        frames = provider._market_frames(now.date())
        price_frame = frames["rt_lmp"]
        if "rt_lmp_source" in price_frame:
            derived = price_frame.loc[(price_frame["rt_lmp_source"] == "iso_ne_five_minute_aggregate")
                & (price_frame.index > now - pd.Timedelta(hours=336)) & (price_frame.index <= now)]
            quality["rt_lmp_derived_hours"] = [{"time": str(ts), "samples_per_hour": int(row["rt_lmp_samples"])}
                for ts, row in derived.iterrows()]
        if "minimum_samples" in frames["pv"]:
            samples = frames["pv"]["minimum_samples"]
            quality["partial_pv_hours"] = [{"time": str(ts), "samples_per_zone": int(samples.loc[ts])} for ts in samples.index[(samples < 12) & (samples.index < now)]]
        load_frame = frames["load"]
        if "minimum_samples" in load_frame:
            samples = load_frame["minimum_samples"]
            quality["partial_load_hours"] = [{"time": str(ts), "samples_per_zone": int(samples.loc[ts])}
                for ts in samples.index[(samples < 12) & (samples.index <= now)]]
            load_frame = load_frame.loc[samples >= 12]
        load = load_frame["load"].replace([np.inf, -np.inf], np.nan).dropna()
        load = load.loc[load.index <= now].sort_index()
        if not load.empty:
            snapshot["current"] = {"time": str(load.index[-1]), "actual_load_mw": float(load.iloc[-1])}
            snapshot["history"] = [{"target_time": str(ts), "historical_actual": float(v), "historical_forecast": None}
                                   for ts, v in load.loc[load.index > now - pd.Timedelta(hours=24)].items()]
    except Exception as exc:
        source_error = "电网数据接口暂不可用"
        logger.warning("Live market unavailable: %s", type(exc).__name__)

    try:
        weather, _ = weather_future.result()
        # Do not label cleaned/interpolated weather as unmodified complete input.
        weather_reports = weather.attrs.get("forecast_provenance", {}).get("quality", [])
        # Failed stations often have zero records and zero missing-value counts.
        # Regional averages from the remaining stations are still incomplete inputs.
        quality["weather_station_failures"] = [report for report in weather_reports
            if report.get("is_valid") is False]
        quality["weather_corrections"] = [report for report in weather_reports
            if report.get("is_valid") is not False
            and (report.get("missing_values", 0) or report.get("outliers_corrected", 0))]
    except Exception as exc:
        source_error = "天气接口暂不可用"
        logger.warning("Live weather unavailable: %s", type(exc).__name__)

    market, market_error, pv, pv_error = None, None, None, None
    if frames is not None and weather is not None and not weather.empty:
        try:
            working = {name: frame.copy() for name, frame in frames.items()}
            estimates = []
            for name in ("load", "rt_lmp", "da_demand", "da_lmp"):
                working[name], additions = bridge_tail(working[name], name, now)
                estimates.extend(additions)
            working, quality["day_ahead_imputed"] = provider._fill_future_day_ahead(working, now)
            market = provider._prepare_load_market(working, provider._weather(weather))
            quality["estimated_inputs"].extend(estimates)
            # Backtests exclusively use untouched observed inputs, never the bridged frame.
            try:
                raw_market = provider._prepare_load_market(frames, provider._weather(weather))
                future_hours = 1 if callable(getattr(services.tf_load_price_service, "predict_load_first_step_features", None)) else 24
                snapshot["load_backtest"] = provider._build_load_backtest_windows(
                    raw_market, now, skip_incomplete=True, future_hours=future_hours)
            except Exception:
                pass
        except Exception as exc:
            market_error = str(exc)
        try:
            pv_end = now - pd.Timedelta(hours=1)
            pv_actual, estimates = bridge_tail(frames["pv"], "pv_mw", pv_end)
            quality["estimated_inputs"].extend(estimates)
            pv_weather = provider._pv_weather(weather)
            pv = pv_frame(provider, pv_weather, pv_actual)
            try:
                snapshot["pv_backtest"] = provider._build_pv_backtest_windows(pv_frame(provider, pv_weather, frames["pv"]), pv_end)
            except Exception:
                pass
        except Exception as exc:
            pv_error = str(exc)

    task_inputs = {}
    for task in ("load", "price", "pv"):
        try:
            if source_error:
                raise ValueError(source_error)
            if task == "pv":
                if pv is None:
                    raise ValueError(pv_error or "光伏输入暂不可用")
                past = provider._require_contiguous(pv[["ts_start"] + PV_PAST_COLS], "ts_start", now - pd.Timedelta(hours=96), 96, "光伏历史")
                future = provider._require_contiguous(pv[["ts_start"] + PV_FUTURE_COLS], "ts_start", now, 24, "光伏未来")
                result = services.tf_pv_service.predict_features(past.to_dict("records"), future.to_dict("records"))
                observed = frames["pv"]["pv_mw"].dropna()
                observed = observed.loc[observed.index < now]
                last = observed.index.max() + pd.Timedelta(hours=1) if not observed.empty else None
            else:
                if market is None:
                    raise ValueError(market_error or "负荷/电价输入暂不可用")
                cols = LOAD_PAST_COLS if task == "price" else LOAD_PAST_COLS[:LOAD_PAST_COLS.index("rtlmp_lag1")]
                past = provider._require_contiguous(market[["ts_local"] + cols], "ts_local", now - pd.Timedelta(hours=167), 168, task)
                future = provider._require_contiguous(market[["ts_local"] + LOAD_FUTURE_COLS], "ts_local", now + pd.Timedelta(hours=1), 24, task)
                service = services.tf_load_price_service
                if hasattr(service, "predict_task_features"):
                    result = service.predict_task_features(task, past.to_dict("records"), future.to_dict("records"))
                else:
                    result = service.predict_features(past.to_dict("records"), future.to_dict("records"))
                field = "load" if task == "load" else "rt_lmp"
                observed = frames[field][field].dropna()
                if task == "price" and "rt_lmp_label_valid" in frames[field]:
                    observed = observed.loc[frames[field]["rt_lmp_label_valid"].reindex(observed.index).fillna(False)]
                observed = observed.loc[observed.index <= now]
                last = observed.index.max() if not observed.empty else None
            validate_component(result, task, now)
            # The result is issued after inference, not before upstream downloads.
            # Cached components keep this timestamp and cannot acquire a new lead time.
            result["generated_at"] = eastern_now().isoformat()
            result["data_source"] = "iso_ne+open_meteo:zonal_he_v2"
            relevant = [x for x in quality["estimated_inputs"] if (x["field"] == "pv_mw") == (task == "pv")]
            partial = quality["partial_pv_hours"] if task == "pv" else quality.get("partial_load_hours", [])
            price_derived = quality["rt_lmp_derived_hours"] if task != "pv" else []
            state = "estimated_inputs" if relevant or partial or price_derived or quality.get("weather_corrections") or quality["weather_station_failures"] or (task != "pv" and quality["day_ahead_imputed"]) else "fresh"
            if state != "fresh":
                if quality["weather_station_failures"]:
                    result["data_source"] += "+weather_station_failure"
                result["data_source"] += "+estimated_inputs"
            else:
                result["data_source"] += "+input_quality_complete"
            quality["components"][task] = {"status": state, "observed_through": str(last) if last is not None else None,
                                           "generated_at": result["generated_at"], "input_status": state, "method": "tensorflow"}
            if price_derived:
                quality["components"][task]["notice"] = f"输入包含{len(price_derived)}小时五分钟聚合电价，作为补充输入而非真实小时标签"
            if quality.get("weather_corrections"):
                existing_notice = quality["components"][task].get("notice", "")
                quality["components"][task]["notice"] = (existing_notice + "；" if existing_notice else "") + "气象资料包含插值或异常值修正"
            if quality["weather_station_failures"]:
                failed_stations = "、".join(str(report.get("location") or "未知站点")
                                          for report in quality["weather_station_failures"])
                existing_notice = quality["components"][task].get("notice", "")
                quality["components"][task]["notice"] = (existing_notice + "；" if existing_notice else "") + f"气象站点缺失或质量校验失败（{failed_stations}）"
            task_inputs[task] = {"origin_hour": str(now), "generated_at": result["generated_at"],
                "input_status": state, "data_source": result["data_source"],
                "past": past.to_dict("records"), "future": future.to_dict("records"),
                "prediction": deepcopy(result)}
            _previous[task] = (deepcopy(result), deepcopy(quality["components"][task]), now)
        except Exception as exc:
            result = None
            previous = _previous.get(task)
            if previous and _usable_age(previous[0]):
                result = valid_component(previous[0], task, now)
            quality["components"][task] = {**(previous[1] if result else {}),
                "status": "cached" if result else "unavailable", "reason": str(exc),
                "notice": "沿用此前预测，仅保留尚未结束的时段" if result else "数据不足，暂不提供该项预测"}
            logger.warning("Live %s degraded: %s", task, type(exc).__name__)
        snapshot["components"][task] = result
    archive = save_forecast_inputs(task_inputs, weather) if task_inputs else {"status": "not_created"}
    quality["input_archive"] = archive
    for task in task_inputs:
        quality["components"][task]["input_archive"] = archive
        result, component_quality, origin = _previous[task]
        _previous[task] = (result, deepcopy(quality["components"][task]), origin)
    quality["preparation_time_ms"] = round((time.perf_counter() - started) * 1000, 1)
    # Network/download/preparation time is not the neural network's inference latency.
    snapshot["inference_time_ms"] = round(sum(float(result.get("inference_time_ms", 0))
        for result in snapshot["components"].values() if result), 1)
    return snapshot


def snapshot_response(snapshot):
    from realtime_api.schemas import LoadPredictionResponse, HourlyPrediction
    now = pd.Timestamp(eastern_now_hour())
    snapshot = trim_snapshot(deepcopy(snapshot), now)
    components = snapshot["components"]
    load = components["load"]
    price = {pd.Timestamp(r["timestamp"]): r for r in components["price"]["hourly"]} if components["price"] else {}
    pv = {pd.Timestamp(t) + pd.Timedelta(hours=1): v for t, v in zip(components["pv"]["timestamps"], components["pv"]["hourly_pv_mw"])} if components["pv"] else {}
    rows = []
    for i, row in enumerate(load["hourly"] if load else []):
        ts = pd.Timestamp(row["timestamp"])
        solar = pv.get(ts)
        prices = price.get(ts, {})
        rows.append(HourlyPrediction(hour=i, timestamp=ts.isoformat(), load_forecast_mw=row["load_forecast_mw"],
            pv_estimation_mw=solar, net_load_mw=row["load_forecast_mw"] - solar if solar is not None else None,
            **{f"price_p{p}": prices.get(f"price_p{p}") for p in (10, 50, 90)}))
    quality = snapshot["quality"]
    quality["coverage_hours"] = len(rows)
    quality["forecast_start"] = rows[0].timestamp if rows else None
    quality["forecast_end"] = rows[-1].timestamp if rows else None
    degraded = any(s["status"] != "fresh" for s in quality["components"].values())
    return LoadPredictionResponse(status="degraded" if degraded else "success", predictions=rows,
        model_info=[], ensemble_weights={"tf_load_split_v1": 1.0} if load else {}, inference_time_ms=snapshot["inference_time_ms"],
        data_source=load["data_source"] if load else "unavailable", timestamp=load["generated_at"] if load else snapshot["generated_at"],
        engine=getattr(services.tf_load_price_service, "MODEL_NAME", "tf_split_v1"), pv_engine="tf_pv" if components["pv"] else "unavailable",
        origin=str(load.get("origin", now)) if load else None, input_quality=quality)
