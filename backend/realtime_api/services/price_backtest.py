"""Read-only historical price replay using the production TensorFlow price model."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from realtime_api.services.container import get_engine_config, services
from realtime_api.utils.iso_ne import get_credentials


def _date_range(frozen_range: dict[str, str]) -> dict[str, str]:
    """Offer completed candidate days without pretending the source is preloaded.

    The no-date request must remain cheap. Individual dates are checked against
    all required model inputs before inference; missing labels are excluded.
    """
    result = dict(frozen_range)
    mode = str(get_engine_config().get("inference_mode", "live")).lower()
    if mode != "live" or not get_credentials()[0]:
        return result
    yesterday = datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)
    if yesterday.isoformat() > result["latest"]:
        result["latest"] = yesterday.isoformat()
    return result


def _replay_result(day: date, available_range: dict[str, str], inputs: dict, prediction: dict) -> dict:
    """Pair 24 model outputs with verified ISO-NE RT-LMP labels, hour by hour."""
    rows = prediction.get("hourly") or []
    actual_rows = inputs.get("actual") or []
    if len(rows) != 24 or len(actual_rows) != 24:
        raise ValueError("电价回测需要完整的 24 个预测和标签时间槽")

    points = []
    actual_values = []
    errors = []
    coverage = []
    input_only_hours = missing_hours = 0
    expected_times = pd.date_range(pd.Timestamp(day) + pd.Timedelta(hours=1), periods=24, freq="h")
    edges = expected_times.union(expected_times - pd.Timedelta(hours=1)).tz_localize(
        "America/New_York", ambiguous="NaT", nonexistent="NaT")
    if edges.isna().any():
        raise ValueError("当前电价模型使用本地24小时窗口，夏令时切换日暂不支持可靠回测")
    for index, (forecast, observation) in enumerate(zip(rows, actual_rows)):
        predicted_time = pd.Timestamp(forecast["timestamp"])
        actual_time = pd.Timestamp(observation["ts_local"])
        if predicted_time != actual_time or predicted_time != expected_times[index]:
            raise ValueError(
                f"电价回测预测与真实值的小时不一致: "
                f"预期 {expected_times[index]}, 预测 {predicted_time}, 真实 {actual_time}"
            )
        quantiles = [float(forecast[f"price_p{p}"]) for p in (10, 50, 90)]
        if not np.isfinite(quantiles).all() or quantiles != sorted(quantiles):
            raise ValueError(f"电价回测包含无效预测分位数: {actual_time}")
        try:
            actual = float(observation.get("RT_LMP"))
        except (TypeError, ValueError, OverflowError):
            actual = float("nan")
        source = observation.get("rt_lmp_source", "iso_ne_hourly")
        source = source if isinstance(source, str) else "missing"
        official = source in {"iso_ne_hourly", "iso_ne_hourly_preliminary", "iso_ne_hourly_final"}
        valid_flag = observation.get("rt_lmp_label_valid", official)
        valid = official and pd.notna(valid_flag) and bool(valid_flag) and np.isfinite(actual)
        samples = observation.get("rt_lmp_samples")
        samples = int(samples) if pd.notna(samples) and np.isfinite(float(samples)) else None
        error = None
        if valid:
            status, notice = "observed", "ISO-NE 官方小时 RT-LMP"
            error = quantiles[1] - actual
            actual_values.append(actual)
            errors.append(error)
            coverage.append(quantiles[0] <= actual <= quantiles[2])
        elif np.isfinite(actual):
            status, notice = "input_only", "补充电价仅用于模型输入，不计入真实误差"
            input_only_hours += 1
        else:
            status, notice = "missing", "缺少官方小时 RT-LMP，不计入真实误差"
            missing_hours += 1
        points.append({
            **forecast,
            "price_actual": round(actual, 2) if valid else None,
            "error_p50": round(error, 2) if error is not None else None,
            "actual_source": source,
            "actual_status": status,
            "samples_per_hour": samples,
            "label_notice": notice,
        })

    errors = np.asarray(errors)
    actuals = np.asarray(actual_values)
    valid_mape = np.abs(actuals) >= 1.0
    metrics = {
        "count": len(actual_values),
        "mae_usd": round(float(np.abs(errors).mean()), 2),
        "rmse_usd": round(float(np.sqrt(np.mean(errors ** 2))), 2),
        "mape_pct": round(float(np.mean(np.abs(errors[valid_mape] / actuals[valid_mape])) * 100), 2)
        if np.any(valid_mape) else None,
        "median_ae_usd": round(float(np.median(np.abs(errors))), 2),
        "bias_usd": round(float(errors.mean()), 2),
        "p10_p90_coverage": round(float(np.mean(coverage) * 100), 1),
    } if actual_values else None
    evaluated = len(actual_values)
    label_notice = f"24个预测小时中，{evaluated}小时有官方小时电价标签可计算误差。"
    if input_only_hours or missing_hours:
        label_notice += f"排除五分钟等补充输入{input_only_hours}小时、缺失标签{missing_hours}小时；预测曲线仍保留。"
    return {
        "available_date_range": available_range,
        "date": day.isoformat(),
        "origin": str(pd.Timestamp(day)),
        "model": prediction.get("model", "tf_split_v1"),
        "data_source": "iso_ne+open_meteo:historical_replay",
        "inference_time_ms": prediction.get("inference_time_ms"),
        "points": points,
        "metrics": metrics,
        "label_quality": {
            "evaluated_hours": evaluated, "excluded_hours": 24 - evaluated,
            "official_hourly_hours": evaluated, "input_only_hours": input_only_hours,
            "missing_hours": missing_hours, "notice": label_notice,
        },
        "metric_note": (
            "P50 与同小时 ISO-NE 真实 RT-LMP 比较；使用事后观测天气进行历史重放，"
            "不是当时在线预测的实测精度。五分钟聚合及缺失标签不计误差；"
            "MAPE 仅统计 |真实电价| ≥ $1/MWh 的小时。"
        ),
    }


async def generate_price_backtest(selected_date: date | None = None) -> dict:
    service = services.tf_load_price_service
    if service is None or not service.is_ready:
        raise RuntimeError("TensorFlow 电价预测模型未加载/未就绪")

    frozen = await asyncio.to_thread(service.price_backtest, None)
    frozen_range = frozen["available_date_range"]
    available_range = _date_range(frozen_range)
    if selected_date is None:
        return {**frozen, "available_date_range": available_range}

    requested = selected_date.isoformat()
    if not available_range["earliest"] <= requested <= available_range["latest"]:
        raise ValueError(
            f"回测日期 {requested} 不在可选范围 "
            f"{available_range['earliest']} 至 {available_range['latest']}"
        )
    from realtime_api.tf_realtime_feature_provider import TFRealtimeFeatureProvider
    TFRealtimeFeatureProvider.validate_price_backtest_window(selected_date)
    if requested <= frozen_range["latest"]:
        result = await asyncio.to_thread(service.price_backtest, requested)
        return {**result, "available_date_range": available_range}

    provider = services.tf_realtime_feature_provider
    if provider is None:
        raise RuntimeError("历史电价特征服务未就绪")
    # The frozen replay uses midnight as origin, then predicts D 01:00 .. D+1 00:00.
    # Read retrospective weather for the same interval plus warm-up history.
    from realtime_api.services.prediction_insight import _load_historical_weather

    start = datetime.combine(selected_date - timedelta(days=16), datetime.min.time())
    end = datetime.combine(selected_date + timedelta(days=1), datetime.min.time())
    weather = await _load_historical_weather(start, end)
    if weather.empty:
        raise RuntimeError(f"{requested} 的历史气象暂不可用，无法回测")
    inputs = await asyncio.to_thread(provider.build_price_day_backtest, selected_date, weather)
    prediction = await asyncio.to_thread(
        service.predict_task_features, "price", inputs["past"], inputs["future"]
    )
    return _replay_result(selected_date, available_range, inputs, prediction)
