"""TensorFlow 光伏发电预测路由。"""

import asyncio
import logging
import math

import pandas as pd

from fastapi import APIRouter, HTTPException, Query

from realtime_api.services.container import (
    eastern_now,
    eastern_now_hour,
    get_engine_config,
    services,
    tf_pv_backend_active,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["光伏"])


def _pv_backtest_metrics(pairs: list[dict]) -> dict | None:
    """计算光伏回测指标；MAPE 排除接近日出/日落的微小分母。"""
    if not pairs:
        return None
    errors = [
        float(pair["historical_forecast"]) - float(pair["historical_actual"])
        for pair in pairs
    ]
    daylight_pairs = [
        pair for pair in pairs if abs(float(pair["historical_actual"])) > 500.0
    ]
    mape = None
    if daylight_pairs:
        mape = sum(
            abs(
                (float(pair["historical_forecast"]) - float(pair["historical_actual"]))
                / float(pair["historical_actual"])
            )
            for pair in daylight_pairs
        ) / len(daylight_pairs) * 100.0
    return {
        "count": len(pairs),
        "daylight_count": len(daylight_pairs),
        "mae_mw": round(sum(abs(error) for error in errors) / len(errors), 1),
        "rmse_mw": round(math.sqrt(sum(error ** 2 for error in errors) / len(errors)), 1),
        "mape": round(mape, 2) if mape is not None else None,
    }


def _run_pv_historical_backtest(windows: list[dict]) -> dict:
    """逐小时重跑 pv_v2，并用每个 24 步输出的第 0 步做回溯验证。"""
    pairs: list[dict] = []
    for window in windows:
        result = services.tf_pv_service.predict_features(
            window["past"], window["future"]
        )
        target_time = pd.Timestamp(window["target_time"])
        prediction_time = pd.Timestamp(result["timestamps"][0])
        if prediction_time != target_time:
            raise RuntimeError(
                "TF 光伏回测时间对齐失败: "
                f"预测={prediction_time}, ISO-NE={target_time}"
            )
        actual = float(window["actual_pv_mw"])
        forecast = float(result["hourly_pv_mw"][0])
        error = forecast - actual
        pairs.append({
            "target_time": target_time.isoformat(),
            "historical_actual": round(actual, 2),
            "historical_forecast": round(forecast, 2),
            "error_mw": round(error, 2),
            "absolute_error_mw": round(abs(error), 2),
            "percentage_error": (
                round(abs(error / actual) * 100.0, 2) if abs(actual) > 500.0 else None
            ),
        })
    return {
        "pairs": pairs,
        "metrics": _pv_backtest_metrics(pairs),
        "data_source": "ISO-NE estimated BTM PV（8个负荷区汇总）",
        "note": (
            "过去24小时逐小时重跑 TensorFlow pv_v2；每次仅取第1个预测步。"
            "真实对照是 ISO-NE 官方估算 BTM PV。MAE/RMSE统计全部24小时，"
            "MAPE仅统计真实估算值大于500 MW的稳定出力时段；气象为事后观测，属于回溯验证。"
        ),
    }


@router.get(
    "/api/solar-generation",
    summary="TensorFlow 光伏发电预测",
    description=(
        "使用 TensorFlow/Keras PV v2（TCN-GRU-Attention）预测未来24小时 ISO-NE BTM 光伏出力。"
        "模型输入为过去96小时×28特征与未来24小时×27个空间气象/时间特征。"
    ),
)
async def get_solar_generation(
    force_refresh: bool = Query(False, description="强制刷新气象数据"),
):
    """获取 TensorFlow PV v2 光伏预测；不进行旧模型或物理模型回退。"""
    if str(get_engine_config().get("inference_mode", "live")).lower() == "live":
        from realtime_api.services.live_forecast import request_live_snapshot, trim_snapshot
        snapshot = trim_snapshot(await request_live_snapshot(force_refresh), pd.Timestamp(eastern_now_hour()))
        result = snapshot["components"]["pv"]
        historical = {"pairs": [], "metrics": None, "note": "没有可用的完整观测回测窗口"}
        try:
            historical = await asyncio.to_thread(_run_pv_historical_backtest, snapshot["pv_backtest"])
        except Exception:
            logger.warning("光伏回测不可用，不影响未来预测")
        # Backtesting may cross an hour boundary too.
        snapshot = trim_snapshot(snapshot, pd.Timestamp(eastern_now_hour()))
        result = snapshot["components"]["pv"]
        quality = snapshot["quality"]
        quality["coverage_hours"] = len(result["timestamps"]) if result else 0
        payload = dict(result) if result else {
            "model_type": "tf_pv_v2", "timestamps": [], "hourly_pv_mw": [], "hourly_pv_kw": [],
            "total_mwh": None, "peak_mw": None, "capacity_factor": None,
            "model_info": {}, "ensemble_weights": {}, "device": "tensorflow", "feature_count": 28,
            "inference_time_ms": 0, "data_source": "unavailable",
        }
        payload.update(status="success" if quality["components"]["pv"]["status"] == "fresh" else "degraded",
            input_quality=quality, historical=historical, lookback_hours=96, horizon_hours=quality["coverage_hours"],
            timestamp=result["generated_at"] if result else snapshot["generated_at"])
        return payload
    if not tf_pv_backend_active():
        raise HTTPException(status_code=503, detail="TensorFlow 光伏模型未就绪")

    try:
        mode = str(get_engine_config().get("inference_mode", "live")).lower()
        if mode == "live":
            weather_df, _ = await asyncio.to_thread(
                services.openmeteo_client.fetch_weather_data, None, force_refresh
            )
            if weather_df is None or weather_df.empty:
                raise RuntimeError("无法获取气象数据")
            bundle = await asyncio.to_thread(
                services.tf_realtime_feature_provider.build, weather_df, force_refresh
            )
            result = await asyncio.to_thread(
                services.tf_pv_service.predict_features,
                bundle["pv"]["past"],
                bundle["pv"]["future"],
            )
            result["data_source"] = bundle.get(
                "pv_data_source", "iso_ne+open_meteo"
            )
            try:
                historical = await asyncio.to_thread(
                    _run_pv_historical_backtest, bundle.get("pv_backtest", [])
                )
            except Exception as backtest_exc:
                logger.warning("TensorFlow 光伏历史回测失败: %s", backtest_exc, exc_info=True)
                historical = {
                    "pairs": [],
                    "metrics": None,
                    "data_source": "ISO-NE estimated BTM PV（8个负荷区汇总）",
                    "note": f"未来预测正常，但本次历史回测暂不可用: {backtest_exc}",
                }
        else:
            result = await asyncio.to_thread(services.tf_pv_service.predict)
            historical = {
                "pairs": [],
                "metrics": None,
                "data_source": "frozen_tail_demo",
                "note": "演示模式不访问 ISO-NE 官方历史实况，因此不生成在线回测。",
            }

        return {
            "status": "success",
            "model_type": result.get("model_type", "tf_pv_v2"),
            "hourly_pv_mw": result["hourly_pv_mw"],
            "hourly_pv_kw": result["hourly_pv_kw"],
            "timestamps": result["timestamps"],
            "total_mwh": result["total_mwh"],
            "peak_mw": result["peak_mw"],
            "capacity_factor": result["capacity_factor"],
            "capacity_mw": result.get("capacity_mw"),
            "hourly_capacity_mw": result.get("hourly_capacity_mw", []),
            "capacity_basis": result.get("capacity_basis"),
            "model_info": result["model_info"],
            "ensemble_weights": result["ensemble_weights"],
            "inference_time_ms": result["inference_time_ms"],
            "device": result["device"],
            "feature_count": result["feature_count"],
            "lookback_hours": result["lookback"],
            "horizon_hours": result["horizon"],
            "data_source": result.get("data_source", ""),
            "origin": result.get("origin"),
            "historical": historical,
            "timestamp": eastern_now_hour().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("TensorFlow 光伏预测失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"TensorFlow 光伏预测失败: {exc}") from exc


@router.get(
    "/api/solar-generation/model-info",
    summary="TensorFlow 光伏模型信息",
)
async def get_solar_model_info():
    """获取当前 TensorFlow 光伏模型信息。"""
    if not tf_pv_backend_active():
        return {
            "status": "unavailable",
            "message": "TensorFlow 光伏模型未加载",
            "timestamp": eastern_now().isoformat(),
        }
    return {
        "status": "ready",
        "engine": "tf_pv_v2",
        "model_info": services.tf_pv_service.get_model_info(),
        "service_status": services.tf_pv_service.get_status(),
        "training_source": (
            "MMXX/smart-grid/runs/pv_v2 "
            "(2025-02..2026-09, independent-test MAE=236.2 MW)"
        ),
        "timestamp": eastern_now().isoformat(),
    }


__all__ = ["router"]
