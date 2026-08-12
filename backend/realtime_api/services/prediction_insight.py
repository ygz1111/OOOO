# -*- coding: utf-8 -*-
"""
24h 负荷预测总览（核心数据逻辑）

严格区分三类数据，互不混淆：
  1. historical_actual   : 过去真实发生的负荷（ISO-NE 真实数据，actual_load_data 表）
  2. historical_forecast : 用【过去气象】重新调用负荷模型得到的回测预测（模型验证用）
  3. future_forecast     : 用【未来气象】调用负荷模型得到的未来 24h 预测

逻辑：
  - 历史回测（T-24h ~ T）：对每个目标时刻 t_i，取其前 168h 的特征窗口
    调用模型推理 → 预测 t_i 的负荷；与真实负荷按 target_time 一一对齐，
    计算 MAE / RMSE / MAPE。这是"模型回测/验证"，不是未来预测。
  - 未来预测（T ~ T+24h）：T 时刻之前的特征窗口 → 模型推理 → 未来 24h。
    未来部分只显示预测，不显示实际（未来实际尚未发生）。
  - 当前实际负荷：T 时刻最近一条真实负荷。

数据来源：
  - 历史气象：weather_data 表（真实历史记录，覆盖过去 18 天）
  - 未来气象：Open-Meteo forecast（openmeteo_client）
  - 历史负荷：actual_load_data 表（ISO-NE 真实，data_source='iso_ne'）

复用：feature_generator.generate / build_sequence、inference_service.predict、
     normalizer.transform_features、ActualLoadDataCRUD。
"""
import asyncio
import logging
from datetime import timedelta

import numpy as np
import pandas as pd

from realtime_api.crud import ActualLoadDataCRUD
from realtime_api.database import db_manager
from realtime_api.services.container import services

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


async def _load_historical_weather(start, end) -> pd.DataFrame:
    """加载历史气象（Open-Meteo 重拉，连续真实历史；weather_data 表为按需写入不连续）"""
    try:
        df, _ = await asyncio.to_thread(_get_openmeteo_client().fetch_weather_data)
    except Exception as e:
        logger.warning(f"历史气象获取失败: {e}")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]


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
    if have_hours < total_hours:
        # 缺口用训练数据回退补（时间戳重映射到 [end-总时长, end]）
        from realtime_api.historical_load_provider import HistoricalLoadProvider
        fallback = HistoricalLoadProvider._cold_start_fallback(
            end_time=end, hours=total_hours
        )
        if fallback is not None and not fallback.empty:
            parts.append(fallback)

    if not parts:
        return pd.DataFrame()
    merged = pd.concat(parts)
    merged = merged.drop_duplicates(subset="timestamp", keep="last")
    return merged.sort_values("timestamp")


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


async def generate_load_overview() -> dict:
    """生成 24h 负荷预测总览（历史回测验证 + 未来预测 + 当前实际）"""
    now = _eastern_now_hour()
    lookback_start = now - timedelta(hours=LOOKBACK_START_HOURS)
    hist_start = now - timedelta(hours=HIST_WINDOW_HOURS)

    # ── 1. 数据获取 ──
    hist_weather = await _load_historical_weather(lookback_start, now)
    if hist_weather.empty:
        logger.warning("历史气象数据为空，历史回测跳过")
        hist_weather = pd.DataFrame(columns=[
            "timestamp", "location", "temperature_2m", "dew_point_2m",
            "relative_humidity_2m", "wind_speed_10m", "wind_direction_10m",
            "cloud_cover", "shortwave_radiation",
        ])

    # 未来气象（Open-Meteo，与历史同一客户端拉取，取未来部分）
    future_weather = pd.DataFrame()
    try:
        fetched, _ = await asyncio.to_thread(_get_openmeteo_client().fetch_weather_data)
        if fetched is not None and not fetched.empty:
            fetched = fetched.copy()
            fetched["timestamp"] = pd.to_datetime(fetched["timestamp"])
            future_weather = fetched[fetched["timestamp"] > now].copy()
            logger.info(f"未来气象 {len(future_weather)} 行（Open-Meteo）")
    except Exception as e:
        logger.warning(f"未来气象获取失败: {e}")

    # 历史负荷（真实 ISO-NE）
    hist_load = await _load_historical_load(lookback_start, now)
    if hist_load.empty:
        logger.warning("历史实际负荷为空——请先运行 scripts/fetch_iso_ne_load.py 接入实际负荷")

    # ── 2. 特征生成（历史气象 + 未来气象 + 历史负荷）──
    weather_df = pd.concat([hist_weather, future_weather], ignore_index=True)
    weather_df = weather_df.drop_duplicates(subset=["timestamp", "location"])
    try:
        features = services.feature_generator.generate(weather_df, hist_load if not hist_load.empty else None)
    except Exception as e:
        logger.error(f"特征生成失败: {e}")
        raise

    # 建立 时间 → 真实负荷 映射（用于回测对齐与当前实际）
    actual_map = {}
    if not hist_load.empty:
        for _, r in hist_load.iterrows():
            actual_map[r["timestamp"].replace(minute=0, second=0, microsecond=0)] = float(r["System_Load"])

    # ── 3. 历史回测：24 个目标时刻，逐小时滑动窗口推理 ──
    hist_pairs = []
    hist_targets = [hist_start + timedelta(hours=i) for i in range(HIST_WINDOW_HOURS)]  # T-24h ~ T-1h
    for t_i in hist_targets:
        features_i = features.loc[features.index <= t_i] if isinstance(features.index, pd.DatetimeIndex) else features
        if len(features_i) < LOOKBACK:
            continue
        try:
            normalized = services.normalizer.transform_features(features_i)
            seq = services.feature_generator.build_sequence(
                pd.DataFrame(normalized, columns=features_i.columns), lookback=LOOKBACK
            )
            pred = services.inference_service.predict(seq, inverse_transform=True)
            forecast = float(pred.ensemble_prediction[0][0])  # 第一小时 = t_i 的预测
        except Exception as e:
            logger.warning(f"历史回测 {t_i} 推理失败: {e}")
            continue

        actual = actual_map.get(t_i)
        if actual is not None:
            hist_pairs.append({
                "target_time": t_i.isoformat(),
                "historical_actual": round(actual, 1),
                "historical_forecast": round(forecast, 1),
            })

    # ── 4. 未来预测（T 之前特征 → 未来 24h）──
    future_predictions = []
    features_now = features.loc[features.index <= now] if isinstance(features.index, pd.DatetimeIndex) else features
    if len(features_now) >= LOOKBACK:
        normalized_now = services.normalizer.transform_features(features_now)
        seq_now = services.feature_generator.build_sequence(
            pd.DataFrame(normalized_now, columns=features_now.columns), lookback=LOOKBACK
        )
        future_pred = services.inference_service.predict(seq_now, inverse_transform=True)
        future_values = future_pred.ensemble_prediction[0]
        for h in range(HIST_WINDOW_HOURS):
            t = now + timedelta(hours=h + 1)
            future_predictions.append({
                "target_time": t.isoformat(),
                "future_forecast": round(float(future_values[h]), 1),
            })
    else:
        logger.warning(f"未来预测特征不足: {len(features_now)} < {LOOKBACK}")

    # ── 5. 当前实际负荷（<= now 最近一条）──
    current_actual = None
    current_time = None
    past_keys = sorted([k for k in actual_map if k <= now])
    if past_keys:
        current_time = past_keys[-1]
        current_actual = actual_map[current_time]

    # ── 6. 历史回测指标 ──
    metrics = None
    if len(hist_pairs) >= 2:
        metrics = _compute_metrics(
            [p["historical_forecast"] for p in hist_pairs],
            [p["historical_actual"] for p in hist_pairs],
        )

    return {
        "status": "success",
        "data": {
            "generated_at": now.isoformat(),
            "current": {"time": current_time.isoformat() if current_time else None,
                        "actual_load_mw": current_actual},
            "historical": {
                "pairs": hist_pairs,
                "metrics": metrics,
                "note": "历史回测：用过去气象重新调用模型，与真实负荷对比验证（非未来预测）",
            },
            "future": {
                "predictions": future_predictions,
                "note": "未来 24h 预测：未来实际负荷尚未发生，不显示",
            },
        },
    }
