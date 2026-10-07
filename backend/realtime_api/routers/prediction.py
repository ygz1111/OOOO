"""
智能电网负荷预测系统 - 预测路由

端点:
  POST /api/prediction/load    - 负荷预测 (24小时)
  POST /api/prediction/batch   - 批量预测
  GET  /api/prediction/history - 历史预测查询

从 app.py 中抽取。

作者: 毕业设计项目
"""

from realtime_api.utils.background import fire_and_forget
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
from realtime_api.services.container import (
    active_model_runtime_stats,
    get_engine_config,
    prediction_backend_ready,
    services,
    eastern_now,
    eastern_now_hour,
    tf_load_backend_active,
)
from realtime_api.services.prediction_pipeline import (
    dispatch_prediction as run_prediction_pipeline,
    weather_points_to_df,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["预测"])


async def _persist_live_response(response):
    """Persistence is best-effort and must not stall the online forecast response."""
    if not response.predictions or (response.input_quality or {}).get('components', {}).get('load', {}).get('status') == 'cached':
        return
    prediction_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{response.engine}:{response.timestamp}:{response.origin}"))
    try:
        for row in response.predictions:
            await LoadPredictionsCRUD.insert_prediction(
                prediction_timestamp=datetime.fromisoformat(response.timestamp),
                target_timestamp=datetime.fromisoformat(row.timestamp),
                load_forecast_mw=row.load_forecast_mw, pv_estimation_mw=row.pv_estimation_mw,
                net_load_mw=row.net_load_mw, model_type=response.engine,
                inference_time_ms=response.inference_time_ms, data_source=response.data_source,
                prediction_id=prediction_id,
            )
    except Exception:
        logger.warning("预测已返回，但本次后台入库失败；不影响曲线展示", exc_info=True)


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
    2. 构建 TensorFlow 在线特征窗口
    3. 独立负荷模型推理
    4. 独立电价模型推理
    5. TensorFlow 光伏模型推理
    6. 反归一化并计算净负荷
    """
    inference_mode = str(get_engine_config().get('inference_mode', 'live')).strip().lower()
    automatic_live = inference_mode == 'live' and not any((request.weather_data, request.tf_load_price_features, request.tf_pv_features))
    if not automatic_live and not prediction_backend_ready():
        raise HTTPException(
            status_code=503,
            detail="模型服务未就绪，请稍后重试",
        )

    inference_mode = str(get_engine_config().get('inference_mode', 'live')).strip().lower()
    frozen_demo = inference_mode == 'demo' and tf_load_backend_active()

    # 冻结验收模式不请求实时天气，避免给离线输出贴上实时数据标签。
    if automatic_live:
        weather_df = None
        data_source = "iso_ne+open_meteo"
    elif frozen_demo:
        weather_df = pd.DataFrame()
        data_source = "frozen_tail_demo"
    elif request.weather_data and len(request.weather_data) > 0:
        weather_df = weather_points_to_df(request.weather_data)
        data_source = "provided"
    else:
        try:
            weather_df, _ = await asyncio.to_thread(
                services.openmeteo_client.fetch_weather_data, None, force_refresh
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

    # 当前 TensorFlow 在线特征服务会直接读取 ISO-NE 权威历史序列，并在
    # provider 内完成滞后/滚动特征构造。旧管线在这里额外查询一次 MySQL，
    # 但下游从未使用该结果；这不仅增加冷启动延迟，还可能触发无意义的
    # 数据库失败/冻结 Tail 回退。保留函数参数仅用于 API 向后兼容。
    historical_load_df = None

    # 执行预测管线（CPU密集型，放线程池）
    try:
        if automatic_live:
            from realtime_api.services.live_forecast import request_live_snapshot, snapshot_response
            snapshot = await request_live_snapshot(force_refresh)
            response = snapshot_response(snapshot)
        else:
            response = await asyncio.to_thread(
                run_prediction_pipeline, weather_df, historical_load_df,
                request.tf_load_price_features.model_dump() if request.tf_load_price_features else None,
                request.tf_pv_features.model_dump() if request.tf_pv_features else None,
            )
        if inference_mode == 'live':
            now = eastern_now_hour()
            stale_targets = [
                datetime.fromisoformat(item.timestamp)
                for item in response.predictions
                if datetime.fromisoformat(item.timestamp) <= now
            ]
            if stale_targets:
                raise RuntimeError(
                    "在线预测目标时间未晚于当前小时，已拒绝返回和入库: "
                    f"当前={now.isoformat()}, 最早异常={min(stale_targets).isoformat()}"
                )
        # TF 引擎有自己的 data_source 标注, 不覆盖
        if not str(getattr(response, 'engine', '')).startswith('tf_'):
            response.data_source = data_source

        if automatic_live:
            fire_and_forget(lambda: _persist_live_response(response), "live_prediction_persistence")
            return response

        # 将预测结果保存到MySQL数据库
        try:
            # Cached results must not masquerade as a newly generated forecast.
            now = datetime.fromisoformat(response.timestamp)
            prediction_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{response.engine}:{response.timestamp}:{response.origin}")) if automatic_live else str(uuid.uuid4())
            model_type = getattr(response, 'engine', None) or 'ensemble'

            cached_load = (response.input_quality or {}).get('components', {}).get('load', {}).get('status') == 'cached'
            for hour_pred in ([] if cached_load else response.predictions):
                # timestamp 由 pipeline 生成: eastern naive 墙钟时间 isoformat()
                # 直接按 naive 解析入库, 与查询端 (eastern_now_hour) 口径一致;
                # 此前 replace('Z','+00:00') 会构造 UTC aware 时间,
                # 在 MySQL 会话时区非 Eastern 时产生 4h 偏移隐患
                pred_timestamp = datetime.fromisoformat(hour_pred.timestamp)

                await LoadPredictionsCRUD.insert_prediction(
                    prediction_timestamp=now,
                    target_timestamp=pred_timestamp,
                    load_forecast_mw=hour_pred.load_forecast_mw,
                    pv_estimation_mw=hour_pred.pv_estimation_mw,
                    net_load_mw=hour_pred.net_load_mw,
                    model_type=model_type,
                    inference_time_ms=response.inference_time_ms,
                    data_source=response.data_source,
                    prediction_id=prediction_id
                )

            logger.info(f"预测结果已保存到MySQL - 预测ID: {prediction_id}, 共{len(response.predictions)}条记录")

            # 异步写入模型性能记录
            async def _persist_model_performance():
                try:
                    stats = active_model_runtime_stats()
                    primary_model = getattr(response, 'engine', None) or 'ensemble'
                    primary_version = (
                        'split_v1' if primary_model == 'tf_split_v1'
                        else 'v2' if primary_model == 'tf_v2'
                        else '1.0'
                    )
                    await ModelPerformanceCRUD.insert_performance(
                        model_name=primary_model,
                        model_version=primary_version,
                        total_inferences=stats.get('total_inferences', 0),
                        successful_inferences=stats.get('total_inferences', 0),
                        failed_inferences=0,
                        average_inference_time_ms=response.inference_time_ms,
                        batch_size=len(response.predictions),
                        device=stats.get('device', 'tensorflow'),
                    )
                    for model_name in response.ensemble_weights:
                        if model_name == primary_model:
                            continue
                        await ModelPerformanceCRUD.insert_performance(
                            model_name=model_name,
                            model_version='v2' if model_name == 'pv_v2' else '1.0',
                            total_inferences=1,
                            successful_inferences=1,
                            failed_inferences=0,
                            average_inference_time_ms=response.inference_time_ms / max(len(response.ensemble_weights), 1),
                            batch_size=1,
                            device=stats.get('device', 'tensorflow'),
                        )
                except Exception as e:
                    logger.warning(f"模型性能入库失败（非阻塞）: {e}")

            fire_and_forget(_persist_model_performance, "model_performance")
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
    if not prediction_backend_ready():
        raise HTTPException(
            status_code=503,
            detail="模型服务未就绪",
        )

    batch_start = time.perf_counter()
    results = []

    for i, item in enumerate(request.requests):
        try:
            if str(get_engine_config().get('inference_mode', 'live')).lower() == 'live' and not any((item.weather_data, item.tf_load_price_features, item.tf_pv_features)):
                from realtime_api.services.live_forecast import request_live_snapshot, snapshot_response
                results.append(snapshot_response(await request_live_snapshot()))
                continue
            if item.weather_data:
                weather_df = weather_points_to_df(item.weather_data)
            elif tf_load_backend_active():
                weather_df, _ = await asyncio.to_thread(
                    services.openmeteo_client.fetch_weather_data
                )
            else:
                weather_df = pd.DataFrame()
            response = await asyncio.to_thread(
                run_prediction_pipeline,
                weather_df,
                None,
                item.tf_load_price_features.model_dump() if item.tf_load_price_features else None,
                item.tf_pv_features.model_dump() if item.tf_pv_features else None,
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
    """历史预测查询API

    2026-08 修复：默认按"预测生成时间"取最近 limit 条记录。
    旧实现按"目标时间在过去 24h"过滤，而预测的目标时间总是未来
    （now+1 ~ now+24），导致刚做过的预测永远不在窗口内，页面显示
    "暂无历史预测数据"。显式传入 start_time/end_time 时仍按目标时间过滤。
    """
    try:
        start_dt = None
        end_dt = None

        if start_time:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        if end_time:
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))

        limit = max(1, min(limit, 1000))

        if start_time or end_time:
            # 显式指定时间范围：按目标时间过滤
            if not start_dt:
                start_dt = eastern_now_hour() - timedelta(hours=24)
            if not end_dt:
                end_dt = eastern_now_hour()
            predictions = await LoadPredictionsCRUD.get_predictions_by_time_range(
                start_time=start_dt,
                end_time=end_dt,
                model_type=model_type,
                limit=limit,
                order_desc=True
            )
        else:
            # 默认：最近 limit 条预测记录（按预测生成时间倒序）
            predictions = await LoadPredictionsCRUD.get_latest_predictions(limit=limit)
            if model_type:
                predictions = [p for p in predictions if p.get('model_type') == model_type]

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


# ============================================================================
# 24h 负荷预测总览（历史回测验证 + 未来预测 + 当前实际）
# ============================================================================

@router.get(
    "/api/prediction/overview",
    summary="24h 负荷预测总览",
    description=(
        "历史 24h：用过去气象重新调用模型回测（historical_forecast），"
        "与真实负荷（historical_actual）按 target_time 对齐对比，计算 MAE/RMSE/MAPE；"
        "未来 24h：未来气象 → 模型推理（future_forecast，不含未来实际）；"
        "当前实际负荷（ISO-NE 真实数据）。"
    )
)
async def get_load_overview(force_refresh: bool = Query(False, description="重新读取共享预测结果")):
    """返回历史回测 + 未来预测 + 当前实际负荷"""
    from realtime_api.services.prediction_insight import generate_load_overview
    try:
        return await generate_load_overview(force_refresh=force_refresh is True)
    except ValueError as exc:
        message = str(exc)
        if "ISO-NE" in message or "不完整" in message or "共同窗口" in message:
            logger.warning("预测总览暂不可用，实时特征不完整: %s", message)
            raise HTTPException(
                status_code=503,
                detail=f"ISO-NE 实时特征数据暂不完整: {message}",
            ) from exc
        raise
