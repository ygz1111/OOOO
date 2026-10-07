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
from realtime_api.utils.iso_ne_intervals import actual_label_sql
from datetime import date, datetime, timedelta
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


def _window_start(end_time: datetime, hours: int) -> datetime:
    """Return an inclusive start that contains exactly ``hours`` hourly points."""
    return end_time - timedelta(hours=max(hours - 1, 0))


def _as_naive_datetime(value: Any) -> Optional[datetime]:
    """Normalize database/ISO timestamps to a naive wall-clock datetime."""
    if isinstance(value, datetime):
        return (value.astimezone(_EST) if value.tzinfo else value).replace(tzinfo=None)
    if not value:
        return None
    try:
        cleaned = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(cleaned)
        return (parsed.astimezone(_EST) if parsed.tzinfo else parsed).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None

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
from realtime_api.services.operation_situation import build_feature_sensitivity, build_operation_situation
from realtime_api.services.prediction_insight import generate_day_backtest
from realtime_api.services.container import selected_load_backend, tf_load_backend_active
from realtime_api.services.lead_time_metrics import build_lead_time_metrics, latest_snapshot_per_target

# 日志配置
logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(
    prefix="/api/analytics",
    tags=["预测分析"]
)


def _active_load_model_type() -> str:
    """返回当前 TensorFlow 负荷模型写入数据库的模型标识。"""
    return selected_load_backend()


async def _get_active_prediction_records(
    start_time: datetime,
    end_time: datetime,
    *,
    dedupe_target: bool = True,
) -> List[Dict[str, Any]]:
    """Read only the active load model's persisted predictions."""
    return await LoadPredictionsCRUD.get_predictions_by_time_range(
        start_time=start_time,
        end_time=end_time,
        model_type=_active_load_model_type(),
        dedupe_target=dedupe_target,
    )


@router.get(
    "/operations/situation",
    response_model=Dict[str, Any],
    summary="智能电网综合运行态势",
    description="汇总未来24小时负荷、光伏、净负荷、新能源占比、峰谷与调峰风险。"
)
async def get_operation_situation():
    """返回独立、只读的 24h 运行态势快照。"""
    try:
        return {
            "status": "success",
            "message": "成功生成智能电网运行态势",
            "data": await build_operation_situation(),
            "timestamp": eastern_now().isoformat(),
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("生成运行态势失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成运行态势失败: {exc}")


@router.get(
    "/operations/feature-sensitivity",
    response_model=Dict[str, Any],
    summary="负荷预测特征敏感度",
    description="使用特征组遮蔽法分析当前24小时负荷预测对历史负荷、温度和时间特征的敏感度。"
)
async def get_feature_sensitivity():
    """返回不重训模型的当前预测输入敏感度。"""
    try:
        return {
            "status": "success", "message": "成功生成特征敏感度分析",
            "data": await build_feature_sensitivity(),
            "timestamp": eastern_now().isoformat(),
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("生成特征敏感度失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成特征敏感度失败: {exc}")


@router.get(
    "/diagnostics/hourly-errors",
    response_model=Dict[str, Any],
    summary="分小时预测误差诊断",
    description="按目标小时汇总已回填真实负荷的预测误差，提供热力图和透明的误差诊断依据。"
)
async def get_hourly_error_diagnostics(
    days: int = Query(7, ge=1, le=30, description="回溯天数，最多30天"),
):
    """基于持久化预测与真实负荷生成小时维度误差画像。

    这是后验误差诊断而非伪造的特征重要度：系统未运行 SHAP 等归因算法，
    因此只报告可由真实预测记录直接验证的时段偏差。
    """
    try:
        now = eastern_now_hour()
        records = await _get_active_prediction_records(
            start_time=now - timedelta(days=days), end_time=now
        )
        valid = [
            row for row in records
            if row.get("actual_load_mw") is not None
            and row.get("target_timestamp") is not None
        ]
        buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
        heatmap: list[dict[str, Any]] = []
        for row in valid:
            target = row["target_timestamp"]
            hour = target.hour
            forecast, actual = float(row["load_forecast_mw"]), float(row["actual_load_mw"])
            error = forecast - actual  # 正值表示高估，前端无需猜测方向
            item = {"hour": hour, "date": target.date().isoformat(), "error_mw": round(error, 2),
                    "absolute_error_mw": round(abs(error), 2),
                    "mape": round(abs(error) / actual * 100, 3) if abs(actual) > 1e-6 else None}
            buckets[hour].append(item)
            heatmap.append(item)

        hourly = []
        for hour in range(24):
            values = buckets[hour]
            if not values:
                hourly.append({"hour": hour, "count": 0, "mae_mw": None, "mape": None, "bias_mw": None})
                continue
            errors = np.array([item["error_mw"] for item in values], dtype=float)
            mapes = [item["mape"] for item in values if item["mape"] is not None]
            hourly.append({
                "hour": hour, "count": len(values),
                "mae_mw": round(float(np.mean(np.abs(errors))), 2),
                "mape": round(float(np.mean(mapes)), 3) if mapes else None,
                "bias_mw": round(float(np.mean(errors)), 2),
            })

        populated = [item for item in hourly if item["count"]]
        worst = max(populated, key=lambda item: item["mae_mw"]) if populated else None
        return {
            "status": "success", "message": "成功生成分小时误差诊断",
            "data": {
                "days": days, "sample_count": len(valid), "hourly": hourly, "heatmap": heatmap,
                "insight": (
                    f"{worst['hour']:02d}:00 的平均绝对误差最高，为 {worst['mae_mw']:.1f} MW。"
                    if worst else "暂无已回填实际负荷的历史样本，暂不能进行误差诊断。"
                ),
                "method_note": "正偏差表示预测高于实际；本诊断为历史误差分组统计，不将相关性误表述为模型因果解释。",
            }, "timestamp": eastern_now().isoformat(),
        }
    except Exception as exc:
        logger.error("生成分小时误差诊断失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成分小时误差诊断失败: {exc}")


@router.get(
    "/backtest/date",
    response_model=Dict[str, Any],
    summary="任意日期历史回测与对比",
    description="对指定日期（ET 时区）用该日之前的历史气象重新调用负荷模型，"
                "与该日 ISO-NE 真实负荷逐小时对比，返回误差、MAE/RMSE/MAPE 与当日区域平均气象。"
                "缺省只返回可用回测日期范围。"
)
async def get_day_backtest(
    d: Optional[date] = Query(
        None, alias="date",
        description="回测日期 YYYY-MM-DD（ET 时区）；缺省仅返回可用日期范围"
    ),
    force_refresh: bool = Query(
        False,
        description="是否跳过60秒内存缓存并重新计算；页面手动刷新时使用",
    ),
):
    """任意日期回测：只读计算，不写入任何数据表、不重训模型。"""
    try:
        if d is None:
            data = await generate_day_backtest(None)
            return {
                "status": "success", "message": "可用回测日期范围",
                "data": data, "timestamp": eastern_now().isoformat(),
            }
        data = await generate_day_backtest(d, force_refresh=force_refresh)
        return {
            "status": "success", "message": f"成功生成 {d.isoformat()} 历史回测对比",
            "data": data, "timestamp": eastern_now().isoformat(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("生成任意日期历史回测失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成任意日期历史回测失败: {exc}")


async def _compute_accuracy_from_db(hours: int = 168) -> Dict[str, Any]:
    """Compute online metrics from persisted predictions of the active engine only."""
    now = eastern_now_hour()
    start_time = _window_start(now, hours)
    model_type = _active_load_model_type()
    # One query retains all causal vintages for lead-time groups. The existing
    # overall result still selects the latest forecast per target hour.
    all_predictions = await _get_active_prediction_records(start_time, now, dedupe_target=False)
    lead_time_metrics = build_lead_time_metrics(all_predictions)
    predictions = latest_snapshot_per_target(all_predictions)

    records_with_actual = [p for p in predictions if p.get('actual_load_mw') is not None]

    if not records_with_actual:
        return {"count": 0, "mape": None, "rmse": None, "mae": None, "r2": None,
                "best_model": None, "worst_model": None, "model_type": model_type,
                "window_hours": hours,
                "metric_scope": "latest_snapshot_per_target",
                "metric_note": "每个目标小时只保留当前生产模型的最新在线预测快照；不是固定提前24小时的同一预测步长。",
                **lead_time_metrics}

    preds = np.array([float(p['load_forecast_mw']) for p in records_with_actual])
    actuals = np.array([float(p['actual_load_mw']) for p in records_with_actual])
    errors = actuals - preds

    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    mask = np.abs(actuals) > 1e-6
    mape = float(np.mean(np.abs(errors[mask] / actuals[mask])) * 100) if np.any(mask) else 0.0
    ss_res = np.sum(errors ** 2)
    ss_tot = np.sum((actuals - np.mean(actuals)) ** 2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot != 0 else 0.0

    return {
        "count": len(records_with_actual),
        "mape": mape,
        "rmse": rmse,
        "mae": mae,
        "r2": r2,
        "best_model": model_type,
        "worst_model": model_type,
        "model_type": model_type,
        "window_hours": hours,
        "metric_scope": "latest_snapshot_per_target",
        "metric_note": "每个目标小时只保留当前生产模型的最新在线预测快照；不是固定提前24小时的同一预测步长。",
        **lead_time_metrics,
    }


@router.get(
    "/accuracy/stats",
    response_model=Dict[str, Any],
    summary="获取预测准确性统计",
    description="获取当前预测准确性指标（MAPE、RMSE、MAE、R²）"
)
async def get_accuracy_stats(
    days: int = Query(7, ge=1, le=30, description="在线预测误差统计窗口（天）"),
    monitoring_service=Depends(get_monitoring_service),
):
    """Return 1--30 day online metrics for the active production model."""
    try:
        stats = await _compute_accuracy_from_db(hours=days * 24)
        
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
    db_manager=Depends(get_db_manager),
):
    """获取最近预测记录（真实数据：load_predictions 表，含回填的实际值）"""
    try:
        # 内存 accuracy_tracker 无数据源（无人调用 record），改为直接查库
        sql = f"""
            SELECT target_timestamp, load_forecast_mw, {actual_label_sql()} AS actual_load_mw,
                   prediction_timestamp, model_type, data_source
            FROM load_predictions
            WHERE prediction_timestamp < target_timestamp
            ORDER BY prediction_timestamp DESC
            LIMIT %s
        """
        rows = await db_manager.execute_sql(sql, (limit,))
        records = [
            {
                "timestamp": r["prediction_timestamp"].isoformat()
                if r.get("prediction_timestamp") else None,
                "target_timestamp": r["target_timestamp"].isoformat()
                if r.get("target_timestamp") else None,
                "prediction": r.get("load_forecast_mw"),
                "actual": r.get("actual_load_mw"),
                "model_type": r.get("model_type"),
                "data_source": r.get("data_source"),
            }
            for r in rows
        ]

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
        # 仅检查当前 TensorFlow 生产模型，避免不同模型版本混入漂移判断。
        now = eastern_now_hour()
        start_time = _window_start(now, 7 * 24)
        predictions = await _get_active_prediction_records(start_time, now)

        ens_with_actual = [p for p in predictions if p.get('actual_load_mw') is not None]

        minimum_samples = 24
        if len(ens_with_actual) < minimum_samples:
            # 数据不足，返回默认值
            result = {
                "drift_detected": False,
                "drift_score": 0.0,
                "threshold": 0.25,
                "recent_mape": None,
                "baseline_mape": None,
                "drift_direction": "insufficient_data",
                "change_percent": None,
                "sample_count": len(ens_with_actual),
                "recommendation": f"数据量不足，需至少{minimum_samples}条含实际值的预测记录才能进行漂移检测"
            }
        else:
            # 解析时间戳并排序
            parsed = []
            for p in ens_with_actual:
                ts = _as_naive_datetime(p.get('target_timestamp'))
                if ts is None:
                    continue
                try:
                    parsed.append((ts, float(p['load_forecast_mw']), float(p['actual_load_mw'])))
                except Exception:
                    continue

            parsed.sort(key=lambda x: x[0])

            if len(parsed) < minimum_samples:
                result = {
                    "drift_detected": False,
                    "drift_score": 0.0,
                    "threshold": 0.25,
                    "recent_mape": None,
                    "baseline_mape": None,
                    "drift_direction": "insufficient_data",
                    "change_percent": None,
                    "sample_count": len(parsed),
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

                # 只把性能恶化计为漂移。MAPE 下降是改善，不能触发漂移告警。
                if baseline_mape > 1e-6:
                    signed_change = (recent_mape - baseline_mape) / baseline_mape
                else:
                    signed_change = 0.0
                drift_score = max(0.0, signed_change)

                threshold = 0.25  # 25%变化率作为漂移阈值
                drift_detected = drift_score > threshold

                if drift_detected:
                    recommendation = f"检测到模型性能下降：MAPE从{baseline_mape:.2f}%升至{recent_mape:.2f}%，建议检查近期数据并评估是否重新训练"
                elif signed_change < -0.05:
                    recommendation = f"模型近期表现改善：MAPE从{baseline_mape:.2f}%降至{recent_mape:.2f}%，无需触发漂移告警"
                else:
                    recommendation = "模型预测准确性保持稳定，无需干预"

                result = {
                    "drift_detected": drift_detected,
                    "drift_score": float(drift_score),
                    "threshold": threshold,
                    "recent_mape": recent_mape,
                    "baseline_mape": baseline_mape,
                    "drift_direction": "degraded" if signed_change > 0.05 else "improved" if signed_change < -0.05 else "stable",
                    "change_percent": float(signed_change * 100),
                    "sample_count": len(parsed),
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
    hours: int = Query(24, ge=1, le=720, description="查询时间范围（小时，最多30天）"),
    db_manager=Depends(get_db_manager),
):
    """多模型预测对比分析 - 返回 Record<string, ModelComparisonItem>"""
    try:
        # 按预测生成时间读取完整窗口，避免固定 LIMIT 在频繁刷新时截断某些模型。
        now = eastern_now()
        cutoff = now - timedelta(hours=hours)
        raw_predictions = await db_manager.execute_sql(
            f"""
            SELECT id, prediction_timestamp, target_timestamp, load_forecast_mw,
                   {actual_label_sql()} AS actual_load_mw, model_type, inference_time_ms, data_source
            FROM load_predictions
            WHERE prediction_timestamp BETWEEN %s AND %s
              AND prediction_timestamp < target_timestamp
            ORDER BY prediction_timestamp DESC, id DESC
            """,
            (cutoff, now),
        )

        # 同一模型、同一目标时刻只保留该窗口内最新一次预测快照。
        by_target: Dict[str, Dict] = {}
        for p in raw_predictions:
            target = p.get('target_timestamp')
            key = f"{p.get('model_type', 'unknown')}|{target}" if target is not None else None
            if key:
                by_target.setdefault(key, p)
        predictions = list(by_target.values())

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

        # 多模型只有在完全相同的目标小时上才允许横向比较指标。
        actual_targets: Dict[str, set] = {}
        for model_name, rows in model_groups.items():
            actual_targets[model_name] = {
                str(row.get('target_timestamp'))
                for row in rows
                if row.get('target_timestamp') is not None and row.get('actual_load_mw') is not None
            }
        common_targets: set = set()
        if actual_targets:
            common_targets = set.intersection(*actual_targets.values())

        result: Dict[str, Any] = {}

        for model_name, preds in model_groups.items():
            if not preds:
                continue

            # 单模型展示其自身有效样本；多模型则严格限定共同目标小时。
            preds_with_actual = [p for p in preds if p.get('actual_load_mw') is not None]
            if len(model_groups) > 1:
                metric_rows = [
                    p for p in preds_with_actual
                    if str(p.get('target_timestamp')) in common_targets
                ]
                comparison_scope = "common_targets"
                comparison_note = (
                    f"指标仅使用 {len(common_targets)} 个共同目标小时进行公平比较"
                    if common_targets
                    else "窗口内没有所有模型共同覆盖且已回填真实值的目标小时，暂不计算横向指标"
                )
            else:
                metric_rows = preds_with_actual
                comparison_scope = "single_model_window"
                comparison_note = "当前窗口只有一个负荷模型，不构成横向模型比较"

            item: Dict[str, Any] = {
                "model_name": model_name,
                "count": len(preds),
                "metric_count": len(metric_rows),
                "mape": None,
                "rmse": None,
                "mae": None,
                "avg_inference_time_ms": None,
                "comparison_scope": comparison_scope,
                "comparison_note": comparison_note,
                "lifecycle": "active" if model_name == _active_load_model_type() else "archived",
            }

            # 平均推理时间
            inf_times = [float(p['inference_time_ms']) for p in preds if p.get('inference_time_ms') is not None]
            if inf_times:
                item["avg_inference_time_ms"] = float(np.mean(inf_times))

            if metric_rows:
                p_arr = np.array([float(p['load_forecast_mw']) for p in metric_rows])
                a_arr = np.array([float(p['actual_load_mw']) for p in metric_rows])
                errors = p_arr - a_arr

                item["mae"] = float(np.mean(np.abs(errors)))
                item["rmse"] = float(np.sqrt(np.mean(errors ** 2)))

                mask = np.abs(a_arr) > 1e-6
                if np.any(mask):
                    item["mape"] = float(np.mean(np.abs(errors[mask] / a_arr[mask])) * 100)

            result[model_name] = item

        return {
            "status": "success",
            "message": f"成功完成负荷模型版本对比，共分析{len(predictions)}条去重记录",
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
):
    """时间维度趋势分析 - 返回 {trends: TrendDataPoint[], summary: any}"""
    try:
        if time_window not in ["hourly", "daily", "weekly"]:
            raise HTTPException(
                status_code=400,
                detail="time_window参数必须是 hourly, daily 或 weekly"
            )

        now = eastern_now_hour()
        start_time = _window_start(now, days * 24)
        ens_preds = await _get_active_prediction_records(start_time, now)

        if not ens_preds:
            return {
                "status": "success",
                "message": "指定时间范围内无预测数据",
                "data": {"trends": [], "summary": {}},
                "timestamp": eastern_now().isoformat()
            }

        # 按时间窗口分组
        groups: Dict[str, Dict[str, Any]] = {}
        for pred in ens_preds:
            ts = _as_naive_datetime(pred.get('target_timestamp'))
            if ts is None:
                continue

            if time_window == 'hourly':
                key = ts.strftime('%Y-%m-%d %H:00')
                label = ts.strftime('%m-%d %H:00')
            elif time_window == 'daily':
                key = ts.strftime('%Y-%m-%d')
                label = ts.strftime('%m-%d')
            else:  # weekly
                week_start = (ts - timedelta(days=ts.weekday())).date()
                key = week_start.isoformat()
                label = f"{week_start.strftime('%m-%d')}周"

            bucket = groups.setdefault(key, {"label": label, "rows": []})
            bucket["rows"].append(pred)

        # 构建 trends 数组
        trends_list: List[Dict[str, Any]] = []
        for key in sorted(groups):
            bucket = groups[key]
            group = bucket["rows"]
            preds_vals = [float(p['load_forecast_mw']) for p in group if p.get('load_forecast_mw') is not None]
            paired_rows = [
                p for p in group
                if p.get('load_forecast_mw') is not None and p.get('actual_load_mw') is not None
            ]
            paired_preds = [float(p['load_forecast_mw']) for p in paired_rows]
            actuals_vals = [float(p['actual_load_mw']) for p in paired_rows]

            point: Dict[str, Any] = {
                "time_label": bucket["label"],
                "predicted_load": float(np.mean(paired_preds or preds_vals)) if (paired_preds or preds_vals) else None,
                "prediction_count": len(preds_vals),
                "paired_count": len(paired_rows),
            }

            if actuals_vals:
                point["actual_load"] = float(np.mean(actuals_vals))
                point["error"] = point["predicted_load"] - point["actual_load"]
                mask = np.abs(np.array(actuals_vals)) > 1e-6
                if np.any(mask):
                    p_arr = np.array(paired_preds)
                    a_arr = np.array(actuals_vals)
                    errors = p_arr - a_arr
                    point["mape"] = float(np.mean(np.abs(errors[mask] / a_arr[mask])) * 100)
                else:
                    point["mape"] = 0.0
            else:
                point["actual_load"] = None
                point["error"] = None
                point["mape"] = None

            trends_list.append(point)

        # 汇总信息
        all_preds = [float(p['load_forecast_mw']) for p in ens_preds if p.get('load_forecast_mw') is not None]
        all_paired = [
            (float(p['load_forecast_mw']), float(p['actual_load_mw']))
            for p in ens_preds
            if p.get('load_forecast_mw') is not None and p.get('actual_load_mw') is not None
        ]
        summary = {
            "total_records": len(ens_preds),
            "paired_records": len(all_paired),
            "time_window": time_window,
            "avg_predicted_load": float(np.mean([p for p, _ in all_paired])) if all_paired else (float(np.mean(all_preds)) if all_preds else None),
            "avg_actual_load": float(np.mean([a for _, a in all_paired])) if all_paired else None,
            "time_range": {
                "start": ens_preds[0].get('target_timestamp') if ens_preds else None,
                "end": ens_preds[-1].get('target_timestamp') if ens_preds else None,
            }
        }
        # 2026-08 修复：按行成对过滤（同时含预测值与实际值的记录）再计算误差，
        # 此前按长度截断配对，中间缺 actual 的记录会导致错位。
        if all_paired:
            p_arr = np.array([x[0] for x in all_paired])
            a_arr = np.array([x[1] for x in all_paired])
            mask = np.abs(a_arr) > 1e-6
            if np.any(mask):
                errors = p_arr - a_arr
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
):
    """预测误差分布分析 - 返回前端期望的 ErrorDistribution 格式"""
    try:
        now = eastern_now_hour()
        start_time = _window_start(now, days * 24)
        predictions = await _get_active_prediction_records(start_time, now)

        # 只使用当前生产模型且已回填实际值的记录。
        ens_with_actual = [p for p in predictions if p.get('actual_load_mw') is not None]

        if not ens_with_actual:
            return {
                "status": "success",
                "message": "指定时间范围内无包含实际值的预测数据",
                "data": None,
                "timestamp": eastern_now().isoformat()
            }

        preds = np.array([float(p['load_forecast_mw']) for p in ens_with_actual])
        actuals = np.array([float(p['actual_load_mw']) for p in ens_with_actual])
        # 全站统一：误差 = 预测 - 实际；正值表示高估，负值表示低估。
        errors = preds - actuals

        # 误差统计
        mean_error = float(np.mean(errors))
        std_error = float(np.std(errors))
        min_error = float(np.min(errors))
        max_error = float(np.max(errors))
        max_absolute_error = float(np.max(np.abs(errors)))

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
            "max_absolute_error": max_absolute_error,
            "percentiles": percentiles,
            "histogram": histogram,
            "bias": bias,
            "sample_count": len(ens_with_actual),
            "error_definition": "forecast_minus_actual",
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
        now = eastern_now_hour()
        start_time = _window_start(now, days * 24)
        predictions = await _get_active_prediction_records(start_time, now)
        
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
        now = eastern_now_hour()
        start_time = _window_start(now, days * 24)
        predictions = await _get_active_prediction_records(start_time, now)
        
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
        now = eastern_now_hour()
        start_time = _window_start(now, hours)
        recent_predictions = await _get_active_prediction_records(start_time, now)
        
        # 简要分析
        analysis_summary = {}
        if recent_predictions:
            recent_ens = recent_predictions
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

# ============================================================================
# 预测 vs 实际 对比（真实实际负荷）
# ============================================================================

@router.get(
    "/prediction-vs-actual",
    response_model=Dict[str, Any],
    summary="预测 vs 实际负荷对比",
    description=(
        "返回最近 N 小时预测负荷 vs 真实实际负荷的小时级配对数据，"
        "含逐小时误差与汇总统计（MAE/MAPE/RMSE）。"
        "实际负荷来自 ISO-NE（data_source=iso_ne）真实数据。"
    )
)
async def prediction_vs_actual(
    hours: int = Query(48, ge=1, le=168, description="回看小时数"),
    db_manager=Depends(get_db_manager),
):
    """小时级预测 vs 实际对比（按 target_timestamp 去重取最新预测）"""
    try:
        # 每个 target_timestamp 取最新一次预测（MySQL 8 窗口函数）。
        # 2026-08 修复：限定最近 N 小时窗口 + 降序取最新 N 条，
        # 此前 ORDER BY ASC 会返回"最早"的有实际值的 N 条记录。
        cutoff = eastern_now_hour() - timedelta(hours=hours)
        sql = f"""
            SELECT target_timestamp, load_forecast_mw, actual_load_mw
            FROM (
                SELECT target_timestamp, load_forecast_mw, {actual_label_sql()} AS actual_load_mw,
                       ROW_NUMBER() OVER (
                           PARTITION BY target_timestamp
                           ORDER BY prediction_timestamp DESC
                       ) AS rn
                FROM load_predictions
                WHERE target_timestamp >= %s
                  AND prediction_timestamp < target_timestamp
            ) t
            WHERE rn = 1 AND actual_load_mw IS NOT NULL
            ORDER BY target_timestamp DESC
            LIMIT %s
        """
        rows = await db_manager.execute_sql(sql, (cutoff, hours))
        # 升序返回（前端按时间正序展示更自然）
        rows = list(reversed(rows))
        if not rows:
            return {
                "status": "success",
                "message": "暂无预测 vs 实际配对数据（实际负荷未接入）",
                "data": {"pairs": [], "summary": None},
                "timestamp": eastern_now().isoformat(),
            }

        import numpy as np
        pairs = []
        errors = []
        for r in rows:
            forecast = float(r["load_forecast_mw"] or 0)
            actual = float(r["actual_load_mw"] or 0)
            abs_err = abs(forecast - actual)
            pct_err = abs_err / actual * 100 if actual > 1 else None
            errors.append(abs_err)
            pairs.append({
                "target_timestamp": r["target_timestamp"].isoformat(),
                "load_forecast_mw": round(forecast, 1),
                "actual_load_mw": round(actual, 1),
                "absolute_error_mw": round(abs_err, 1),
                "percentage_error": round(pct_err, 2) if pct_err is not None else None,
            })

        arr = np.array(errors)
        mae = float(arr.mean())
        rmse = float(np.sqrt(np.mean(arr ** 2)))
        mask = np.abs([p["actual_load_mw"] for p in pairs]) > 1
        mape = float(np.mean([
            p["absolute_error_mw"] / p["actual_load_mw"] * 100
            for p, m in zip(pairs, mask) if m
        ])) if mask.any() else None

        summary = {
            "count": len(pairs),
            "mae_mw": round(mae, 1),
            "rmse_mw": round(rmse, 1),
            "mape": round(mape, 2) if mape is not None else None,
            "data_source": "iso_ne",
            "note": "实际负荷来自 ISO-NE 真实数据",
        }
        return {
            "status": "success",
            "message": "获取预测 vs 实际对比成功",
            "data": {"pairs": pairs, "summary": summary},
            "timestamp": eastern_now().isoformat(),
        }

    except Exception as e:
        logger.error(f"获取预测vs实际对比失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"获取预测vs实际对比失败: {str(e)}"
        )
