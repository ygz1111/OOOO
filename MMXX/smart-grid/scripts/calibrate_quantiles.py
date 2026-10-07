# -*- coding: utf-8 -*-
"""
smart-grid / scripts/calibrate_quantiles.py
============================================
Post-hoc quantile recalibration on the validation partition, applied to test.
For each quantile tau in {0.1,0.5,0.9}: p_cal = p50 + (p - p50) * s(tau)
where s(0.5)=1 and s(0.1)/s(0.9) chosen so the empirical rate of y below
the calibrated bound on VAL matches (0.1 / 0.9). p50 stays unchanged.
Writes: runs/<tag>/calibration.json and runs/<tag>/preds_test_calib.npz
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TAG = os.environ.get("FIG_TAG", "tf_v3")
RUN = ROOT / "runs" / TAG


def load(tag_: str):
    z = np.load(RUN / f"preds_{tag_}.npz")
    return z["y_price"], z["p_q"]


def below_rate(y, bound):
    return float(np.mean(y < bound))


def find_scale_lower(y, p50, q10, target=0.10, iters=50):
    """bound(a)=p50+(q10-p50)*a moves down as a grows (f decreasing). target in (f(1), f(0))"""
    lo, hi = 0.0, 1.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        r = below_rate(y, p50 + (q10 - p50) * mid)
        if r < target:      # too low -> need less widening (closer to p50)
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def find_scale_upper(y, p50, q90, target=0.90, iters=50):
    lo, hi = 0.0, 1.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        r = below_rate(y, p50 + (q90 - p50) * mid)
        if r < target:      # not enough coverage -> widen
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def main() -> None:
    yv, qv = load("val")
    yt, qt = load("test")
    # pooled over all horizons & origins
    a10 = find_scale_lower(yv.ravel(), qv[..., 1].ravel(), qv[..., 0].ravel())
    a90 = find_scale_upper(yv.ravel(), qv[..., 1].ravel(), qv[..., 2].ravel())
    res = {"a10": round(float(a10), 4), "a50": 1.0, "a90": round(float(a90), 4),
           "note": "bound_cal = p50 + (bound_raw - p50) * a, a in [0,1]"}

    def apply(y, q):
        lo = q[..., 1] + (q[..., 0] - q[..., 1]) * a10
        hi = q[..., 1] + (q[..., 2] - q[..., 1]) * a90
        return lo, hi

    def report(y, q, tag):
        lo, hi = apply(y, q)
        cov = float(np.mean((y >= lo) & (y <= hi)))
        below_lo = float(np.mean(y < lo))
        below_p50 = float(np.mean(y < q[..., 1]))
        return {"partition": tag, "p10_below": round(below_lo, 4),
                "p50_below": round(below_p50, 4), "p90_below": round(float(np.mean(y < hi)), 4),
                "p10p90_coverage": round(cov, 4)}

    res["val_calibrated"] = report(yv, qv, "val")
    res["test_calibrated"] = report(yt, qt, "test")

    lo_t, hi_t = apply(yt, qt)
    qt_cal = np.stack([lo_t, qt[..., 1], hi_t], axis=-1)
    np.savez(RUN / "preds_test_calib.npz", y_price=yt, p_q_cal=qt_cal)
    (RUN / "calibration.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    print("saved", RUN / "preds_test_calib.npz", "|", RUN / "calibration.json")


if __name__ == "__main__":
    main()
