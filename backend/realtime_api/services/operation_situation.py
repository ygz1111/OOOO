"""面向可视化大屏的智能电网运行态势聚合服务。

本模块只编排已有预测能力，不训练、不替换模型，也不把情景分析误写为真实
调度结果。新能源出力来自 TensorFlow 光伏模型，"供需缺口"严格表述为
光伏出力扣除后的净负荷（即仍需由常规电源、储能或外购电承担的需求）。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any

from realtime_api.services.container import (
    eastern_now,
    eastern_now_hour,
    get_engine_config,
    prediction_backend_ready,
    services,
)
from realtime_api.services.prediction_pipeline import dispatch_prediction


def _round(value: float | None, digits: int = 1) -> float | None:
    return round(float(value), digits) if value is not None else None


def _hour_label(timestamp: str) -> str:
    """Pipeline 时间戳为新英格兰墙钟时间，页面只需稳定展示小时。"""
    try:
        return timestamp[11:16]
    except (TypeError, IndexError):
        return timestamp


# ============================================================================
# 运行态势 / 特征敏感度缓存 + 并发单飞
# ============================================================================
# 运行态势会拉取 Open-Meteo 气象并执行完整预测管线；特征敏感度会在固定验收
# 窗口上执行 5 次模型推理。缓存 + single-flight 使并发请求共享一次计算，避免
# 页面进入、React 开发模式重复挂载或手动刷新造成重型任务叠加。
_SITUATION_CACHE: dict = {"timestamp": 0.0, "data": None}
_SITUATION_CACHE_TTL = 300.0
_situation_inflight = None  # Optional[asyncio.Task]

_SENSITIVITY_CACHE: dict = {"timestamp": 0.0, "data": None}
_sensitivity_inflight = None  # Optional[asyncio.Task]


async def build_operation_situation() -> dict[str, Any]:
    """生成未来 24 小时运行态势快照（5 分钟缓存 + 并发单飞）。

    在线数据使用共享预测；派生统计缓存按整点失效，准备中结果允许快速重试。
    single-flight 避免并发请求各自重复执行统计。
    """
    global _situation_inflight

    now_ts = time.time()
    # 快速路径：缓存命中直接返回（无锁、无等待）
    if (
        _SITUATION_CACHE["data"] is not None
        and now_ts - _SITUATION_CACHE["timestamp"] < _SITUATION_CACHE_TTL
        and _SITUATION_CACHE.get("hour") == eastern_now_hour()
        and not (_SITUATION_CACHE["data"].get("input_quality") or {}).get("refresh_in_progress")
    ):
        return _SITUATION_CACHE["data"]

    # 单飞路径：已有计算任务在跑，共享同一结果
    if _situation_inflight is not None and not _situation_inflight.done():
        try:
            return await asyncio.shield(_situation_inflight)
        except asyncio.CancelledError:
            raise

    # 创建新计算任务
    task = asyncio.create_task(_compute_and_cache_situation(now_ts))
    _situation_inflight = task
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        raise
    finally:
        if _situation_inflight is task and task.done():
            _situation_inflight = None


async def _compute_and_cache_situation(now_ts: float) -> dict[str, Any]:
    """执行运行态势计算并写缓存（供 single-flight 任务使用）"""
    try:
        source_hour = eastern_now_hour()
        data = await _build_operation_situation_impl()
        _SITUATION_CACHE["data"] = data
        _SITUATION_CACHE["timestamp"] = time.time()
        _SITUATION_CACHE["hour"] = source_hour
        return data
    except Exception:
        # 计算失败：清理 in-flight 引用，允许后续请求重新触发
        global _situation_inflight
        if _situation_inflight is not None:
            _situation_inflight = None
        raise


async def _build_operation_situation_impl() -> dict[str, Any]:
    """生成未来 24 小时运行态势快照（无缓存的实际计算逻辑）。

    在线模式读取其他页面共用的快照，最多等待约8秒，缺失模块独立留空。
    该只读分析不会写入预测表，避免仅刷新大屏就制造重复历史样本。
    """
    if str(get_engine_config().get("inference_mode", "live")).lower() == "live":
        from realtime_api.services.live_forecast import request_live_snapshot, snapshot_response
        prediction = snapshot_response(await request_live_snapshot())
    else:
        if not prediction_backend_ready():
            raise RuntimeError("负荷模型服务未就绪")
        weather_df, _ = await asyncio.to_thread(services.openmeteo_client.fetch_weather_data)
        prediction = await asyncio.to_thread(dispatch_prediction, weather_df, None)
    return _summarize_prediction(prediction)


def _summarize_prediction(prediction) -> dict[str, Any]:
    """Never replace unavailable PV/net load with zero or invent full-day totals."""
    rows = []
    for item in prediction.predictions:
        load = float(item.load_forecast_mw)
        pv = max(0.0, float(item.pv_estimation_mw)) if item.pv_estimation_mw is not None else None
        renewable = pv
        net_load = load - pv if pv is not None else None
        share = renewable / load * 100 if load > 0 and renewable is not None else None
        rows.append({
            "timestamp": item.timestamp,
            "time_label": _hour_label(item.timestamp),
            "load_mw": _round(load),
            "pv_mw": _round(pv),
            "renewable_mw": _round(renewable),
            "renewable_share_percent": _round(share, 2),
            "net_load_mw": _round(net_load),
        })

    def select(key, lowest=False):
        available = [row for row in rows if row[key] is not None]
        return (min if lowest else max)(available, key=lambda row: row[key]) if available else {
            "load_mw": None, "net_load_mw": None, "renewable_mw": None,
            "renewable_share_percent": None, "time_label": "—"}
    peak, valley = select("load_mw"), select("load_mw", lowest=True)
    peak_net, highest_share = select("net_load_mw"), select("renewable_share_percent")
    total_load = sum(row["load_mw"] for row in rows)
    pv_coverage = sum(row["renewable_mw"] is not None for row in rows)
    total_renewable = sum(row["renewable_mw"] for row in rows) if rows and pv_coverage == len(rows) else None
    ramps = [(abs(rows[i]["net_load_mw"] - rows[i - 1]["net_load_mw"]), i)
             for i in range(1, len(rows))
             if rows[i]["net_load_mw"] is not None and rows[i - 1]["net_load_mw"] is not None
             and datetime.fromisoformat(rows[i]["timestamp"]) - datetime.fromisoformat(rows[i - 1]["timestamp"]) == timedelta(hours=1)]
    max_ramp = max(ramps) if ramps else (None, None)

    risks: list[dict[str, str]] = []
    p90_load = sorted(row["load_mw"] for row in rows)[max(0, int(len(rows) * 0.9) - 1)] if rows else None
    for row in rows:
        if row["load_mw"] >= p90_load:
            risks.append({"level": "warning", "time": row["time_label"], "message": "预测负荷处于当日高位"})
        if row["renewable_share_percent"] is not None and row["renewable_share_percent"] < 3 and row["load_mw"] >= p90_load:
            risks.append({"level": "warning", "time": row["time_label"], "message": "高负荷时段新能源贡献偏低"})
    if max_ramp[0] is not None and max_ramp[0] > 0:
        risks.append({
            "level": "info",
            "time": rows[max_ramp[1]]["time_label"],
            "message": f"净负荷最大相邻小时爬坡 {_round(max_ramp[0])} MW，建议关注调峰资源",
        })

    return {
        "generated_at": prediction.timestamp,
        "input_quality": prediction.input_quality,
        "data_scope": {
            "region": "美国新英格兰地区",
            "horizon_hours": len(rows),
            "pv_coverage_hours": pv_coverage,
            "renewable_note": "光伏为 TensorFlow 模型预测值；供需指标表示扣除光伏后的净负荷，不代表真实全网电力缺口。",
        },
        "hourly": rows,
        "renewable": {
            "total_energy_mwh": _round(total_renewable),
            "average_share_percent": _round(total_renewable / total_load * 100 if total_load and total_renewable is not None else None, 2),
            "highest_share_percent": highest_share["renewable_share_percent"],
            "highest_share_time": highest_share["time_label"],
        },
        "peak_valley": {
            "peak_load_mw": peak["load_mw"], "peak_time": peak["time_label"],
            "valley_load_mw": valley["load_mw"], "valley_time": valley["time_label"],
            "spread_mw": _round(peak["load_mw"] - valley["load_mw"]) if rows else None,
            "peak_net_load_mw": peak_net["net_load_mw"], "peak_net_load_time": peak_net["time_label"],
            "renewable_peak_reduction_mw": peak_net["renewable_mw"],
        },
        "supply_demand": {
            "maximum_net_load_mw": peak_net["net_load_mw"],
            "maximum_net_load_time": peak_net["time_label"],
            "maximum_net_load_ramp_mw": _round(max_ramp[0]),
            "ramp_time": rows[max_ramp[1]]["time_label"] if max_ramp[1] is not None else "—",
            "interpretation": "净负荷可视为扣除预测新能源后，仍需由常规电源、储能或外购电承担的功率需求。",
        },
        "risks": risks[:8],
        "model": {"inference_time_ms": prediction.inference_time_ms, "data_source": prediction.data_source},
    }


async def build_feature_sensitivity() -> dict[str, Any]:
    """特征组遮蔽敏感度（进程内缓存 + 并发单飞）。

    该指标使用已加载模型的固定验收窗口，模型不重载时结果不会变化；因此首次
    计算后保持进程内缓存，避免每次进入页面都重复执行 5 次模型推理。
    """
    global _sensitivity_inflight

    now_ts = time.time()
    if _SENSITIVITY_CACHE["data"] is not None:
        return _SENSITIVITY_CACHE["data"]

    if _sensitivity_inflight is not None and not _sensitivity_inflight.done():
        try:
            return await asyncio.shield(_sensitivity_inflight)
        except asyncio.CancelledError:
            raise

    task = asyncio.create_task(_compute_and_cache_sensitivity(now_ts))
    _sensitivity_inflight = task
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        raise
    finally:
        if _sensitivity_inflight is task and task.done():
            _sensitivity_inflight = None


async def _compute_and_cache_sensitivity(now_ts: float) -> dict[str, Any]:
    try:
        data = await _build_feature_sensitivity_impl()
        _SENSITIVITY_CACHE["data"] = data
        _SENSITIVITY_CACHE["timestamp"] = now_ts
        return data
    except Exception:
        global _sensitivity_inflight
        if _sensitivity_inflight is not None:
            _sensitivity_inflight = None
        raise


async def _build_feature_sensitivity_impl() -> dict[str, Any]:
    """以特征遮蔽（occlusion）估计当前预测的输入敏感度（无缓存的实际计算逻辑）。

    将一个语义完整的特征组替换为该组在 168h 输入窗中的时间中位数，并比较
    集成预测曲线变化。该值表示模型对输入信息的敏感度，而非因果贡献或 SHAP 值。
    """
    if not prediction_backend_ready():
        raise RuntimeError("TensorFlow 负荷模型服务未就绪")
    impacts = await asyncio.to_thread(
        services.tf_load_price_service.calculate_demo_feature_sensitivity
    )
    return {
        "generated_at": eastern_now().isoformat(),
        "horizon_hours": 24,
        "ranking": impacts,
        "method_note": "采用 TensorFlow 特征组遮蔽敏感度：标准化后将指定特征置为训练均值，再比较24小时负荷曲线变化；它不是因果结论或SHAP值。",
        "data_note": "当前结果用于解释已训练 TensorFlow 模型，不会训练、更新或替换模型。",
    }
