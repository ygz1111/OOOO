# -*- coding: utf-8 -*-
"""ISO-NE BTM PV capacity references used by TensorFlow PV inference.

The PV network predicts ISO-NE's normalized regional BTM PV target.  Converting
that target back to MW and normalizing live history must use the capacity that
belongs to each timestamp; using one frozen 2026-Q1 value creates a systematic
scale drift as installations are added.

The anchors below come from the official 2026 CELT workbook, sheet
``3.1 PV Forecast - Nameplate``.  Row 41 publishes cumulative BTM PV AC
nameplate totals.  For 2026, row 40 gives 363 MW annual growth and sheet
``3.2 PV Forecast - BTM MW`` row 46 gives end-of-month cumulative growth
shares.  Values inside a month are linearly interpolated between published
month-end anchors; no observed PV output is used to estimate the capacity.
"""

from __future__ import annotations

from calendar import monthrange

import numpy as np
import pandas as pd


CELT_2026_URL = (
    "https://www.iso-ne.com/static-assets/documents/100035/2026_celt.xlsx"
)
CELT_2025_YEAR_END_BTM_MW = 5131.0
CELT_2026_BTM_GROWTH_MW = 363.0
CELT_2026_MONTH_END_GROWTH_SHARE = (
    0.06, 0.11, 0.19, 0.26, 0.32, 0.41,
    0.48, 0.55, 0.63, 0.72, 0.81, 1.00,
)

# Official CELT year-end cumulative BTM PV AC nameplate totals (MW), row 41.
CELT_YEAR_END_BTM_MW = {
    2025: 5131.0,
    2026: 5494.0,
    2027: 5831.0,
    2028: 6225.0,
    2029: 6540.0,
    2030: 6803.0,
    2031: 7023.0,
    2032: 7244.0,
    2033: 7476.0,
    2034: 7710.0,
    2035: 7950.0,
}


def _naive_timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("America/New_York").tz_localize(None)
    return ts


def _2026_month_end_anchors() -> list[tuple[pd.Timestamp, float]]:
    anchors = [(pd.Timestamp("2025-12-31 23:59:59"), CELT_2025_YEAR_END_BTM_MW)]
    for month, share in enumerate(CELT_2026_MONTH_END_GROWTH_SHARE, start=1):
        last_day = monthrange(2026, month)[1]
        anchors.append((
            pd.Timestamp(2026, month, last_day, 23, 59, 59),
            CELT_2025_YEAR_END_BTM_MW + CELT_2026_BTM_GROWTH_MW * share,
        ))
    return anchors


def _capacity_anchors() -> list[tuple[pd.Timestamp, float]]:
    anchors = _2026_month_end_anchors()
    anchors.extend(
        (pd.Timestamp(year, 12, 31, 23, 59, 59), capacity)
        for year, capacity in CELT_YEAR_END_BTM_MW.items()
        if year >= 2027
    )
    return anchors


_ANCHORS = _capacity_anchors()


def btm_pv_capacity_mw(timestamp, *, fallback_mw: float) -> float:
    """Return the non-leaking ISO-NE BTM PV capacity for ``timestamp``.

    Dates before the first official CELT anchor keep the model asset's frozen
    training fallback.  Dates from 2026 onward interpolate only between
    capacity anchors already published in the 2026 CELT forecast.
    """
    ts = _naive_timestamp(timestamp)
    if ts <= _ANCHORS[0][0]:
        return float(fallback_mw)
    if ts >= _ANCHORS[-1][0]:
        return float(_ANCHORS[-1][1])

    for (left_ts, left_value), (right_ts, right_value) in zip(_ANCHORS, _ANCHORS[1:]):
        if left_ts < ts <= right_ts:
            span = (right_ts - left_ts).total_seconds()
            elapsed = (ts - left_ts).total_seconds()
            return float(left_value + (right_value - left_value) * elapsed / span)
    return float(fallback_mw)


def btm_pv_capacity_array(timestamps, *, fallback_mw: float) -> np.ndarray:
    """Vector form of :func:`btm_pv_capacity_mw`."""
    return np.asarray(
        [btm_pv_capacity_mw(value, fallback_mw=fallback_mw) for value in timestamps],
        dtype="float64",
    )


__all__ = [
    "CELT_2026_URL",
    "CELT_YEAR_END_BTM_MW",
    "btm_pv_capacity_mw",
    "btm_pv_capacity_array",
]
