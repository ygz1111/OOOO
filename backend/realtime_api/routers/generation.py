"""
智能电网负荷预测系统 - 光伏/风电发电路由

端点:
  GET /api/solar-generation            - 光伏发电 ML 预测
  GET /api/solar-generation/model-info - 光伏 ML 模型信息
  GET /api/wind-generation             - 风电功率预测
  GET /api/wind-generation/power-curve - 风机功率曲线

从 app.py 中抽取。

作者: 毕业设计项目
"""

import os
import asyncio
import logging
from datetime import timedelta

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from realtime_api.services.container import services, eastern_now, eastern_now_hour

logger = logging.getLogger(__name__)

router = APIRouter(tags=["光伏", "风电"])


# ============================================================================
# GET /api/solar-generation — 光伏发电 ML 预测
# ============================================================================

@router.get(
    "/api/solar-generation",
    summary="光伏发电 ML 预测",
    description="""基于训练好的 4 模型集成 (LSTM + BiGRU + TCN + Transformer) 预测未来 24 小时光伏发电量。

模型使用 Open-Meteo 实时气象数据 (GHI/DNI/DHI/温度/湿度/风速/云量等 21 维特征) 作为输入。

如果 ML 模型未加载，自动回退到物理模型估算。""",
)
async def get_solar_generation(
    force_refresh: bool = Query(False, description="强制刷新，绕过缓存直接请求气象API"),
):
    """获取光伏发电预测 (ML 模型优先)"""
    try:
        weather_df, _ = await asyncio.to_thread(
            services.openmeteo_client.fetch_weather_data,
            None,  # locations
            force_refresh,  # force_refresh
        )

        if weather_df.empty:
            raise HTTPException(
                status_code=502,
                detail="无法获取气象数据用于光伏预测"
            )

        now = eastern_now_hour()

        # 优先使用 ML 模型
        if services.pv_inference_service and services.pv_inference_service.is_ready:
            try:
                pv_weather_rows = []
                df_for_ml = weather_df.copy()
                df_for_ml["timestamp"] = pd.to_datetime(df_for_ml["timestamp"])

                for hour in range(24):
                    pred_time = now + timedelta(hours=hour)
                    row = {"timestamp": pred_time}
                    window_start = pred_time - timedelta(minutes=30)
                    window_end = pred_time + timedelta(minutes=30)
                    mask = (df_for_ml["timestamp"] >= window_start) & (df_for_ml["timestamp"] <= window_end)
                    if mask.any():
                        for col in ["shortwave_radiation", "direct_radiation", "diffuse_radiation",
                                    "temperature_2m", "dew_point_2m", "relative_humidity_2m",
                                    "wind_speed_10m", "wind_direction_10m", "surface_pressure",
                                    "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high"]:
                            if col in df_for_ml.columns:
                                row[col] = float(df_for_ml.loc[mask, col].mean())
                    pv_weather_rows.append(row)

                pv_weather_df = pd.DataFrame(pv_weather_rows)

                result = services.pv_inference_service.predict(
                    pv_weather_df,
                    start_time=now,
                    latitude=42.36,
                    longitude=-71.06,
                )

                return {
                    "status": "success",
                    "model_type": "ml_ensemble",
                    "hourly_pv_mw": result["hourly_pv_mw"],
                    "hourly_pv_kw": result["hourly_pv_kw"],
                    "timestamps": result["timestamps"],
                    "total_mwh": result["total_mwh"],
                    "peak_mw": result["peak_mw"],
                    "capacity_factor": result["capacity_factor"],
                    "model_info": result["model_info"],
                    "ensemble_weights": result["ensemble_weights"],
                    "inference_time_ms": result["inference_time_ms"],
                    "device": result["device"],
                    "feature_count": result["feature_count"],
                    "lookback_hours": result["lookback"],
                    "horizon_hours": result["horizon"],
                    "timestamp": now.isoformat(),
                }
            except Exception as e:
                logger.error(f"光伏 ML 预测失败: {e}", exc_info=True)
                logger.warning("回退到物理模型...")

        # 物理模型回退
        from realtime_api.pv_estimator import PVGenerationEstimator
        pv_estimator = PVGenerationEstimator(
            latitude=42.36,
            longitude=-71.06,
            installed_capacity_mw=500.0,
        )
        pv_result = pv_estimator.estimate_24h(weather_df, start_time=now)

        return {
            "status": "success",
            "model_type": "physical",
            "hourly_pv_mw": [round(v, 2) for v in pv_result.hourly_generation_mw],
            "hourly_efficiency": [round(v, 4) for v in pv_result.hourly_efficiency],
            "hourly_uncertainty_mw": [round(v, 2) for v in pv_result.hourly_uncertainty],
            "timestamps": pv_result.timestamps,
            "total_mwh": round(pv_result.total_daily_mwh, 2),
            "peak_mw": round(float(pv_result.hourly_generation_mw.max()), 2),
            "capacity_factor": round(pv_result.capacity_factor, 4),
            "panel_type": pv_result.panel_type,
            "timestamp": now.isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"光伏预测失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"光伏预测失败: {str(e)}"
        )


# ============================================================================
# GET /api/solar-generation/model-info — 光伏 ML 模型信息
# ============================================================================

@router.get(
    "/api/solar-generation/model-info",
    summary="光伏 ML 模型信息",
    description="获取光伏预测模型的详细信息：模型结构、参数量、集成权重、训练指标",
)
async def get_solar_model_info():
    """获取光伏 ML 模型信息"""
    if not services.pv_inference_service or not services.pv_inference_service.is_ready:
        return {
            "status": "unavailable",
            "message": "光伏 ML 模型未加载",
            "fallback": "physical_model",
        }

    status = services.pv_inference_service.get_status()
    model_info = services.pv_inference_service.get_model_info()

    # 训练评估指标
    training_metrics = {}
    report_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "solar_data2", "pv_training", "outputs", "evaluation_report.json"
    )
    if os.path.exists(report_path):
        try:
            import json
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            training_metrics = {
                "training_date": report.get("training_date"),
                "device": report.get("device"),
                "gpu_name": report.get("gpu_name"),
                "torch_version": report.get("torch_version"),
                "data_shapes": report.get("data_shapes"),
                "results": report.get("results"),
                "city_metrics": report.get("city_metrics"),
            }
        except Exception:
            pass

    return {
        "status": "ready",
        "model_info": model_info,
        "service_status": status,
        "training_metrics": training_metrics,
        "timestamp": eastern_now().isoformat(),
    }


# ============================================================================
# GET /api/wind-generation — 风电功率预测
# ============================================================================

@router.get(
    "/api/wind-generation",
    summary="风电功率预测",
    description="基于物理模型计算未来24小时风电功率，考虑风切变高度修正、空气密度修正、功率曲线和尾流损失",
)
async def get_wind_generation():
    """获取风电功率预测"""
    try:
        weather_df, _ = await asyncio.to_thread(
            services.openmeteo_client.fetch_weather_data
        )

        if weather_df.empty:
            raise HTTPException(
                status_code=502,
                detail="无法获取气象数据用于风电估算"
            )

        # 确保必要的气象参数存在
        if "wind_speed_10m" not in weather_df.columns:
            weather_df["wind_speed_10m"] = 0.0
        if "temperature_2m" not in weather_df.columns:
            weather_df["temperature_2m"] = 15.0
        if "surface_pressure" not in weather_df.columns:
            weather_df["surface_pressure"] = 1013.25
        if "wind_direction_10m" not in weather_df.columns:
            weather_df["wind_direction_10m"] = 270.0

        now = eastern_now_hour()
        result = services.wind_estimator.estimate_24h(weather_df, start_time=now)

        return {
            "status": "success",
            "hourly_generation_mw": [round(v, 2) for v in result.hourly_generation_mw],
            "hourly_wind_speed_hub": [round(v, 2) for v in result.hourly_wind_speed_hub],
            "hourly_efficiency": [round(v, 4) for v in result.hourly_efficiency],
            "hourly_uncertainty_mw": [round(v, 2) for v in result.hourly_uncertainty],
            "hourly_air_density": [round(v, 4) for v in result.hourly_air_density],
            "timestamps": result.timestamps,
            "total_daily_mwh": round(result.total_daily_mwh, 2),
            "capacity_factor": round(result.capacity_factor, 4),
            "turbine_type": result.turbine_type,
            "installed_capacity_mw": result.installed_capacity_mw,
            "timestamp": now.isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"风电预测失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"风电预测失败: {str(e)}"
        )


# ============================================================================
# GET /api/wind-generation/power-curve — 风机功率曲线
# ============================================================================

@router.get(
    "/api/wind-generation/power-curve",
    summary="风机功率曲线",
    description="获取风机功率特性曲线数据，包括功率曲线模型和理论功率",
)
async def get_wind_power_curve():
    """获取风机功率曲线"""
    try:
        curve_df = services.wind_estimator.power_curve(speed_range=(0, 30), steps=60)

        return {
            "status": "success",
            "turbine_type": services.wind_estimator.turbine.name,
            "rated_power_kw": services.wind_estimator.turbine.rated_power_kw,
            "rotor_diameter_m": services.wind_estimator.turbine.rotor_diameter_m,
            "hub_height_m": services.wind_estimator.turbine.hub_height_m,
            "cut_in_speed": services.wind_estimator.turbine.cut_in_speed,
            "rated_speed": services.wind_estimator.turbine.rated_speed,
            "cut_out_speed": services.wind_estimator.turbine.cut_out_speed,
            "power_coefficient": services.wind_estimator.turbine.power_coefficient,
            "mechanical_efficiency": services.wind_estimator.turbine.mechanical_efficiency,
            "n_turbines": services.wind_estimator.n_turbines,
            "installed_capacity_mw": services.wind_estimator.installed_capacity,
            "wind_shear_alpha": services.wind_estimator.alpha,
            "wake_loss": services.wind_estimator.wake_loss,
            "availability": services.wind_estimator.availability,
            "curve": curve_df.to_dict(orient="records"),
            "timestamp": eastern_now().isoformat(),
        }

    except Exception as e:
        logger.error(f"获取功率曲线失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取功率曲线失败: {str(e)}"
        )
