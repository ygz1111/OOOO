"""
智能电网负荷预测系统 - 预测路由

端点:
  POST /api/prediction/load    - 负荷预测 (24小时)
  POST /api/prediction/batch   - 批量预测
  GET  /api/prediction/history - 历史预测查询

从 app.py 中抽取。

作者: 毕业设计项目
"""

import uuid
import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from realtime_api.schemas import (
    LoadPredictionRequest,
    LoadPredictionResponse,
    BatchPredictionRequest,
    BatchPredictionResponse,
    SuccessResponse,
)
from realtime_api.crud import (
    LoadPredictionsCRUD,
    ModelPerformanceCRUD,
)
from realtime_api.historical_load_provider import HistoricalLoadProvider
from realtime_api.services.container import services, eastern_now, eastern_now_hour
from realtime_api.services.prediction_pipeline import (
    run_prediction_pipeline,
    weather_points_to_df,
    load_points_to_df,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["预测"])


# ============================================================================
# POST /api/prediction/load — 负荷预测
# ============================================================================

@router.post(
    "/api/prediction/load",
    response_model=LoadPredictionResponse,
    summary="负荷预测",
    description="""
    执行24小时负荷预测。

    可以在请求体中提供气象数据，也可以不提供（系统自动从 Open-Meteo 获取）。
    返回每小时负荷预测、光伏估算和净负荷。
    """,
)
async def predict_load(
    request: LoadPredictionRequest,
    force_refresh: bool = Query(False, description="强制刷新，绕过缓存直接请求气象API"),
):
    """
    负荷预测端点

    流程:
    1. 获取气象数据（用户提供 或 Open-Meteo API）
    2. 数据验证和清洗
    3. 38维特征生成
    4. MinMaxScaler 归一化
    5. 4模型集成推理
    6. 逆归一化 + 光伏估算
    """
    if not services.inference_service or not services.inference_service.is_ready():
        raise HTTPException(
            status_code=503,
            detail="模型服务未就绪，请稍后重试",
        )

    # 获取气象数据
    if request.weather_data and len(request.weather_data) > 0:
        weather_df = weather_points_to_df(request.weather_data)
        data_source = "provided"
    else:
        try:
            weather_df, _ = await asyncio.to_thread(
                services.openmeteo_client.fetch_weather_data
            )
            data_source = "api"
            if weather_df is None or weather_df.empty:
                logger.warning("气象数据为空，预测将使用默认特征值")
        except Exception as e:
            logger.error(f"获取气象数据失败: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"获取气象数据失败: {e}",
            )

    # 获取历史负荷数据
    historical_load_df = None
    if request.historical_load and len(request.historical_load) > 0:
        historical_load_df = load_points_to_df(request.historical_load)
    else:
        try:
            historical_load_df = await HistoricalLoadProvider.get_historical_load()
            if historical_load_df is not None:
                logger.info(f"已从数据库获取历史负荷数据: {len(historical_load_df)} 条")
        except Exception as e:
            logger.warning(f"获取历史负荷数据失败: {e}，将使用默认值")

    # 执行预测管线（CPU密集型，放线程池）
    try:
        response = await asyncio.to_thread(
            run_prediction_pipeline,
            weather_df,
            historical_load_df,
        )
        response.data_source = data_source

        # 将预测结果保存到MySQL数据库
        try:
            now = eastern_now_hour()
            prediction_id = str(uuid.uuid4())

            for hour_pred in response.predictions:
                pred_timestamp = datetime.fromisoformat(hour_pred.timestamp.replace('Z', '+00:00'))

                await LoadPredictionsCRUD.insert_prediction(
                    prediction_timestamp=now,
                    target_timestamp=pred_timestamp,
                    load_forecast_mw=hour_pred.load_forecast_mw,
                    pv_estimation_mw=hour_pred.pv_estimation_mw,
                    wind_estimation_mw=hour_pred.wind_estimation_mw,
                    net_load_mw=hour_pred.net_load_mw,
                    model_type='ensemble',
                    inference_time_ms=response.inference_time_ms,
                    data_source=data_source,
                    prediction_id=prediction_id
                )

            logger.info(f"预测结果已保存到MySQL - 预测ID: {prediction_id}, 共{len(response.predictions)}条记录")

            # 异步写入模型性能记录
            async def _persist_model_performance():
                try:
                    stats = services.inference_service.get_performance_stats()
                    await ModelPerformanceCRUD.insert_performance(
                        model_name='ensemble',
                        model_version='1.0',
                        total_inferences=stats.get('total_inferences', 0),
                        successful_inferences=stats.get('total_inferences', 0),
                        failed_inferences=0,
                        average_inference_time_ms=response.inference_time_ms,
                        batch_size=len(response.predictions),
                        device=stats.get('device', 'cpu'),
                    )
                    for model_name in response.ensemble_weights:
                        await ModelPerformanceCRUD.insert_performance(
                            model_name=model_name,
                            model_version='1.0',
                            total_inferences=1,
                            successful_inferences=1,
                            failed_inferences=0,
                            average_inference_time_ms=response.inference_time_ms / max(len(response.ensemble_weights), 1),
                            batch_size=1,
                            device=stats.get('device', 'cpu'),
                        )
                except Exception as e:
                    logger.warning(f"模型性能入库失败（非阻塞）: {e}")

            asyncio.create_task(_persist_model_performance())
        except Exception as db_error:
            logger.warning(f"保存预测结果到数据库失败（非阻塞）: {db_error}")

        return response

    except Exception as e:
        logger.error(f"预测管线失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"预测失败: {e}",
        )


# ============================================================================
# POST /api/prediction/batch — 批量预测
# ============================================================================

@router.post(
    "/api/prediction/batch",
    response_model=BatchPredictionResponse,
    summary="批量预测",
    description="批量执行负荷预测（最多10个请求）",
)
async def batch_predict(request: BatchPredictionRequest):
    """批量预测"""
    if not services.inference_service or not services.inference_service.is_ready():
        raise HTTPException(
            status_code=503,
            detail="模型服务未就绪",
        )

    batch_start = time.perf_counter()
    results = []

    for i, item in enumerate(request.requests):
        try:
            weather_df = weather_points_to_df(item.weather_data)
            historical_load_df = None
            if item.historical_load:
                historical_load_df = load_points_to_df(item.historical_load)

            response = await asyncio.to_thread(
                run_prediction_pipeline,
                weather_df,
                historical_load_df,
            )
            results.append(response)

        except Exception as e:
            logger.error(f"批量预测第{i}个请求失败: {e}")
            results.append(LoadPredictionResponse(
                status="error",
                predictions=[],
                model_info=[],
                ensemble_weights={},
                inference_time_ms=0,
                data_source="error",
                timestamp=eastern_now().isoformat(),
            ))

    total_time = (time.perf_counter() - batch_start) * 1000

    return BatchPredictionResponse(
        status="success" if all(r.status == "success" for r in results) else "partial",
        results=results,
        total_time_ms=round(total_time, 1),
        timestamp=eastern_now().isoformat(),
    )


# ============================================================================
# GET /api/prediction/history — 历史预测查询
# ============================================================================

@router.get(
    "/api/prediction/history",
    response_model=SuccessResponse,
    summary="历史预测查询",
    description="查询历史负荷预测结果（分页显示）",
)
async def get_prediction_history(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    model_type: Optional[str] = None,
    limit: int = 100,
):
    """历史预测查询API"""
    try:
        start_dt = None
        end_dt = None

        if start_time:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        if end_time:
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))

        # 默认查询最近24小时
        if not start_dt:
            start_dt = eastern_now_hour() - timedelta(hours=24)
        if not end_dt:
            end_dt = eastern_now_hour()

        limit = max(1, min(limit, 1000))

        predictions = await LoadPredictionsCRUD.get_predictions_by_time_range(
            start_time=start_dt,
            end_time=end_dt,
            model_type=model_type,
            limit=limit,
            order_desc=True
        )

        logger.info(f"查询到 {len(predictions)} 条历史预测记录")

        return SuccessResponse(
            message=f"成功获取历史预测数据，共{len(predictions)}条记录",
            data=predictions
        )

    except ValueError as ve:
        raise HTTPException(
            status_code=400,
            detail=f"时间格式错误: {str(ve)}"
        )
    except Exception as e:
        logger.error(f"历史预测查询失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"查询历史预测数据失败: {str(e)}"
        )
