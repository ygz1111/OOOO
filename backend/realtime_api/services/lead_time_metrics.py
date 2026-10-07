"""Read-only, physical lead-time metrics for stored online load forecasts.

The database keeps Eastern wall-clock timestamps. Ambiguous/nonexistent naive
DST timestamps cannot be recovered, so they are excluded instead of guessing.
No forecast generation time is replaced by a request or cache-restoration time.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np

EASTERN = ZoneInfo("America/New_York")
QUALITY_LABELS = {
    "complete": "完整输入",
    "estimated": "估计补齐输入",
    "unknown": "历史输入质量未留档",
}
GROUPS = (("1_6", 1, 6), ("7_12", 7, 12), ("13_24", 13, 24))


def _utc_timestamp(value: Any) -> tuple[datetime | None, str | None]:
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None, "invalid_timestamp"
    if stamp.tzinfo is not None:
        return stamp.astimezone(timezone.utc), None
    first = stamp.replace(tzinfo=EASTERN, fold=0)
    second = stamp.replace(tzinfo=EASTERN, fold=1)
    valid_first = first.astimezone(timezone.utc).astimezone(EASTERN).replace(tzinfo=None) == stamp
    valid_second = second.astimezone(timezone.utc).astimezone(EASTERN).replace(tzinfo=None) == stamp
    if not valid_first and not valid_second:
        return None, "invalid_timestamp"
    if valid_first and valid_second and first.utcoffset() != second.utcoffset():
        return None, "ambiguous_timestamp"
    return (first if valid_first else second).astimezone(timezone.utc), None


def _quality(row: dict[str, Any]) -> str:
    markers = set(str(row.get("data_source") or "").split("+"))
    if "estimated_inputs" in markers:
        return "estimated"
    if "input_quality_complete" in markers:
        return "complete"
    return "unknown"


def _metrics(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    if not rows:
        return {"count": 0, "mae": None, "rmse": None, "mape": None, "bias": None, "r2": None}
    forecast = np.array([float(row["load_forecast_mw"]) for row in rows])
    actual = np.array([float(row["actual_load_mw"]) for row in rows])
    error = forecast - actual
    mask = np.abs(actual) > 1e-6
    variance = float(np.sum((actual - actual.mean()) ** 2))
    return {
        "count": len(rows),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "mape": float(np.mean(np.abs(error[mask] / actual[mask])) * 100) if mask.any() else None,
        "bias": float(error.mean()),
        "r2": float(1 - np.sum(error ** 2) / variance) if variance else None,
    }


def latest_snapshot_per_target(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirror the existing SQL target/latest/id ordering for overall metrics."""
    latest: dict[Any, tuple[tuple[Any, Any], dict[str, Any]]] = {}
    unkeyed: list[dict[str, Any]] = []
    for row in rows:
        target = row.get("target_timestamp")
        generated = row.get("prediction_timestamp")
        if target is None or generated is None:
            # Retain the prior helper contract for callers with preselected rows.
            unkeyed.append(row)
            continue
        try:
            stamp = generated if isinstance(generated, datetime) else datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
            if stamp.tzinfo is not None:
                stamp = stamp.astimezone(EASTERN).replace(tzinfo=None)
            generated_key = stamp.isoformat(timespec="microseconds")
        except (TypeError, ValueError):
            generated_key = str(generated)
        # Keep the legacy SQL wall-clock ordering for the overall metric.
        order = (generated_key, int(row.get("id") or 0))
        previous = latest.get(target)
        if previous is None or order > previous[0]:
            latest[target] = (order, row)
    return [entry[1] for entry in latest.values()] + unkeyed


def build_lead_time_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """One earliest forecast per physical target hour within each lead group."""
    selected: dict[str, dict[datetime, tuple[tuple[datetime, int], dict[str, Any]]]] = {key: {} for key, _, _ in GROUPS}
    excluded = dict.fromkeys(("invalid_timestamp", "ambiguous_timestamp", "noncausal", "outside_24_hours", "invalid_values"), 0)
    for row in rows:
        # Labels were joined through actual_label_sql: missing/unverified actuals
        # do not become zero-valued observations or usable metric samples.
        if row.get("actual_load_mw") is None:
            continue
        try:
            forecast = float(row["load_forecast_mw"])
            actual = float(row["actual_load_mw"])
            if not math.isfinite(forecast) or not math.isfinite(actual) or actual < 0:
                raise ValueError("invalid values")
        except (TypeError, ValueError, KeyError, OverflowError):
            excluded["invalid_values"] += 1
            continue
        generated, error = _utc_timestamp(row.get("prediction_timestamp"))
        target, target_error = _utc_timestamp(row.get("target_timestamp"))
        if error or target_error:
            excluded[error or target_error] += 1
            continue
        seconds = (target - generated).total_seconds()
        if seconds <= 0:
            excluded["noncausal"] += 1
            continue
        if seconds > 24 * 3600:
            excluded["outside_24_hours"] += 1
            continue
        # A 00:05 generation for HE 01:00 has 55 minutes of lead and belongs
        # to step 1. floor() would silently drop it into a nonexistent step 0.
        lead_hour = math.ceil(seconds / 3600)
        key = next(key for key, lo, hi in GROUPS if lo <= lead_hour <= hi)
        order = (generated, int(row.get("id") or 0))
        previous = selected[key].get(target)
        if previous is None or order < previous[0]:
            selected[key][target] = (order, row)
    groups = []
    for key, lo, hi in GROUPS:
        group_rows = [item[1] for item in selected[key].values()]
        groups.append({
            "key": key, "label": f"提前 {lo}–{hi} 小时", "min_hour": lo, "max_hour": hi,
            **_metrics(group_rows),
            "input_quality": [
                {"quality": quality, "label": label, **_metrics(row for row in group_rows if _quality(row) == quality)}
                for quality, label in QUALITY_LABELS.items()
            ],
        })
    return {
        "lead_time_groups": groups,
        "lead_time_scope": "earliest_snapshot_per_target_within_lead_group",
        "lead_time_note": "以原始生成时间到目标小时末的实际时长划组（0–6、>6–12、>12–24小时），组内每个目标小时只取最早生成的在线快照；同一目标可分别出现在不同组，组样本数不能相加当作独立目标小时总数。输入质量未留档的旧记录单独标为未知；无实测标签不参与统计。",
        "lead_time_excluded": excluded,
    }
