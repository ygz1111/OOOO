#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能电网负荷预测系统 - 预测结果分析API

提供预测准确性追踪、对比分析和综合报告的API接口

作者: 毕业设计项目
"""

import os
import re
import sys
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict
from zoneinfo import ZoneInfo

# 新英格兰地区（美国东部）时区
_EST = ZoneInfo("America/New_York")

def eastern_now() -> datetime:
    """返回当前新英格兰地区时间（naive datetime）"""
    return datetime.now(_EST).replace(tzinfo=None)

def eastern_now_hour() -> datetime:
    """返回当前新英格兰地区时间，截断到整点（用于数据库查询时间窗口对齐）"""
    return eastern_now().replace(minute=0, second=0, microsecond=0)

# 项目路径
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND_DIR)

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
import logging

from realtime_api.database import db_manager, get_db_manager
from realtime_api.crud import LoadPredictionsCRUD
from realtime_api.monitoring_service import get_monitoring_service
from realtime_api.prediction_analytics import get_prediction_analytics

# 日志配置
logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(
    prefix="/api/analytics",
    tags=["预测分析"]
)


async def _compute_accuracy_from_db(hours: int = 168) -> Dict[str, Any]:
    """从数据库计算预测准确性统计"""
    now = eastern_now_hour()
    start_time = now - timedelta(hours=hours)
    predictions = await LoadPredictionsCRUD.get_predictions_by_time_range(
        start_time=start_time,
        end_time=now
    )

    # 只取 ensemble 模型且含 actual_load_mw 的记录
    ens_with_actual = [
        p for p in predictions
        if p.get('model_type') == 'ensemble' and p.get('actual_load_mw') is not None
    ]

    if not ens_with_actual:
        return {"count": 0, "mape": None, "rmse": None, "mae": None, "r2": None,
                "best_model": None, "worst_model": None}

    preds = np.array([float(p['load_forecast_mw']) for p in ens_with_actual])
    actuals = np.array([float(p['actual_load_mw']) for p in ens_with_actual])
    errors = actuals - preds

    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    mask = np.abs(actuals) > 1e-6
    mape = float(np.mean(np.abs(errors[mask] / actuals[mask])) * 100) if np.any(mask) else 0.0
    ss_res = np.sum(errors ** 2)
    ss_tot = np.sum((actuals - np.mean(actuals)) ** 2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot != 0 else 0.0

    # 按模型统计最佳/最差
    model_mapes = {}
    for mt in set(p.get('model_type', 'ensemble') for p in predictions):
        mt_records = [p for p in predictions if p.get('model_type') == mt and p.get('actual_load_mw') is not None]
        if mt_records:
            mt_preds = np.array([float(p['load_forecast_mw']) for p in mt_records])
            mt_actuals = np.array([float(p['actual_load_mw']) for p in mt_records])
            mt_errors = mt_actuals - mt_preds
            mt_mask = np.abs(mt_actuals) > 1e-6
            if np.any(mt_mask):
                model_mapes[mt] = float(np.mean(np.abs(mt_errors[mt_mask] / mt_actuals[mt_mask])) * 100)

    best_model = min(model_mapes, key=model_mapes.get) if model_mapes else None
    worst_model = max(model_mapes, key=model_mapes.get) if model_mapes else None

    return {
        "count": len(ens_with_actual),
        "mape": mape,
        "rmse": rmse,
        "mae": mae,
        "r2": r2,
        "best_model": best_model,
        "worst_model": worst_model
    }


@router.get(
    "/accuracy/stats",
    response_model=Dict[str, Any],
    summary="获取预测准确性统计",
    description="获取当前预测准确性指标（MAPE、RMSE、MAE、R²）"
)
async def get_accuracy_stats(
    monitoring_service=Depends(get_monitoring_service)
):
    """获取预测准确性统计 - 直接从数据库计算"""
    try:
        stats = await _compute_accuracy_from_db()
        
        return {
            "status": "success",
            "message": "成功获取预测准确性统计",
            "data": stats,
            "timestamp": eastern_now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"获取准确性统计失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取预测准确性统计失败: {str(e)}"
        )


@router.get(
    "/accuracy/recent",
    response_model=Dict[str, Any],
    summary="获取最近预测记录",
    description="获取最近的预测和实际值对比记录"
)
async def get_recent_predictions(
    limit: int = Query(50, ge=1, le=200, description="返回记录数量限制"),
    monitoring_service=Depends(get_monitoring_service)
):
    """获取最近的预测记录"""
    try:
        records = monitoring_service.accuracy_tracker.get_recent_predictions(limit)
        
        return {
            "status": "success",
            "message": f"成功获取最近预测记录，共{len(records)}条",
            "data": records,
            "timestamp": eastern_now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"获取最近预测记录失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取最近预测记录失败: {str(e)}"
        )


@router.get(
    "/drift/check",
    response_model=Dict[str, Any],
    summary="检查模型漂移",
    description="检测模型预测是否存在漂移现象"
)
async def check_model_drift(
    monitoring_service=Depends(get_monitoring_service)
):
    """检查模型漂移 - 从数据库计算，返回前端期望的 DriftDetection 格式"""
    try:
        # 从数据库获取最近7天 ensemble 预测
        start_time = eastern_now_hour() - timedelta(days=7)
        predictions = await LoadPredictionsCRUD.get_predictions_by_time_range(
            start_time=start_time,
            end_time=eastern_now_hour()
        )

        ens_with_actual = [
            p for p in predictions
            if p.get('model_type', 'ensemble') == 'ensemble'
            and p.get('actual_load_mw') is not None
        ]

        if len(ens_with_actual) < 10:
            # 数据不足，返回默认值
            result = {
                "drift_detected": False,
                "drift_score": 0.0,
                "threshold": 0.25,
                "recent_mape": None,
                "baseline_mape": None,
                "recommendation": "数据量不足，需至少10条含实际值的预测记录才能进行漂移检测"
            }
        else:
            # 解析时间戳并排序
            parsed = []
            for p in ens_with_actual:
                ts_str = p.get('target_timestamp')
                if not ts_str:
                    continue
                try:
                    if isinstance(ts_str, str):
                        # 移除可能的时区后缀（Z 或 +HH:MM），得到 naive datetime
                        # 与 eastern_now() 保持一致
                        cleaned = ts_str.strip()
                        if cleaned.endswith('Z'):
                            cleaned = cleaned[:-1]
                        # 截断可能的时区偏移 (+HH:MM 或 -HH:MM)
                        cleaned = re.sub(r'[+-]\d{2}:\d{2}$', '', cleaned)
                        ts = datetime.fromisoformat(cleaned)
                    else:
                        ts = ts_str
                    parsed.append((ts, float(p['load_forecast_mw']), float(p['actual_load_mw'])))
                except Exception:
                    continue

            parsed.sort(key=lambda x: x[0])

            if len(parsed) < 10:
                result = {
                    "drift_detected": False,
                    "drift_score": 0.0,
                    "threshold": 0.25,
                    "recent_mape": None,
                    "baseline_mape": None,
                    "recommendation": "有效数据不足，无法进行漂移检测"
                }
            else:
                # 分为基准集(前70%)和近期集(后30%)
                split_idx = int(len(parsed) * 0.7)
                baseline = parsed[:split_idx]
                recent = parsed[split_idx:]

                def compute_mape(data_list):
                    errors = []
                    for _, pred, actual in data_list:
                        if abs(actual) > 1e-6:
                            errors.append(abs((actual - pred) / actual) * 100)
                    return float(np.mean(errors)) if errors else 0.0

                baseline_mape = compute_mape(baseline)
                recent_mape = compute_mape(recent)

                # 漂移分数 = MAPE 变化率
                if baseline_mape > 1e-6:
                    drift_score = abs(recent_mape - baseline_mape) / baseline_mape
                else:
                    drift_score = 0.0

                threshold = 0.25  # 25%变化率作为漂移阈值
                drift_detected = drift_score > threshold

                if drift_detected:
                    if recent_mape > baseline_mape:
                        recommendation = f"检测到模型性能下降：MAPE从{baseline_mape:.2f}%升至{recent_mape:.2f}%，建议重新训练模型"
                    else:
                        recommendation = f"模型性能有变化：MAPE从{baseline_mape:.2f}%降至{recent_mape:.2f}%，请关注数据分布变化"
                else:
                    recommendation = "模型预测准确性保持稳定，无需干预"

                result = {
                    "drift_detected": drift_detected,
                    "drift_score": float(drift_score),
                    "threshold": threshold,
                    "recent_mape": recent_mape,
                    "baseline_mape": baseline_mape,
                    "recommendation": recommendation
                }

        message = "模型漂移检测完成"
        if result.get('drift_detected', False):
            message += " - 检测到模型漂移"
        else:
            message += " - 未检测到明显漂移"

        return {
            "status": "success",
            "message": message,
            "data": result,
            "timestamp": eastern_now().isoformat()
        }

    except Exception as e:
        logger.error(f"模型漂移检测失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"模型漂移检测失败: {str(e)}"
        )


@router.get(
    "/quality/stats",
    response_model=Dict[str, Any],
    summary="获取数据质量统计",
    description="获取气象数据质量验证统计信息"
)
async def get_data_quality_stats(
    monitoring_service=Depends(get_monitoring_service)
):
    """获取数据质量统计"""
    try:
        quality_stats = monitoring_service.data_quality_monitor.get_quality_stats()
        
        return {
            "status": "success",
            "message": "成功获取数据质量统计",
            "data": quality_stats,
            "timestamp": eastern_now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"获取数据质量统计失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取数据质量统计失败: {str(e)}"
        )


@router.post(
    "/quality/validate",
    response_model=Dict[str, Any],
    summary="验证气象数据质量",
    description="验证单条气象数据的质量"
)
async def validate_weather_data(
    weather_data: Dict[str, float],
    monitoring_service=Depends(get_monitoring_service)
):
    """验证气象数据质量"""
    try:
        validation_result = monitoring_service.validate_data_quality(weather_data)
        
        message = "数据质量验证完成"
        if validation_result.get('is_valid', False):
            message += " - ✅ 数据质量良好"
        else:
            message += f" - ⚠️ 发现 {len(validation_result.get('issues', []))} 个质量问题"
        
        return {
            "status": "success",
            "message": message,
            "data": validation_result,
            "timestamp": eastern_now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"数据质量验证失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"数据质量验证失败: {str(e)}"
        )


@router.get(
    "/comparison/models",
    response_model=Dict[str, Any],
    summary="多模型预测对比",
    description="对比不同模型的预测准确性"
)
async def compare_models(
    hours: int = Query(24, ge=1, le=168, description="查询时间范围（小时）"),
    db_manager=Depends(get_db_manager),
    analytics=Depends(get_prediction_analytics)
):
    """多模型预测对比分析 - 返回 Record<string, ModelComparisonItem>"""
    try:
        start_time = eastern_now_hour() - timedelta(hours=hours)
        predictions = await LoadPredictionsCRUD.get_predictions_by_time_range(
            start_time=start_time,
            end_time=eastern_now_hour()
        )

        if not predictions:
            return {
                "status": "success",
                "message": "指定时间范围内无预测数据",
                "data": {},
                "timestamp": eastern_now().isoformat()
            }

        # 按模型类型分组
        model_groups: Dict[str, List[Dict]] = defaultdict(list)
        for pred in predictions:
            mt = pred.get('model_type', 'unknown')
            model_groups[mt].append(pred)

        # 构建前端期望的格式: { model_name: { model_name, count, mape, rmse, mae, avg_inference_time_ms } }
        result: Dict[str, Any] = {}

        for model_name, preds in model_groups.items():
            if not preds:
                continue

            # 取含 actual_load_mw 的记录用于计算误差指标
            preds_with_actual = [p for p in preds if p.get('actual_load_mw') is not None]

            item: Dict[str, Any] = {
                "model_name": model_name,
                "count": len(preds),
                "mape": None,
                "rmse": None,
                "mae": None,
                "avg_inference_time_ms": None,
            }

            # 平均推理时间
            inf_times = [float(p['inference_time_ms']) for p in preds if p.get('inference_time_ms') is not None]
            if inf_times:
                item["avg_inference_time_ms"] = float(np.mean(inf_times))

            if preds_with_actual:
                p_arr = np.array([float(p['load_forecast_mw']) for p in preds_with_actual])
                a_arr = np.array([float(p['actual_load_mw']) for p in preds_with_actual])
                errors = a_arr - p_arr

                item["mae"] = float(np.mean(np.abs(errors)))
                item["rmse"] = float(np.sqrt(np.mean(errors ** 2)))

                mask = np.abs(a_arr) > 1e-6
                if np.any(mask):
                    item["mape"] = float(np.mean(np.abs(errors[mask] / a_arr[mask])) * 100)

            result[model_name] = item

        return {
            "status": "success",
            "message": f"成功完成多模型对比分析，共分析{len(predictions)}条记录",
            "data": result,
            "timestamp": eastern_now().isoformat()
        }

    except Exception as e:
        logger.error(f"多模型对比分析失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"多模型对比分析失败: {str(e)}"
        )


@router.get(
    "/temporal/trends",
    response_model=Dict[str, Any],
    summary="时间维度趋势分析",
    description="分析预测结果的时间维度趋势（小时/日/周）"
)
async def analyze_temporal_trends(
    time_window: str = Query("daily", description="时间窗口类型: hourly, daily, weekly"),
    days: int = Query(7, ge=1, le=30, description="分析天数"),
    db_manager=Depends(get_db_manager),
    analytics=Depends(get_prediction_analytics)
):
    """时间维度趋势分析 - 返回 {trends: TrendDataPoint[], summary: any}"""
    try:
        if time_window not in ["hourly", "daily", "weekly"]:
            raise HTTPException(
                status_code=400,
                detail="time_window参数必须是 hourly, daily 或 weekly"
            )

        start_time = eastern_now_hour() - timedelta(days=days)
        predictions = await LoadPredictionsCRUD.get_predictions_by_time_range(
            start_time=start_time,
            end_time=eastern_now_hour()
        )

        # 只取 ensemble 模型，避免单模型干扰趋势
        ens_preds = [p for p in predictions if p.get('model_type', 'ensemble') == 'ensemble']

        if not ens_preds:
            return {
                "status": "success",
                "message": "指定时间范围内无预测数据",
                "data": {"trends": [], "summary": {}},
                "timestamp": eastern_now().isoformat()
            }

        # 按时间窗口分组
        groups: Dict[str, List[Dict]] = defaultdict(list)
        for pred in ens_preds:
            ts_str = pred.get('target_timestamp')
            if not ts_str:
                continue
            try:
                if isinstance(ts_str, str):
                    ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00').replace('+00:00', ''))
                else:
                    ts = ts_str
            except Exception:
                continue

            if time_window == 'hourly':
                key = f"{ts.hour:02d}:00"
            elif time_window == 'daily':
                key = ts.strftime('%m-%d')
            else:  # weekly
                weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
                key = weekday_names[ts.weekday()]

            groups[key].append(pred)

        # 构建 trends 数组
        trends_list: List[Dict[str, Any]] = []
        for key, group in groups.items():
            preds_vals = [float(p['load_forecast_mw']) for p in group if p.get('load_forecast_mw') is not None]
            actuals_vals = [float(p['actual_load_mw']) for p in group if p.get('actual_load_mw') is not None]

            point: Dict[str, Any] = {
                "time_label": key,
                "predicted_load": float(np.mean(preds_vals)) if preds_vals else 0,
            }

            if actuals_vals:
                point["actual_load"] = float(np.mean(actuals_vals))
                point["error"] = point["actual_load"] - point["predicted_load"]
                mask = np.abs(np.array(actuals_vals)) > 1e-6
                if np.any(mask):
                    p_arr = np.array([float(p['load_forecast_mw']) for p in group if p.get('actual_load_mw') is not None])
                    a_arr = np.array(actuals_vals)
                    errors = a_arr - p_arr
                    point["mape"] = float(np.mean(np.abs(errors[mask] / a_arr[mask])) * 100)
                else:
                    point["mape"] = 0.0
            else:
                point["actual_load"] = None
                point["error"] = None
                point["mape"] = None

            trends_list.append(point)

        # 按时间排序
        if time_window == 'hourly':
            trends_list.sort(key=lambda x: x["time_label"])
        elif time_window == 'daily':
            trends_list.sort(key=lambda x: x["time_label"])
        else:  # weekly
            order = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            trends_list.sort(key=lambda x: order.index(x["time_label"]) if x["time_label"] in order else 99)

        # 汇总信息
        all_preds = [float(p['load_forecast_mw']) for p in ens_preds if p.get('load_forecast_mw') is not None]
        all_actuals = [float(p['actual_load_mw']) for p in ens_preds if p.get('actual_load_mw') is not None]
        summary = {
            "total_records": len(ens_preds),
            "time_window": time_window,
            "avg_predicted_load": float(np.mean(all_preds)) if all_preds else 0,
            "avg_actual_load": float(np.mean(all_actuals)) if all_actuals else None,
            "time_range": {
                "start": ens_preds[0].get('target_timestamp') if ens_preds else None,
                "end": ens_preds[-1].get('target_timestamp') if ens_preds else None,
            }
        }
        if all_actuals and all_preds:
            mask = np.abs(np.array(all_actuals)) > 1e-6
            if np.any(mask):
                p_arr = np.array(all_preds[:len(all_actuals)])
                a_arr = np.array(all_actuals)
                errors = a_arr - p_arr
                summary["overall_mape"] = float(np.mean(np.abs(errors[mask] / a_arr[mask])) * 100)

        return {
            "status": "success",
            "message": f"成功完成时间维度趋势分析，时间窗口: {time_window}",
            "data": {"trends": trends_list, "summary": summary},
            "timestamp": eastern_now().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"时间维度趋势分析失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"时间维度趋势分析失败: {str(e)}"
        )


@router.get(
    "/error/distribution",
    response_model=Dict[str, Any],
    summary="预测误差分布分析",
    description="分析预测误差的分布特征"
)
async def analyze_error_distribution(
    days: int = Query(7, ge=1, le=30, description="分析天数"),
    db_manager=Depends(get_db_manager),
    analytics=Depends(get_prediction_analytics)
):
    """预测误差分布分析 - 返回前端期望的 ErrorDistribution 格式"""
    try:
        start_time = eastern_now_hour() - timedelta(days=days)
        predictions = await LoadPredictionsCRUD.get_predictions_by_time_range(
            start_time=start_time,
            end_time=eastern_now_hour()
        )

        # 过滤出包含实际值的 ensemble 预测
        ens_with_actual = [
            p for p in predictions
            if p.get('actual_load_mw') is not None
            and p.get('model_type', 'ensemble') == 'ensemble'
        ]

        if not ens_with_actual:
            return {
                "status": "success",
                "message": "指定时间范围内无包含实际值的预测数据",
                "data": None,
                "timestamp": eastern_now().isoformat()
            }

        preds = np.array([float(p['load_forecast_mw']) for p in ens_with_actual])
        actuals = np.array([float(p['actual_load_mw']) for p in ens_with_actual])
        errors = actuals - preds

        # 误差统计
        mean_error = float(np.mean(errors))
        std_error = float(np.std(errors))
        min_error = float(np.min(errors))
        max_error = float(np.max(errors))

        # 百分位数
        percentiles = {
            "p25": float(np.percentile(errors, 25)),
            "p50": float(np.percentile(errors, 50)),
            "p75": float(np.percentile(errors, 75)),
            "p95": float(np.percentile(errors, 95)),
        }

        # 偏差方向
        if mean_error > std_error * 0.1:
            bias = "over_predict"
        elif mean_error < -std_error * 0.1:
            bias = "under_predict"
        else:
            bias = "balanced"

        # 直方图数据
        hist_bins = 20
        hist_counts, hist_edges = np.histogram(errors, bins=hist_bins)
        histogram = []
        for i in range(len(hist_counts)):
            bin_label = f"{hist_edges[i]:.0f}~{hist_edges[i+1]:.0f}"
            histogram.append({"bin": bin_label, "count": int(hist_counts[i])})

        result = {
            "mean_error": mean_error,
            "std_error": std_error,
            "min_error": min_error,
            "max_error": max_error,
            "percentiles": percentiles,
            "histogram": histogram,
            "bias": bias,
        }

        return {
            "status": "success",
            "message": f"成功完成误差分布分析，共{len(ens_with_actual)}条有效记录",
            "data": result,
            "timestamp": eastern_now().isoformat()
        }

    except Exception as e:
        logger.error(f"误差分布分析失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"误差分布分析失败: {str(e)}"
        )


@router.get(
    "/patterns/load",
    response_model=Dict[str, Any],
    summary="负荷特性模式分析",
    description="分析电网负荷的时间模式特性"
)
async def analyze_load_patterns(
    days: int = Query(14, ge=1, le=90, description="分析天数"),
    db_manager=Depends(get_db_manager),
    analytics=Depends(get_prediction_analytics)
):
    """负荷特性模式分析"""
    try:
        # 获取历史预测数据
        start_time = eastern_now_hour() - timedelta(days=days)
        predictions = await LoadPredictionsCRUD.get_predictions_by_time_range(
            start_time=start_time,
            end_time=eastern_now_hour()
        )
        
        # 过滤出包含实际值的数据
        predictions_with_actual = [
            p for p in predictions 
            if p.get('actual_load_mw') is not None
        ]
        
        if not predictions_with_actual:
            return {
                "status": "success",
                "message": "指定时间范围内无包含实际值的预测数据",
                "data": {},
                "timestamp": eastern_now().isoformat()
            }
        
        # 执行负荷特性分析
        pattern_analysis = analytics.analyze_load_patterns(predictions_with_actual)
        
        return {
            "status": "success",
            "message": f"成功完成负荷特性分析，共{len(predictions_with_actual)}条有效记录",
            "data": pattern_analysis,
            "timestamp": eastern_now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"负荷特性分析失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"负荷特性分析失败: {str(e)}"
        )


@router.get(
    "/report/comprehensive",
    response_model=Dict[str, Any],
    summary="生成综合分析报告",
    description="生成包含所有分析维度的综合报告"
)
async def generate_comprehensive_report(
    days: int = Query(7, ge=1, le=30, description="分析天数"),
    db_manager=Depends(get_db_manager),
    analytics=Depends(get_prediction_analytics)
):
    """生成综合分析报告"""
    try:
        # 获取历史预测数据
        start_time = eastern_now_hour() - timedelta(days=days)
        predictions = await LoadPredictionsCRUD.get_predictions_by_time_range(
            start_time=start_time,
            end_time=eastern_now_hour()
        )
        
        if not predictions:
            return {
                "status": "success",
                "message": "指定时间范围内无预测数据",
                "data": {},
                "timestamp": eastern_now().isoformat()
            }
        
        logger.info(f"开始生成综合分析报告，分析 {len(predictions)} 条记录")
        
        # 生成综合报告
        comprehensive_report = analytics.generate_comprehensive_report(predictions)
        
        return {
            "status": "success",
            "message": f"成功生成综合分析报告，共分析{len(predictions)}条记录",
            "data": comprehensive_report,
            "timestamp": eastern_now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"综合分析报告生成失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"综合分析报告生成失败: {str(e)}"
        )


@router.get(
    "/dashboard/metrics",
    response_model=Dict[str, Any],
    summary="仪表板指标",
    description="获取仪表板所需的综合指标"
)
async def get_dashboard_metrics(
    hours: int = Query(24, ge=1, le=168, description="查询时间范围（小时）"),
    monitoring_service=Depends(get_monitoring_service),
    db_manager=Depends(get_db_manager),
    analytics=Depends(get_prediction_analytics)
):
    """获取仪表板综合指标"""
    try:
        # 从数据库计算准确性统计
        accuracy_stats = await _compute_accuracy_from_db(hours=hours)
        
        # 获取数据质量统计
        quality_stats = monitoring_service.data_quality_monitor.get_quality_stats()
        
        # 获取最近预测数据用于快速分析
        start_time = eastern_now_hour() - timedelta(hours=hours)
        recent_predictions = await LoadPredictionsCRUD.get_predictions_by_time_range(
            start_time=start_time,
            end_time=eastern_now_hour()
        )
        
        # 简要分析
        analysis_summary = {}
        if recent_predictions:
            recent_ens = [p for p in recent_predictions if p.get('model_type', 'ensemble') == 'ensemble']
            recent_with_actual = [p for p in recent_ens if p.get('actual_load_mw') is not None]
            if recent_with_actual:
                actuals = np.array([float(p['actual_load_mw']) for p in recent_with_actual])
                preds = np.array([float(p['load_forecast_mw']) for p in recent_with_actual])
                
                errors = actuals - preds
                mask = np.abs(actuals) > 1e-6
                mape = float(np.mean(np.abs(errors[mask] / actuals[mask])) * 100) if np.any(mask) else 0.0
                
                analysis_summary = {
                    "recent_records_count": len(recent_predictions),
                    "recent_with_actual_count": len(recent_with_actual),
                    "recent_mape": mape,
                    "recent_avg_load": float(np.mean(actuals))
                }
        
        dashboard_data = {
            "accuracy": accuracy_stats,
            "data_quality": quality_stats,
            "recent_analysis": analysis_summary,
            "system_status": "operational" if accuracy_stats.get('count', 0) > 0 else "warning"
        }
        
        return {
            "status": "success",
            "message": "成功获取仪表板指标",
            "data": dashboard_data,
            "timestamp": eastern_now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"获取仪表板指标失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取仪表板指标失败: {str(e)}"
        )