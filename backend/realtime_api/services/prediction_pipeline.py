"""TensorFlow 负荷、电价和光伏统一预测管线。"""

import time
from typing import List, Optional

import pandas as pd

from realtime_api.schemas import HourlyPrediction, LoadPredictionResponse, ModelInfoResponse
from realtime_api.services.container import (
    eastern_now,
    get_engine_config,
    services,
    tf_load_backend_active,
    tf_pv_backend_active,
)


def weather_points_to_df(points: List) -> pd.DataFrame:
    """将请求中的气象点转换为 TensorFlow 在线特征服务可用的数据表。"""
    records = []
    for point in points:
        record = {
            "timestamp": point.timestamp,
            "location": "API_Input",
            "temperature_2m": point.temperature_2m,
            "dew_point_2m": point.dew_point_2m,
        }
        for name in (
            "relative_humidity_2m",
            "wind_speed_10m",
            "cloud_cover",
            "shortwave_radiation",
        ):
            value = getattr(point, name, None)
            if value is not None:
                record[name] = value
        records.append(record)
    return pd.DataFrame(records)


def load_points_to_df(points: List) -> pd.DataFrame:
    """将请求中的历史负荷点转换为数据表。"""
    return pd.DataFrame([
        {"timestamp": point.timestamp, "System_Load": point.system_load}
        for point in points
    ])


def run_tf_prediction_pipeline(
    weather_df: Optional[pd.DataFrame] = None,
    historical_load_df: Optional[pd.DataFrame] = None,
    tf_load_price_features: Optional[dict] = None,
    tf_pv_features: Optional[dict] = None,
) -> LoadPredictionResponse:
    """执行 TensorFlow 负荷、电价、光伏 24 小时预测。"""
    del historical_load_df  # 在线特征服务读取权威历史负荷，保留参数以兼容 API。
    pipeline_start = time.perf_counter()

    mode = str(get_engine_config().get("inference_mode", "live")).strip().lower()
    if mode == "live" and weather_df is None and not tf_load_price_features and not tf_pv_features:
        from realtime_api.services.live_forecast import get_live_snapshot, snapshot_response
        return snapshot_response(get_live_snapshot())

    if not tf_load_backend_active():
        raise RuntimeError("TensorFlow 负荷与电价模型服务未就绪")
    if not tf_pv_backend_active():
        raise RuntimeError("TensorFlow 光伏模型服务未就绪")

    mode = str(get_engine_config().get("inference_mode", "live")).strip().lower()
    live_source = None
    live_quality = None
    live_origin = None
    if mode == "live" and (not tf_load_price_features or not tf_pv_features):
        if not services.tf_realtime_feature_provider:
            raise RuntimeError("TensorFlow 实时特征服务未初始化")
        bundle = services.tf_realtime_feature_provider.build(weather_df)
        live_source = bundle.get("data_source")
        live_quality = bundle.get("input_quality")
        live_origin = bundle.get("origin_hour_end")
        tf_load_price_features = tf_load_price_features or bundle["load_price"]
        tf_pv_features = tf_pv_features or bundle["pv"]

    if tf_load_price_features:
        tf_result = services.tf_load_price_service.predict_features(
            tf_load_price_features.get("past", []),
            tf_load_price_features.get("future", []),
        )
    elif mode == "demo":
        tf_result = services.tf_load_price_service.predict()
    else:
        raise ValueError(
            "TensorFlow live 模式缺少负荷/电价特征："
            "必须提供过去168小时和未来24小时完整特征"
        )

    if live_source:
        tf_result["data_source"] = live_source
    load_rows = tf_result["hourly"]
    if len(load_rows) < 24:
        raise RuntimeError(f"TensorFlow 负荷/电价输出异常: {len(load_rows)} 行")

    try:
        if tf_pv_features:
            pv_result = services.tf_pv_service.predict_features(
                tf_pv_features.get("past", []),
                tf_pv_features.get("future", []),
            )
        elif mode == "demo":
            pv_result = services.tf_pv_service.predict()
        else:
            raise ValueError(
                "TensorFlow live 模式缺少光伏特征："
                "必须提供过去96小时和未来24小时完整特征"
            )
    except Exception as exc:
        raise RuntimeError(f"TensorFlow 光伏在线预测失败: {exc}") from exc

    if live_source:
        pv_result["data_source"] = live_source
    pv_values = pv_result["hourly_pv_mw"]
    if len(pv_values) < 24:
        raise RuntimeError(f"TensorFlow 光伏输出异常: {len(pv_values)} 行")

    load_timestamps = pd.DatetimeIndex(
        pd.to_datetime([row["timestamp"] for row in load_rows[:24]])
    )
    pv_hour_end = (
        pd.DatetimeIndex(pd.to_datetime(pv_result["timestamps"][:24]))
        + pd.Timedelta(hours=1)
    )
    if not load_timestamps.equals(pv_hour_end):
        raise ValueError("TensorFlow 负荷/电价与光伏预测窗口不一致")

    predictions = []
    for index, row in enumerate(load_rows[:24]):
        load_mw = float(row["load_forecast_mw"])
        pv_mw = float(pv_values[index])
        predictions.append(HourlyPrediction(
            hour=int(row["hour"]),
            timestamp=row["timestamp"],
            load_forecast_mw=round(load_mw, 1),
            pv_estimation_mw=round(pv_mw, 1),
            net_load_mw=round(load_mw - pv_mw, 1),
            price_p10=row.get("price_p10"),
            price_p50=row.get("price_p50"),
            price_p90=row.get("price_p90"),
        ))

    model_infos = []
    for service in (services.tf_load_price_service, services.tf_pv_service):
        for name, info in service.get_model_info().items():
            model_infos.append(ModelInfoResponse(
                name=name,
                weight=float(info.get("weight", 1.0)),
                num_params=int(info.get("num_params", 0)),
                loaded=bool(info.get("loaded", True)),
            ))

    pipeline_time = (time.perf_counter() - pipeline_start) * 1000
    return LoadPredictionResponse(
        status="success",
        predictions=predictions,
        model_info=model_infos,
        ensemble_weights={
            services.tf_load_price_service.MODEL_NAME: 1.0,
            services.tf_pv_service.MODEL_NAME: 1.0,
        },
        inference_time_ms=round(max(pipeline_time, tf_result.get("inference_time_ms", 0)), 1),
        data_source=tf_result.get("data_source", "unknown"),
        timestamp=eastern_now().isoformat(),
        engine=services.tf_load_price_service.MODEL_NAME,
        pv_engine="tf_pv",
        origin=live_origin or tf_result.get("origin"),
        input_quality=live_quality,
    )


def dispatch_prediction(
    weather_df: Optional[pd.DataFrame] = None,
    historical_load_df: Optional[pd.DataFrame] = None,
    tf_load_price_features: Optional[dict] = None,
    tf_pv_features: Optional[dict] = None,
) -> LoadPredictionResponse:
    """唯一预测入口：始终使用 TensorFlow 模型。"""
    return run_tf_prediction_pipeline(
        weather_df,
        historical_load_df,
        tf_load_price_features=tf_load_price_features,
        tf_pv_features=tf_pv_features,
    )


__all__ = [
    "dispatch_prediction",
    "run_tf_prediction_pipeline",
    "weather_points_to_df",
    "load_points_to_df",
]
