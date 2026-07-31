"""
智能电网负荷预测系统 - 预测管线

完整预测流程:
  天气数据 → 数据验证 → 特征生成 → 归一化 → 序列构建 → 模型推理
  → 逆归一化 → 光伏/风电估算 → 构建响应

从 app.py 中抽取，供 routers/prediction.py 调用。

作者: 毕业设计项目
"""

import time
import logging
from datetime import timedelta
from typing import Optional, List

import numpy as np
import pandas as pd

from realtime_api.schemas import (
    LoadPredictionResponse,
    HourlyPrediction,
    ModelInfoResponse,
)
from realtime_api.services.container import (
    services,
    eastern_now,
    eastern_now_hour,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 辅助函数
# ============================================================================

def weather_points_to_df(points: List) -> pd.DataFrame:
    """将 Pydantic 气象数据点列表转为 DataFrame"""
    records = []
    for p in points:
        record = {
            "timestamp": p.timestamp,
            "location": "API_Input",
            "temperature_2m": p.temperature_2m,
            "dew_point_2m": p.dew_point_2m,
        }
        if p.relative_humidity_2m is not None:
            record["relative_humidity_2m"] = p.relative_humidity_2m
        if p.wind_speed_10m is not None:
            record["wind_speed_10m"] = p.wind_speed_10m
        if p.cloud_cover is not None:
            record["cloud_cover"] = p.cloud_cover
        if p.shortwave_radiation is not None:
            record["shortwave_radiation"] = p.shortwave_radiation
        records.append(record)

    return pd.DataFrame(records)


def load_points_to_df(points: List) -> pd.DataFrame:
    """将 Pydantic 历史负载点列表转为 DataFrame"""
    records = [
        {"timestamp": p.timestamp, "System_Load": p.system_load}
        for p in points
    ]
    return pd.DataFrame(records)


# ============================================================================
# 气象数据提取（统一提取辐射、温度、风速等，避免重复遍历）
# ============================================================================

def _extract_hourly_weather(
    clean_df: pd.DataFrame,
    now,
    hours: int = 24,
):
    """
    从清洗后的气象数据中，按预测时间窗口提取区域平均气象变量。

    合并了原来三个独立循环 (radiation / pv_weather / wind)，
    一次遍历完成所有气象变量提取。

    Returns:
        (radiation_values, temp_values, wind_speed_values,
         wind_dir_values, pressure_values, pv_weather_df)
    """
    radiation_values = []
    temp_values = []
    wind_speed_values = []
    wind_dir_values = []
    pressure_values = []
    pv_weather_rows = []

    has_timestamp = "timestamp" in clean_df.columns

    if has_timestamp:
        df = clean_df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    else:
        df = clean_df

    pv_cols = [
        "shortwave_radiation", "direct_radiation", "diffuse_radiation",
        "temperature_2m", "dew_point_2m", "relative_humidity_2m",
        "wind_speed_10m", "wind_direction_10m", "surface_pressure",
        "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    ]

    for hour in range(hours):
        pred_time = now + timedelta(hours=hour)

        if has_timestamp:
            window_start = pred_time - timedelta(minutes=30)
            window_end = pred_time + timedelta(minutes=30)
            mask = (df["timestamp"] >= window_start) & (df["timestamp"] <= window_end)
        else:
            mask = pd.Series([False] * len(df))

        if mask.any():
            rad_val = float(df.loc[mask, "shortwave_radiation"].mean()) if "shortwave_radiation" in df.columns else 0.0
            temp_val = float(df.loc[mask, "temperature_2m"].mean()) if "temperature_2m" in df.columns else 25.0
            ws_val = float(df.loc[mask, "wind_speed_10m"].mean()) if "wind_speed_10m" in df.columns else 0.0
            wd_val = float(df.loc[mask, "wind_direction_10m"].mean()) if "wind_direction_10m" in df.columns else 270.0
            sp_val = float(df.loc[mask, "surface_pressure"].mean()) if "surface_pressure" in df.columns else 1013.25

            # PV ML 行
            row = {"timestamp": pred_time}
            for col in pv_cols:
                if col in df.columns:
                    row[col] = float(df.loc[mask, col].mean())
            pv_weather_rows.append(row)
        elif len(df) > 0 and has_timestamp:
            # 取最接近的一条
            time_diffs = (df["timestamp"] - pd.Timestamp(pred_time)).abs()
            nearest_idx = time_diffs.idxmin()

            rad_val = float(df.loc[nearest_idx, "shortwave_radiation"]) if "shortwave_radiation" in df.columns else 0.0
            temp_val = float(df.loc[nearest_idx, "temperature_2m"]) if "temperature_2m" in df.columns else 25.0
            ws_val = float(df.loc[nearest_idx, "wind_speed_10m"]) if "wind_speed_10m" in df.columns else 0.0
            wd_val = float(df.loc[nearest_idx, "wind_direction_10m"]) if "wind_direction_10m" in df.columns else 270.0
            sp_val = float(df.loc[nearest_idx, "surface_pressure"]) if "surface_pressure" in df.columns else 1013.25

            # PV ML 行
            row = {"timestamp": pred_time}
            for col in pv_cols:
                if col in df.columns:
                    row[col] = float(df.loc[nearest_idx, col])
            pv_weather_rows.append(row)
        else:
            rad_val = 0.0
            temp_val = 25.0
            ws_val = 0.0
            wd_val = 270.0
            sp_val = 1013.25
            pv_weather_rows.append({"timestamp": pred_time})

        radiation_values.append(max(0.0, rad_val))
        temp_values.append(temp_val)
        wind_speed_values.append(max(0.0, ws_val))
        wind_dir_values.append(wd_val)
        pressure_values.append(sp_val)

    pv_weather_df = pd.DataFrame(pv_weather_rows)

    return (
        radiation_values,
        temp_values,
        wind_speed_values,
        wind_dir_values,
        pressure_values,
        pv_weather_df,
    )


# ============================================================================
# 主预测管线
# ============================================================================

def run_prediction_pipeline(
    weather_df: pd.DataFrame,
    historical_load_df: Optional[pd.DataFrame] = None,
) -> LoadPredictionResponse:
    """
    执行完整预测管线

    天气数据 → 数据验证 → 特征生成 → 归一化 → 序列构建 → 模型推理
    → 逆归一化 → 光伏/风电估算 → 构建响应

    Args:
        weather_df: 气象数据 DataFrame
        historical_load_df: 历史负荷数据 DataFrame（可选）

    Returns:
        LoadPredictionResponse
    """
    pipeline_start = time.perf_counter()
    now = eastern_now_hour()

    # ── 1. 数据验证 ──
    try:
        clean_df, quality_report, anomaly_flags = services.weather_validator.validate(
            weather_df, raise_on_severe=False
        )
    except Exception as e:
        logger.warning(f"数据验证失败，使用原始数据: {e}")
        clean_df = weather_df.copy()

    # ── 2. 特征生成 ──
    features = services.feature_generator.generate(clean_df, historical_load_df)

    # 2.1 只用历史数据构建模型输入序列（不含预报数据）
    if hasattr(features, 'index') and pd.api.types.is_datetime64_any_dtype(features.index):
        historical_mask = features.index <= pd.Timestamp(now)
        features_for_model = features.loc[historical_mask].copy()
        logger.info(
            f"  模型输入过滤: {len(features)} → {len(features_for_model)} 行 "
            f"(仅保留 timestamp <= {now})"
        )
    else:
        features_for_model = features.copy()
        logger.warning("  无法按时间过滤特征，使用全部数据（可能包含未来预报）")

    if len(features_for_model) < 168:
        logger.warning(
            f"  历史特征数据不足: {len(features_for_model)} < 168，"
            f"模型输入将用0填充"
        )

    # ── 3. 归一化 ──
    normalized = services.normalizer.transform_features(features_for_model)

    # ── 4. 构建序列 ──
    sequence = services.feature_generator.build_sequence(
        pd.DataFrame(normalized, columns=features_for_model.columns),
        lookback=168,
    )

    # ── 5. 模型推理 ──
    result = services.inference_service.predict(sequence, inverse_transform=True)
    ensemble_pred = result.ensemble_prediction[0]  # (24,)

    # ── 6. 一次性提取所有气象变量（合并原来3个循环）──
    (
        radiation_values,
        temp_values,
        wind_speed_values,
        wind_dir_values,
        pressure_values,
        pv_weather_df,
    ) = _extract_hourly_weather(clean_df, now, hours=24)

    # ── 7. 光伏 ML 预测（优先 ML 模型，回退物理模型）──
    pv_ml_predictions = []
    if services.pv_inference_service and services.pv_inference_service.is_ready:
        try:
            pv_result = services.pv_inference_service.predict(
                pv_weather_df,
                start_time=now,
                latitude=42.36,
                longitude=-71.06,
            )
            pv_ml_predictions = pv_result["hourly_pv_mw"]
            logger.info(
                f"光伏 ML 预测完成: 总发电 {pv_result['total_mwh']:.1f} MWh, "
                f"峰值 {pv_result['peak_mw']:.1f} MW, "
                f"耗时 {pv_result['inference_time_ms']:.1f}ms"
            )
        except Exception as e:
            logger.warning(f"光伏 ML 预测失败，回退物理模型: {e}")
            pv_ml_predictions = []

    # ── 8. 构建每小时预测结果 ──
    predictions = []

    for hour in range(min(24, len(ensemble_pred))):
        pred_time = now + timedelta(hours=hour)
        load_mw = float(ensemble_pred[hour])
        radiation = float(radiation_values[hour]) if hour < len(radiation_values) else 0.0
        temp = float(temp_values[hour]) if hour < len(temp_values) else 25.0
        wind_spd = float(wind_speed_values[hour]) if hour < len(wind_speed_values) else 0.0
        wind_dir = float(wind_dir_values[hour]) if hour < len(wind_dir_values) else 270.0
        pressure = float(pressure_values[hour]) if hour < len(pressure_values) else 1013.25

        # 光伏预测：ML 优先，物理模型回退
        if services.pv_inference_service and services.pv_inference_service.is_ready:
            if hour < len(pv_ml_predictions):
                pv_mw = float(pv_ml_predictions[hour])
            else:
                pv_mw = services.solar_estimator.estimate(radiation, temp)
        else:
            pv_mw = services.solar_estimator.estimate(radiation, temp)

        # 风电估算
        wind_mw, _, _, _ = services.wind_estimator.estimate_hourly(
            wind_speed_10m=wind_spd,
            temperature_2m=temp,
            surface_pressure=pressure,
            wind_direction=wind_dir,
        )
        net_mw = load_mw - pv_mw - wind_mw

        predictions.append(HourlyPrediction(
            hour=hour,
            timestamp=pred_time.isoformat(),
            load_forecast_mw=round(load_mw, 1),
            pv_estimation_mw=round(pv_mw, 1),
            wind_estimation_mw=round(wind_mw, 1),
            net_load_mw=round(net_mw, 1),
        ))

    # ── 9. 模型信息 ──
    model_infos = []
    for name, info in services.inference_service.get_model_info().items():
        model_infos.append(ModelInfoResponse(
            name=name,
            weight=info['weight'],
            num_params=info['num_params'],
            loaded=info['loaded'],
        ))

    pipeline_time = (time.perf_counter() - pipeline_start) * 1000

    return LoadPredictionResponse(
        status="success",
        predictions=predictions,
        model_info=model_infos,
        ensemble_weights=services.inference_service.ensemble_weights,
        inference_time_ms=round(pipeline_time, 1),
        data_source="provided" if weather_df is not None else "fallback",
        timestamp=eastern_now().isoformat(),
    )
