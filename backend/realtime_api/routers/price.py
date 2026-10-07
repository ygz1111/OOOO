# -*- coding: utf-8 -*-
"""
智能电网负荷预测系统 - 电价预测路由 (TensorFlow, 2026-09)

端点:
  GET /api/price/forecast    - 未来 24h 电价预测 (p10/p50/p90, USD/MWh)
  GET /api/price/model-info  - 电价预测模型信息

说明: 电价预测由当前启用的 TensorFlow 电价模型输出,
      live 模式使用 ISO-NE 与 Open-Meteo 特征。旧模型不含电价能力, 因此该接口
      仅在 TF 引擎就绪时可用; 不可用时返回 503 并提示。

作者: 毕业设计项目
"""

import asyncio
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from realtime_api.schemas import HourlyPricePoint, PriceForecastResponse
from realtime_api.services.container import services, eastern_now, get_engine_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["电价预测"])


@router.get(
    "/api/price/forecast",
    response_model=PriceForecastResponse,
    summary="电价预测 (24h, p10/p50/p90)",
    description="""
    基于当前 TensorFlow 模型输出未来 24 小时电价分位预测:
      price_p10 / price_p50 / price_p90 (USD/MWh)
    生产模式使用 ISO-NE + Open-Meteo 在线特征；demo 模式才使用冻结验收窗口。
    """,
)
async def get_price_forecast(force_refresh: bool = Query(False)):
    """获取 24h 电价分位预测"""
    if str(get_engine_config().get("inference_mode", "live")).lower() == "live":
        from realtime_api.services.live_forecast import request_live_snapshot, trim_snapshot
        from realtime_api.services.container import eastern_now_hour
        import pandas as pd
        snapshot = trim_snapshot(await request_live_snapshot(force_refresh), pd.Timestamp(eastern_now_hour()))
        res = snapshot["components"]["price"]
        quality = snapshot["quality"]
        quality["coverage_hours"] = len(res["hourly"]) if res else 0
        return PriceForecastResponse(
            status="success" if quality["components"]["price"]["status"] == "fresh" else "degraded",
            predictions=[HourlyPricePoint(**{k: v for k, v in row.items() if k != 'price_unit'}) for row in res["hourly"]] if res else [],
            origin=res.get("origin") if res else None,
            inference_time_ms=res.get("inference_time_ms", 0) if res else 0,
            data_source=res.get("data_source", "") if res else "unavailable",
            timestamp=res["generated_at"] if res else snapshot["generated_at"], input_quality=quality,
        )
    if not (services.tf_load_price_service and services.tf_load_price_service.is_ready):
        raise HTTPException(
            status_code=503,
            detail="TensorFlow 电价预测模型未加载/未就绪，旧模型不支持电价预测",
        )

    try:
        mode = str(get_engine_config().get("inference_mode", "live")).lower()
        if mode == "live":
            weather_df, _ = await asyncio.to_thread(services.openmeteo_client.fetch_weather_data)
            bundle = await asyncio.to_thread(
                services.tf_realtime_feature_provider.build, weather_df
            )
            res = await asyncio.to_thread(
                services.tf_load_price_service.predict_features,
                bundle["load_price"]["past"], bundle["load_price"]["future"],
            )
            res["data_source"] = bundle.get("data_source", "live_features")
        else:
            res = await asyncio.to_thread(services.tf_load_price_service.predict)
        predictions = [
            HourlyPricePoint(
                hour=int(h["hour"]),
                timestamp=h["timestamp"],
                price_p10=h["price_p10"],
                price_p50=h["price_p50"],
                price_p90=h["price_p90"],
                load_forecast_mw=h.get("load_forecast_mw"),
            )
            for h in res["hourly"]
        ]
        return PriceForecastResponse(
            status="success",
            model=res.get("model", "tensorflow"),
            model_name=services.tf_load_price_service.MODEL_LABEL,
            predictions=predictions,
            origin=res.get("origin"),
            inference_time_ms=res.get("inference_time_ms", 0.0),
            data_source=res.get("data_source", ""),
            timestamp=eastern_now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"电价预测失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"电价预测失败: {e}")


@router.get(
    "/api/price/backtest",
    summary="电价历史回测与真实 RT-LMP 对比",
    description=(
        "以所选日期 00:00（ET）为锚点，使用前 168 小时特征预测后续 24 小时电价，"
        "并与真实 RT-LMP 对比。旧日期读取冻结历史特征；较新日期按需读取 ISO-NE"
        "与历史气象。缺省仅返回候选日期范围；不训练、不写入数据库。"
    ),
)
async def get_price_backtest(
    selected_date: Optional[date] = Query(
        None,
        alias="date",
        description="回测日期 YYYY-MM-DD（ET 时区）；缺省仅返回可用日期范围",
    ),
):
    """返回电价 P10/P50/P90、历史真实 RT-LMP 与逐日误差指标。"""
    service = services.tf_load_price_service
    if not (service and service.is_ready):
        raise HTTPException(status_code=503, detail="TensorFlow 电价预测模型未加载/未就绪")

    try:
        from realtime_api.services.price_backtest import generate_price_backtest
        result = await generate_price_backtest(selected_date)
        message = (
            "可用电价回测日期范围"
            if selected_date is None
            else f"成功完成 {selected_date.isoformat()} 电价历史回测"
        )
        return {"status": "success", "message": message, "data": result, "timestamp": eastern_now().isoformat()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("电价历史回测失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"电价历史回测失败: {exc}")


@router.get(
    "/api/price/model-info",
    summary="电价预测模型信息",
    description="返回当前电价预测模型的详细信息与加载状态",
)
async def get_price_model_info():
    """获取电价预测模型信息"""
    if not (services.tf_load_price_service and services.tf_load_price_service.is_ready):
        return {
            "status": "unavailable",
            "message": "TensorFlow 电价预测模型未加载",
            "timestamp": eastern_now().isoformat(),
        }

    return {
        "status": "ready",
        "model_info": services.tf_load_price_service.get_model_info(),
        "service_status": services.tf_load_price_service.get_status(),
        "training_source": "MMXX/smart-grid/runs/tf_split_v1 "
                           "(独立负荷/电价训练：load_MAE=305.4MW，price_p50_MAE=$13.27/MWh @test)",
        "timestamp": eastern_now().isoformat(),
    }
