# -*- coding: utf-8 -*-
"""
24h 负荷预测总览（核心数据逻辑）+ 任意日期历史回测

严格区分三类数据，互不混淆：
  1. historical_actual   : 过去真实发生的负荷（ISO-NE 真实数据，actual_load_data 表）
  2. historical_forecast : 用【过去气象】重新调用负荷模型得到的回测预测（模型验证用）
  3. future_forecast     : 用【未来气象】调用负荷模型得到的未来 24h 预测

逻辑：
  - 历史回测（T-24h ~ T）：对每个目标时刻 t_i，取其前 168h 的特征窗口
    调用模型推理 → 预测 t_i+1 的负荷（模型第 0 输出对齐输入窗口末 +1h）；
    与真实负荷按 target_time 一一对齐，计算 MAE / RMSE / MAPE。
    这是"模型回测/验证"，不是未来预测。
  - 未来预测（T ~ T+24h）：T 时刻之前的特征窗口 → 模型推理 → 未来 24h。
    未来部分只显示预测，不显示实际（未来实际尚未发生）。
  - 当前实际负荷：T 时刻最近一条真实负荷。
  - 任意日期回测（generate_day_backtest）：对选定日期 D 重跑上述回测流程，
    输出 D 当天 24h 的 实际/预测/误差/指标 + 当日区域平均气象（只读，不写库）。

数据来源：
  - 历史气象：Open-Meteo Archive（ERA5 重分析）+ Forecast 补齐今天
  - 未来气象：Open-Meteo forecast（openmeteo_client）
  - 历史负荷：actual_load_data 表（ISO-NE 真实，data_source='iso_ne'）

回测与在线预测统一使用 TensorFlow 服务和 ActualLoadDataCRUD。
"""
import asyncio
import logging
import time
import hashlib
import json
import threading
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from realtime_api.crud import ActualLoadDataCRUD
from realtime_api.database import db_manager
from realtime_api.services.container import (
    services,
    get_engine_config,
    tf_load_backend_active,
    tf_pv_backend_active,
    eastern_now,
)

logger = logging.getLogger(__name__)

# 目标时刻的 lookback 长度（与模型训练一致）
LOOKBACK = 168
# 回测窗口小时数
HIST_WINDOW_HOURS = 24
# lookback 起点：最早回测目标 (T-24h) 需要前 168h 特征 → T-192h
LOOKBACK_START_HOURS = LOOKBACK + HIST_WINDOW_HOURS


def _eastern_now_hour():
    """东部时区当前整点（naive 墙钟时间，与 weather_data/actual_load_data 表一致）"""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).replace(
        minute=0, second=0, microsecond=0, tzinfo=None
    )


_OPENMETEO_CLIENT = None


def _get_openmeteo_client():
    """新建 Open-Meteo 客户端（past_days=9 覆盖 192h lookback，返回连续历史+未来）"""
    global _OPENMETEO_CLIENT
    if _OPENMETEO_CLIENT is None:
        from realtime_api.openmeteo_client import OpenMeteoClient
        _OPENMETEO_CLIENT = OpenMeteoClient(past_days=9, forecast_days=2)
    return _OPENMETEO_CLIENT


# ── Archive 历史气象缓存（2026-08 优化）──
# overview 每次请求都会重新拉 Archive（6 站点，实测拖慢至 20s+），
# 而 Archive 数据按天归档、一天内不变，加 30 分钟内存缓存即可消除重复拉取。
_ARCHIVE_CACHE: dict = {"key": None, "data": None, "timestamp": 0.0}
_ARCHIVE_CACHE_TTL = 1800  # 30 分钟
_archive_lock = __import__('threading').Lock()
# Archive API 免费层对并发敏感（无 key 6 并发实测触发 429），
# 全局限速：并发 2 + 请求间隔 1.0s，并带 429 退避重试
_archive_rate_lock = __import__('threading').Lock()
_archive_last_request = 0.0
_ARCHIVE_CONCURRENCY = 2
_ARCHIVE_REQUEST_INTERVAL = 1.0


def _fetch_archive_weather(start, end):
    """Open-Meteo Archive API（ERA5 重分析）：拉取已归档历史气象（带 30min 缓存）。

    2026-08 优化：
      - 6 站点限速并发（并发 2 + 1s 间隔；全并发会触发 Archive 429 限流）
      - 429 退避重试一次
      - 结果按 (start,end) 缓存 30 分钟（Archive 按天归档，短期不变）

    2026-08 实验结论（scripts/backtest_compare.py）：
      回测 MAPE 由 Forecast 历史预报 5.89% → Archive 4.98%（-12.5%），
      因为 Archive 与训练数据（真实历史气象）口径更一致。
    Archive 数据只到昨天（今天尚未归档），今天由 Forecast 补齐。
    """
    import time as _time
    from concurrent.futures import ThreadPoolExecutor
    import requests
    from realtime_api.config_manager import get_config

    cache_key = (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    now_ts = _time.time()
    with _archive_lock:
        if (
            _ARCHIVE_CACHE["key"] == cache_key
            and now_ts - _ARCHIVE_CACHE["timestamp"] < _ARCHIVE_CACHE_TTL
        ):
            logger.info(f"Archive 历史气象缓存命中 ({cache_key[0]}~{cache_key[1]})")
            return _ARCHIVE_CACHE["data"]

    config = get_config()
    locations = config.get_weather_locations()
    hourly_params = "temperature_2m,dew_point_2m,relative_humidity_2m,wind_speed_10m," \
                    "wind_direction_10m,wind_gusts_10m,cloud_cover,cloud_cover_low," \
                    "cloud_cover_mid,cloud_cover_high,shortwave_radiation,direct_radiation," \
                    "diffuse_radiation,surface_pressure"

    def _throttle():
        """限速：保证相邻请求至少间隔 _ARCHIVE_REQUEST_INTERVAL 秒"""
        global _archive_last_request
        with _archive_rate_lock:
            elapsed = _time.time() - _archive_last_request
            if elapsed < _ARCHIVE_REQUEST_INTERVAL:
                _time.sleep(_ARCHIVE_REQUEST_INTERVAL - elapsed)
            _archive_last_request = _time.time()

    def _fetch_one(loc):
        """拉取单个站点（供线程池并行调用，带限速与 429 重试）"""
        params = {
            "latitude": loc.get("lat", loc.get("latitude")),
            "longitude": loc.get("lon", loc.get("longitude")),
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "hourly": hourly_params,
            "timezone": "America/New_York",
        }
        for attempt in range(2):
            _throttle()
            try:
                r = requests.get(
                    "https://archive-api.open-meteo.com/v1/archive",
                    params=params,
                    timeout=60,
                )
                if r.status_code == 429 and attempt == 0:
                    logger.warning(f"Archive 429 限流，退避 5s 重试: {loc.get('name')}")
                    _time.sleep(5)
                    continue
                r.raise_for_status()
                d = r.json()["hourly"]
                rows = []
                for i, t in enumerate(d["time"]):
                    row = {"timestamp": t, "location": loc.get("name", "Boston")}
                    for param in hourly_params.split(","):
                        vals = d.get(param)
                        row[param] = vals[i] if vals and i < len(vals) else None
                    rows.append(row)
                return rows
            except requests.exceptions.RequestException as e:
                if attempt == 0:
                    logger.warning(f"Archive 拉取失败，重试: {loc.get('name')}: {e}")
                    _time.sleep(2)
                    continue
                logger.error(f"Archive 拉取最终失败: {loc.get('name')}: {e}")
                return []
        return []

    with ThreadPoolExecutor(max_workers=_ARCHIVE_CONCURRENCY) as pool:
        results = list(pool.map(_fetch_one, locations))

    records = [row for rows in results for row in rows]
    df = pd.DataFrame(records)

    with _archive_lock:
        _ARCHIVE_CACHE.update(key=cache_key, data=df, timestamp=now_ts)
    logger.info(f"Archive 历史气象拉取完成（限速并发 {len(locations)} 站点）: {len(df)} 行")
    return df


async def _load_historical_weather(start, end) -> pd.DataFrame:
    """历史气象：Archive(ERA5 重分析) 为主 + Forecast 补齐今天。

    2026-08 实验验证（不重训模型）：Archive 与训练数据口径更一致，
    24h 回测 MAPE 5.89% → 4.98%。Archive 仅到昨天，今天的小时用
    Forecast past_days 补齐（今日数据量小，影响可忽略）。
    """
    parts = []
    today = _eastern_now_hour().date()
    # 任意旧日期回测只需该日期窗口，不要从输入起点一直下载到昨天。
    archive_end = min(today - timedelta(days=1), end.date())

    # 1. Archive：只读取请求窗口内已归档的日期。
    if start.date() <= archive_end:
        try:
            # Open-Meteo end_date 是包含当天的，不要把未归档的下一天也请求进去。
            arc = await asyncio.to_thread(_fetch_archive_weather, start, archive_end)
            if arc is not None and not arc.empty:
                arc["timestamp"] = pd.to_datetime(arc["timestamp"])
                parts.append(arc)
                logger.info(f"历史气象(Archive/ERA5): {len(arc)} 行")
        except Exception as e:
            logger.warning(f"Archive 历史气象获取失败，回退 Forecast: {e}")

    # 2. Forecast 补齐今天未归档的小时（2026-08 修复：按 [start,end] 窗口过滤，
    #    此前只保留"今天"导致 Archive 失败时历史气象严重不足、回测/未来预测全空；
    #    Forecast 客户端 past_days=9 已覆盖完整回看窗口）
    try:
        df, _ = await asyncio.to_thread(_get_openmeteo_client().fetch_weather_data)
        if df is not None and not df.empty:
            df = df.copy()
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
            if len(df) > 0:
                parts.append(df)
    except Exception as e:
        logger.warning(f"Forecast 历史气象获取失败: {e}")

    if not parts:
        logger.warning("历史气象数据为空")
        return pd.DataFrame()

    merged = pd.concat(parts, ignore_index=True)
    # Archive 优先（排前面），同时间戳去重保留 Archive
    merged = merged.drop_duplicates(subset=["timestamp", "location"], keep="first")
    merged = merged.sort_values("timestamp").reset_index(drop=True)
    return merged[(merged["timestamp"] >= start) & (merged["timestamp"] <= end)]


async def _load_historical_load(start, end) -> pd.DataFrame:
    """历史负荷：ISO-NE 真实（actual_load_data）优先，缺口用训练数据回退补全

    注意：回测对比的"实际值"只用 ISO-NE 真实数据（actual_map 只由真实行构建）；
    训练数据回退仅用于填充 lookback 特征输入（模型输入的历史负荷序列）。
    """
    rows = await ActualLoadDataCRUD.get_actual_load_by_time_range(start, end)
    parts = []
    if rows:
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        parts.append(df.rename(columns={"actual_load_mw": "System_Load"})[["timestamp", "System_Load"]].astype({"System_Load": float}))

    total_hours = int((end - start).total_seconds() // 3600)
    have_hours = len(parts[0]) if parts else 0

    if have_hours >= total_hours:
        # 覆盖完整：直接使用真实数据
        merged = parts[0].drop_duplicates(subset="timestamp", keep="last").sort_values("timestamp")
        return merged

    # 缺口处理（2026-08 修复）：真实数据 ffill 补缺优先。
    # 此前用训练数据时间戳重映射补缺——重映射的负荷是"过去年份某天的模式"，
    # 与实际相差可达数千 MW，会污染 lag_168/rolling_168 等特征，导致回测误差
    # 被放大近一倍（实验对比：ffill 补缺 MAPE 4.98% vs 重映射补缺 9.85%）。
    # 仅当完全没有真实数据时才回退训练数据冷启动。
    if have_hours == 0:
        from realtime_api.historical_load_provider import HistoricalLoadProvider
        fallback = HistoricalLoadProvider._cold_start_fallback(
            end_time=end, hours=total_hours
        )
        return fallback if fallback is not None and not fallback.empty else pd.DataFrame()

    logger.warning(
        f"真实负荷覆盖 {have_hours}/{total_hours} h，缺口用相邻真实值前向填充"
        f"（建议运行 scripts/fetch_iso_ne_load.py 或等待后台同步补满 14 天）"
    )
    merged = parts[0].drop_duplicates(subset="timestamp", keep="last").set_index("timestamp")
    full_range = pd.date_range(start=merged.index.min(), end=merged.index.max(), freq="h")
    merged = merged.reindex(full_range).ffill().bfill()
    return merged.reset_index().rename(columns={"index": "timestamp"})


def _compute_metrics(forecasts: np.ndarray, actuals: np.ndarray) -> dict:
    """MAE/RMSE/MAPE（真实 MW 单位，|actual|>1 掩码防除零）"""
    f = np.asarray(forecasts, dtype=float)
    a = np.asarray(actuals, dtype=float)
    mae = float(np.mean(np.abs(a - f)))
    rmse = float(np.sqrt(np.mean((a - f) ** 2)))
    mask = np.abs(a) > 1.0
    mape = float(np.mean(np.abs((a[mask] - f[mask]) / a[mask])) * 100) if np.any(mask) else None
    return {"mae_mw": round(mae, 1), "rmse_mw": round(rmse, 1),
            "mape": round(mape, 2) if mape is not None else None}


def _regional_hourly_weather(weather_df, day_start, hours=HIST_WINDOW_HOURS) -> list:
    """按小时聚合多站点区域平均气象（与特征工程区域平均口径一致）。

    返回与回测目标时刻一一对齐的气象行：
      target_time + temperature_2m / wind_speed_10m / cloud_cover / shortwave_radiation
    无数据的时刻置 None。
    """
    cols = ["temperature_2m", "wind_speed_10m", "cloud_cover", "shortwave_radiation"]
    if weather_df is None or weather_df.empty:
        return []
    df = weather_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    rows = []
    for h in range(hours):
        t = day_start + timedelta(hours=h)
        part = df[df["timestamp"] == t]
        row = {"target_time": t.isoformat()}
        for col in cols:
            vals = pd.to_numeric(part[col], errors="coerce").dropna() if not part.empty else pd.Series(dtype=float)
            row[col] = round(float(vals.mean()), 1) if len(vals) else None
        rows.append(row)
    return rows


# ============================================================================
# overview 结果缓存（60s TTL）+ 并发单飞
# ============================================================================
# overview 每次请求要执行 24 次历史回测推理 + 历史气象拉取（冷缓存实测约 26s），
# 前端多个页面/组件会同时轮询该端点。除短 TTL 缓存外：
#   - 2026-08 修复：旧实现把整个计算包在 asyncio.Lock 内，首屏并发时等待者
#     阻塞在锁上直至首个请求完成（~26s），叠加前端重试极易触发网关超时（504）。
#     现改为 single-flight：计算期间所有并发请求共享同一任务，首个完成即全体返回；
#     首个请求即使被取消，任务也继续在后台完成并写缓存（asyncio.shield）。
_OVERVIEW_CACHE: dict = {"timestamp": 0.0, "data": None}
_OVERVIEW_CACHE_TTL = 60.0
_overview_inflight = None  # Optional[asyncio.Task]
_TF_BACKTEST_CACHE: dict = {"windows": None, "service": None, "pairs": None}
_tf_backtest_lock = threading.Lock()


# ============================================================================
# TF 模式总览（live 使用官方在线数据；demo 使用冻结验收窗口）
# ============================================================================

def _run_tf_historical_backtest(windows: list[dict], force_refresh: bool = False) -> list[dict]:
    # Live snapshots are deep-copied: object identity never survives a request.
    # Hash inputs AND labels, so revisions invalidate results even in the same hour.
    key = hashlib.sha256(json.dumps(windows, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
    with _tf_backtest_lock:
        return _run_tf_historical_backtest_cached(windows, key, force_refresh)


def _run_tf_historical_backtest_cached(windows: list[dict], key: str, force_refresh: bool) -> list[dict]:
    """逐小时回溯验证；独立负荷模型可只使用目标小时的未来特征。"""
    if (not force_refresh and _TF_BACKTEST_CACHE.get("key") == key
            and _TF_BACKTEST_CACHE["service"] is services.tf_load_price_service):
        return [dict(pair) for pair in _TF_BACKTEST_CACHE["pairs"]]
    pairs = []
    for window in windows:
        service = services.tf_load_price_service
        first_step = getattr(service, "predict_load_first_step_features", None)
        if len(window["future"]) == 1 and callable(first_step):
            result = first_step(window["past"], window["future"])
        elif hasattr(service, "predict_task_features"):
            result = service.predict_task_features("load", window["past"], window["future"])
        else:
            result = service.predict_features(window["past"], window["future"])
        prediction = result["hourly"][0]
        target_time = pd.Timestamp(window["target_time"]).isoformat()
        if pd.Timestamp(prediction["timestamp"]) != pd.Timestamp(target_time):
            raise RuntimeError(
                "TF 回测时间对齐失败: "
                f"预测={prediction['timestamp']}, 真实={target_time}"
            )
        pairs.append({
            "target_time": target_time,
            "historical_actual": float(window["actual_load_mw"]),
            "historical_forecast": float(prediction["load_forecast_mw"]),
        })
    _TF_BACKTEST_CACHE.update(key=key, windows=None, service=services.tf_load_price_service,
                             pairs=[dict(pair) for pair in pairs])
    return pairs


async def _generate_tf_overview_impl() -> dict:
    """TF 引擎（独立负荷/电价 + pv_v2）的 24h 总览。

    live 模式会对锚点前 24 个小时分别做一次 168h→24h 回溯推理，并将
    每次第 0 步预测与该小时 ISO-NE 实际负荷对齐。
    """
    mode = str(get_engine_config().get("inference_mode", "live")).lower()
    if mode == "live":
        from realtime_api.services.live_forecast import request_live_snapshot, snapshot_response
        snapshot = await request_live_snapshot()
        pairs = snapshot["history"]
        backtest_error = False
        try:
            backtest = await asyncio.to_thread(_run_tf_historical_backtest, snapshot["load_backtest"])
            mapped = {pd.Timestamp(p["target_time"]): p for p in backtest}
            pairs = [mapped.get(pd.Timestamp(p["target_time"]), p) for p in pairs]
        except Exception as exc:
            backtest_error = True
            logger.warning("负荷历史回测暂时不可用: %s", type(exc).__name__, exc_info=True)
        valid = [p for p in pairs if p["historical_forecast"] is not None and p["historical_actual"] is not None]
        metrics = _compute_metrics([p["historical_forecast"] for p in valid], [p["historical_actual"] for p in valid]) if len(valid) >= 2 else None
        missing = len(pairs) - len(valid)
        historical_note = (
            f"事后天气回溯验证，非当时在线预测精度；仅统计{len(valid)}个有效观测配对，补值不作为实际值。"
        )
        if missing:
            historical_note += (
                f"{missing}个小时暂缺回测结果："
                + ("回测计算暂时失败。" if backtest_error else
                   "资料更新中，或目标小时的历史、日前及气象输入尚不完整；资料齐全后自动重试。")
            )
        response = snapshot_response(snapshot)
        return {"status": response.status, "data": {
            "generated_at": response.timestamp, "current": snapshot["current"],
            "historical": {"pairs": pairs, "metrics": metrics,
                "note": historical_note},
            "future": {"predictions": [{"target_time": r.timestamp, "future_forecast": r.load_forecast_mw,
                "pv_forecast_mw": r.pv_estimation_mw, "price_p10": r.price_p10, "price_p50": r.price_p50, "price_p90": r.price_p90}
                for r in response.predictions], "note": "每个时间点表示该小时结束时间；缺失模块留空，不用0代替。"},
            "input_quality": response.input_quality, "data_source": response.data_source,
            "engine": response.engine, "pv_engine": response.pv_engine,
        }}
    bundle = None
    hist_pairs = []
    metrics = None
    if mode == "live":
        weather_df, _ = await asyncio.to_thread(services.openmeteo_client.fetch_weather_data)
        bundle = await asyncio.to_thread(services.tf_realtime_feature_provider.build, weather_df)
        tf_res = await asyncio.to_thread(
            services.tf_load_price_service.predict_features,
            bundle["load_price"]["past"], bundle["load_price"]["future"],
        )
        hist_pairs = await asyncio.to_thread(
            _run_tf_historical_backtest, bundle["load_price_backtest"]
        )
        if len(hist_pairs) >= 2:
            metrics = _compute_metrics(
                [pair["historical_forecast"] for pair in hist_pairs],
                [pair["historical_actual"] for pair in hist_pairs],
            )
    else:
        tf_res = services.tf_load_price_service.predict()
    rows = tf_res["hourly"]
    pv_mw: list = []
    pv_engine = "none"
    if tf_pv_backend_active():
        try:
            if mode == "live":
                pv_res = await asyncio.to_thread(
                    services.tf_pv_service.predict_features,
                    bundle["pv"]["past"], bundle["pv"]["future"],
                )
            else:
                pv_res = services.tf_pv_service.predict()
            pv_mw = list(pv_res["hourly_pv_mw"])
            pv_engine = "tf_pv"
        except Exception as e:
            logger.warning(f"TF pv_v2 总览预测失败: {e}")

    future_predictions = []
    for k, row in enumerate(rows[:24]):
        future_predictions.append({
            "target_time": row["timestamp"],
            "future_forecast": row["load_forecast_mw"],
            "price_p10": row.get("price_p10"),
            "price_p50": row.get("price_p50"),
            "price_p90": row.get("price_p90"),
            "price_unit": "USD/MWh",
            "pv_forecast_mw": round(pv_mw[k], 1) if k < len(pv_mw) else None,
        })

    current_actual = tf_res.get("anchor_actual_load_mw")
    current_time = tf_res.get("origin")
    if mode != "live":
        # 冻结验收模式只有尾部样本，没有官方在线历史特征窗口；明确不伪造回测预测。
        hist_pairs = [
            {
                "target_time": h["target_time"],
                "historical_actual": h["actual_load_mw"],
                "historical_forecast": None,
            }
            for h in tf_res.get("anchor_history_actual", [])
        ]

    return {
        "status": "success",
        "data": {
            "generated_at": eastern_now().isoformat(),
            "current": {"time": current_time, "actual_load_mw": current_actual},
            "historical": {
                "pairs": hist_pairs,
                "metrics": metrics,
                "note": (
                    "TF live 回溯验证：过去24个锚点使用 ISO-NE 实际负荷、日前曲线和"
                    "事后可得天气构建特征；因此用于模型回测，不等同于当时天气预报的在线精度。"
                    if mode == "live" else
                    "TF demo 模式：仅展示冻结样本的历史实际值，不执行逐小时回测。"
                ),
            },
            "future": {
                "predictions": future_predictions,
                "note": f"TF {mode} 模式：未来 24h 负荷+电价(p10/p50/p90, USD/MWh)+光伏 (pv_engine={pv_engine}); "
                        "锚点时间见 current.time",
            },
            "input_quality": bundle.get("input_quality") if bundle else None,
            "data_source": bundle.get("data_source") if bundle else tf_res.get("data_source"),
            "engine": services.tf_load_price_service.MODEL_NAME,
            "pv_engine": pv_engine,
        },
    }

async def generate_load_overview(force_refresh: bool = False) -> dict:
    """生成 24h 负荷预测总览（60s 缓存 + 并发单飞）"""
    import time
    global _overview_inflight

    now_ts = time.time()
    from realtime_api.services.live_forecast import quality_cache_valid
    # 快速路径：缓存命中直接返回（无锁、无等待）
    if (
        not force_refresh and _OVERVIEW_CACHE["data"] is not None
        and not (_OVERVIEW_CACHE["data"].get("data", {}).get("input_quality") or {}).get("refresh_in_progress")
        and quality_cache_valid(_OVERVIEW_CACHE["data"].get("data", {}).get("input_quality"))
        and now_ts - _OVERVIEW_CACHE["timestamp"] < _OVERVIEW_CACHE_TTL
        and _OVERVIEW_CACHE.get("hour") == _eastern_now_hour()
    ):
        return _OVERVIEW_CACHE["data"]

    # 单飞路径：已有计算任务在跑，共享同一结果（不再排队各自计算）
    if _overview_inflight is not None and not _overview_inflight.done():
        try:
            result = await asyncio.shield(_overview_inflight)
            if not force_refresh:
                return result
        except asyncio.CancelledError:
            # 调用者被取消：任务继续后台完成并写缓存，保留引用供后续请求共享
            raise

    # 创建新计算任务
    task = asyncio.create_task(_compute_and_cache_overview())
    _overview_inflight = task
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        raise
    finally:
        # 仅当任务已结束时清理引用；取消场景下任务仍在后台跑，保留引用
        if _overview_inflight is task and task.done():
            _overview_inflight = None


async def _compute_and_cache_overview() -> dict:
    """执行 overview 计算并写缓存（供 single-flight 任务使用）"""
    try:
        source_hour = _eastern_now_hour()
        data = await _generate_load_overview_impl()
        _OVERVIEW_CACHE["data"] = data
        # 从完成时计时，避免一次60秒计算完成后缓存已经过期。
        _OVERVIEW_CACHE["timestamp"] = time.time()
        _OVERVIEW_CACHE["hour"] = source_hour
        return data
    except Exception:
        # 计算失败：清理 in-flight 引用，允许后续请求重新触发
        global _overview_inflight
        if _overview_inflight is not None:
            _overview_inflight = None
        raise


async def _generate_load_overview_impl() -> dict:
    """使用当前 TensorFlow 模型生成 24 小时预测总览。"""
    if str(get_engine_config().get("inference_mode", "live")).lower() != "live" and not tf_load_backend_active():
        raise RuntimeError("TensorFlow 负荷与电价模型未就绪")
    return await _generate_tf_overview_impl()


# ============================================================================
# 任意日期历史回测（按天重跑模型验证，不重训模型）
# ============================================================================
# 每次回测需要 24 次模型推理 + 历史气象拉取（冷缓存较慢），前端切换日期/重试时
# 会反复触发。按日期字符串缓存 60s（Archive 按天归档、真实负荷按小时回填，
# 60s 内结果不变），风格同 _ARCHIVE_CACHE。
_DAY_BACKTEST_CACHE: dict = {"key": None, "data": None, "timestamp": 0.0}
_DAY_BACKTEST_CACHE_TTL = 60.0
_day_backtest_lock = __import__('threading').Lock()


async def generate_day_backtest(day=None, *, force_refresh: bool = False) -> dict:
    """任意日期历史回测：对选定日期 D（ET 墙钟）重跑模型并与 ISO-NE 真实负荷对比。

    - day=None：仅返回 available_date_range（轻量，供前端初始化日期选择器）
    - day=过去某天：回测 D 00:00 ~ 23:00 共 24 个目标小时
        · 目标小时 H 的输入窗口截止 H-1h（模型第 0 输出 = 窗口末+1h）
        · 历史气象：ERA5 Archive + Forecast 补齐（复用 _load_historical_weather）
        · 真实值：仅 ISO-NE 真实行（actual_load_data），绝不使用训练数据冷启动重映射
        · 输出：24 对 实际/预测 + 误差 + 指标 + 当日逐小时区域平均气象

    返回 inner data dict（不含 status/message 外壳，由路由统一封装）。
    只读计算，不写任何数据表。
    """
    import time as _time

    # ── 可用日期范围（两种模式都返回，供前端限制日期选择器）──
    bounds = await ActualLoadDataCRUD.get_time_bounds()
    earliest = bounds.get("earliest")
    latest = bounds.get("latest")
    # 按日回测会为当天每个目标小时构建严格的“只看过去”输入窗口；当天
    # 尚未结束时，晚些小时的 RT_Demand/RT_LMP 尚不存在，不能伪造完整回测。
    # 所以前端可选上限是最后一个完整 ISO-NE 实际负荷日，而非最新小时记录。
    latest_complete_day = None
    if latest is not None:
        latest_ts = pd.Timestamp(latest)
        latest_complete_day = (
            latest_ts.date()
            if latest_ts.hour >= 23
            else (latest_ts - pd.Timedelta(days=1)).date()
        )
    available_range = {
        "earliest": earliest.date().isoformat() if earliest else None,
        "latest": latest_complete_day.isoformat() if latest_complete_day else None,
    }

    if day is None:
        return {"available_date_range": available_range}

    # ── 日期合法性校验 ──
    today = _eastern_now_hour().date()
    if day > today:
        raise ValueError(f"回测日期 {day.isoformat()} 晚于今天，只能回测今天及以前的日期")
    if earliest is None or latest_complete_day is None:
        raise ValueError("数据库中暂无 ISO-NE 实际负荷数据，无法进行历史回测")
    if day < earliest.date() or day > latest_complete_day:
        raise ValueError(
            f"回测日期 {day.isoformat()} 超出可用真实负荷范围 "
            f"（{available_range['earliest']} ~ {available_range['latest']}）"
        )

    # ── 按日期缓存（60s TTL）──
    cache_key = day.isoformat()
    now_ts = _time.time()
    with _day_backtest_lock:
        if (
            not force_refresh
            and
            _DAY_BACKTEST_CACHE["key"] == cache_key
            and now_ts - _DAY_BACKTEST_CACHE["timestamp"] < _DAY_BACKTEST_CACHE_TTL
        ):
            logger.info(f"按日回测缓存命中 ({cache_key})")
            return _DAY_BACKTEST_CACHE["data"]

    data = await _generate_day_backtest_impl(day, available_range, force_refresh=force_refresh)

    with _day_backtest_lock:
        _DAY_BACKTEST_CACHE.update(key=cache_key, data=data, timestamp=_time.time())
    return data


async def _generate_day_backtest_impl(day, available_range, *, force_refresh: bool = False) -> dict:
    """按日回测实际计算逻辑（无缓存，使用当前选定的 TensorFlow 引擎）。"""
    day_start = datetime(day.year, day.month, day.day)  # naive ET 墙钟 00:00
    day_end = day_start + timedelta(hours=23)           # 最后一个目标小时 23:00

    if not tf_load_backend_active() or not services.tf_realtime_feature_provider:
        raise RuntimeError("TensorFlow 负荷预测模型未就绪，暂不能进行历史回测")
    first_step = callable(getattr(services.tf_load_price_service, "predict_load_first_step_features", None))
    future_hours = 1 if first_step else 24

    # ── 1. 目标日真实负荷（仅 ISO-NE 真实行，构建 actual_map 与覆盖校验）──
    actual_rows = await ActualLoadDataCRUD.get_actual_load_by_time_range(day_start, day_end)
    if not actual_rows:
        raise ValueError(
            f"所选日期 {day.isoformat()} 无 ISO-NE 实际负荷数据"
            f"（可用范围 {available_range['earliest']} ~ {available_range['latest']}）"
        )
    actual_map = {
        pd.to_datetime(r["timestamp"]).replace(minute=0, second=0, microsecond=0): float(r["actual_load_mw"])
        for r in actual_rows
    }

    # ── 2. 历史气象：同时覆盖 168h 序列和其中的 168h 滞后特征。
    # Archive/ERA5 覆盖已归档日期；当日及下一日由 Forecast 补齐。
    weather_start = day_start - timedelta(days=16)
    weather_end = day_end + timedelta(hours=future_hours - 1)
    hist_weather = await _load_historical_weather(weather_start, weather_end)
    if hist_weather.empty:
        raise RuntimeError("历史气象获取失败，暂不能进行历史回测")

    # ── 3. TensorFlow 严格特征窗口 + 24 个逐小时回测推理。
    # 每个目标小时的输入只含该时刻以前的 RT 数据；模型第 0 个输出与目标对齐。
    windows = await asyncio.to_thread(
        services.tf_realtime_feature_provider.build_day_backtest, day, hist_weather,
        **({"future_hours": 1} if first_step else {}),
    )
    pairs = await asyncio.to_thread(_run_tf_historical_backtest, windows, force_refresh)
    # 页面真实值统一采用本项目已入库的 ISO-NE actual_load_data；以此支持尚未回填
    # 小时展示为 null，且不把模型输入源与评价标签混为一谈。
    for pair in pairs:
        target = pd.Timestamp(pair["target_time"]).to_pydatetime()
        actual = actual_map.get(target)
        pair["historical_actual"] = round(actual, 1) if actual is not None else None

    if len(pairs) != HIST_WINDOW_HOURS:
        raise RuntimeError(f"TensorFlow 历史回测窗口不完整：期望 {HIST_WINDOW_HOURS} 小时，实际 {len(pairs)} 小时")

    # ── 4. 补充误差字段（正=高估，口径与 /diagnostics/hourly-errors 一致）──
    # 补充误差字段（正=高估，口径与 /diagnostics/hourly-errors 一致）
    for p in pairs:
        actual = p["historical_actual"]
        if actual is None:
            p.update(error_mw=None, absolute_error_mw=None, percentage_error=None)
            continue
        err = p["historical_forecast"] - actual
        p.update(
            error_mw=round(err, 2),
            absolute_error_mw=round(abs(err), 2),
            percentage_error=round(err / actual * 100, 2) if abs(actual) > 1e-6 else None,
        )

    # ── 5. 当日区域平均气象（与回测目标时刻对齐，供前端叠加展示）──
    weather = _regional_hourly_weather(hist_weather, day_start, hours=HIST_WINDOW_HOURS)

    # ── 6. 指标（≥2 个有效配对才计算）──
    valid = [p for p in pairs if p["historical_actual"] is not None]
    metrics = (
        _compute_metrics(
            [p["historical_forecast"] for p in valid],
            [p["historical_actual"] for p in valid],
        )
        if len(valid) >= 2 else None
    )

    return {
        "date": day.isoformat(),
        "timezone": "America/New_York",
        "available_date_range": available_range,
        "pairs": pairs,
        "metrics": metrics,
        "weather": weather,
        "note": (
            "历史回测：用该日之前的历史气象重新调用模型得到预测，"
            "与该日 ISO-NE 真实负荷对比验证（非未来预测）；"
            "误差=预测−实际（正=高估），实际负荷尚未回填的小时为空。"
        ),
    }
