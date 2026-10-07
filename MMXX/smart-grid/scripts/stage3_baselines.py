# -*- coding: utf-8 -*-
"""
smart-grid / scripts / stage3_baselines.py
==========================================
Stage 0 baselines for the CA load target (RT_Demand, MW).
Untrained rules, evaluated on the VAL and TEST partitions only.
Results -> runs/baselines/metrics.json + runs/baselines/REPORT.md

Baselines
  naive24      : RT(t-24h)                      (yesterday same hour)
  naive168     : RT(t-168h)                     (last week same hour)
  week_profile : mean RT by (day-of-week, clock-hour) fit on TRAIN only
  DA_as_pred   : DA_Demand (day-ahead cleared demand, known at origin)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
RUNS = ROOT / "runs" / "baselines"
RUNS.mkdir(parents=True, exist_ok=True)

df = pd.read_parquet(PROC / "ca_features.parquet").sort_values("seq").reset_index(drop=True)
rt = df["RT_Demand"].astype("float64")
da = df["DA_Demand"].astype("float64")

# week profile fit on TRAIN only
tr = df[df["split"] == "train"]
prof = tr.groupby(["dow", "clock_hour"])["RT_Demand"].mean()
df["prof_pred"] = df.apply(lambda r: prof.get((int(r["dow"]), int(r["clock_hour"])), np.nan), axis=1)

preds = {
    "naive24": rt.shift(24),
    "naive168": rt.shift(168),
    "week_profile_train": df["prof_pred"],
    "DA_as_pred": da,
}

HOURS = df["ts_local"].dt.hour  # local label hour of hour-ending instant


def metrics(y, p, hours):
    m = p.notna() & y.notna()
    y, p, hours = y[m], p[m], hours[m]
    if len(y) == 0:
        return None
    rmse = float(np.sqrt(np.mean((y - p) ** 2)))
    mae = float(np.mean(np.abs(y - p)))
    mape = float(np.mean(np.abs(y - p) / y) * 100)
    peak = hours.between(17, 20).values
    return {
        "n": int(len(y)),
        "RMSE_MW": round(rmse, 1),
        "MAE_MW": round(mae, 1),
        "MAPE_pct": round(mape, 2),
        "peak(17-20h)_MAE_MW": round(float(np.mean(np.abs(y[peak] - p[peak]))), 1) if peak.any() else None,
    }


report = {"note": "CA RT_Demand (MW), out-of-sample on val/test. DA_as_pred uses row-aligned DA_Demand "
                  "(legit: published day-ahead)."}
for part in ("val", "test"):
    mask = df["split"] == part
    y = rt[mask]
    h = HOURS[mask]
    report[part] = {}
    for name, p in preds.items():
        m = metrics(y, p[mask], h)
        if m:
            report[part][name] = m

# human-readable markdown
lines = ["# Stage-0 Baselines (CA RT_Demand, MW)", "",
         "Out-of-sample; lower is better. **DA_as_pred is the practical bar to beat.**", ""]
lines += ["| split | baseline | RMSE | MAE | MAPE% | peak(17-20h) MAE |", "|---|---|---|---|---|---|"]
for part in ("val", "test"):
    for name in ("naive24", "naive168", "week_profile_train", "DA_as_pred"):
        m = report[part].get(name)
        if m:
            lines.append(f"| {part} | {name} | {m['RMSE_MW']} | {m['MAE_MW']} | "
                         f"{m['MAPE_pct']} | {m['peak(17-20h)_MAE_MW']} |")
(RUNS / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
(RUNS / "metrics.json").write_text(json.dumps(report, indent=1), encoding="utf-8")

print("== STAGE-0 BASELINES (CA RT_Demand, MW) ==")
for part in ("val", "test"):
    print(f"--- {part} ---")
    for name, m in report[part].items():
        print(f"  {name:18s} RMSE={m['RMSE_MW']:8.1f}  MAE={m['MAE_MW']:8.1f}  MAPE={m['MAPE_pct']:5.2f}%  "
              f"peakMAE={m['peak(17-20h)_MAE_MW']}")
print("\nreports:", RUNS / "REPORT.md", "|", RUNS / "metrics.json")
