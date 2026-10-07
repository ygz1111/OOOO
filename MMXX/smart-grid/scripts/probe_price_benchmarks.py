# -*- coding: utf-8 -*-
"""
Evidence: how predictable are the price series from history alone?
Benchmarks computed OUT-OF-SAMPLE on 2025 (full) and 2026-06..07 (val+test
window) for Trading-Hub RT_LMP / DA_LMP. No model training.
"""
import numpy as np
import pandas as pd
from pathlib import Path

PROC = Path("/home/wy/ai-projects/smart-grid/data/processed")
df = pd.read_parquet(PROC / "ca_features.parquet")
df = df.sort_values("seq").reset_index(drop=True)
rt = df["RT_LMP"].astype("float64")
da = df["DA_LMP"].astype("float64")
ts = pd.to_datetime(df["ts_local"])


def metrics(y, pred):
    m = pred.notna() & y.notna()
    y, p = y[m], pred[m]
    if len(y) == 0:
        return None
    rmse = float(np.sqrt(np.mean((y - p) ** 2)))
    mae = float(np.mean(np.abs(y - p)))
    # MAPE with a 2 $/MWh floor to avoid div-by-near-zero blowups
    mape = float(np.mean(np.abs(y - p) / np.maximum(y.abs(), 2.0)) * 100)
    return dict(n=int(len(y)), RMSE=round(rmse, 2), MAE=round(mae, 2), MAPE_floor2=round(mape, 2))


def window(mask):
    y = rt[mask]
    yda = da[mask]
    lvl = dict(n=int(len(y)), RT_mean=round(float(y.mean()), 2), RT_med=round(float(y.median()), 2),
               RT_p95=round(float(y.quantile(0.95)), 2), DA_mean=round(float(yda.mean()), 2))
    return {
        "level": lvl,
        "naive24_rt": metrics(y, rt.shift(24)[mask]),
        "naive168_rt": metrics(y, rt.shift(168)[mask]),
        "DA_as_pred_of_RT": metrics(y, yda),
        "DA_naive24": metrics(yda, da.shift(24)[mask]),
    }


out = {}
m25 = (ts >= "2025-01-01") & (ts < "2026-01-01")
m26 = (ts >= "2026-06-01") & (ts < "2026-08-01")
out["2025"] = window(m25)
out["2026_Jun_Jul"] = window(m26)

for k, v in out.items():
    print(f"== {k} ==")
    print("  level:", v["level"])
    for name, m in v.items():
        if name != "level":
            print(f"  {name:16s}", m)

pd.Series(out).to_json(PROC / "price_benchmarks.json", indent=1)
print("\nsaved price_benchmarks.json")
