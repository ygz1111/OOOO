# -*- coding: utf-8 -*-
"""
Step 5 - baseline sizing & seasonality profile (ISO NE CA, RT demand).
Naive benchmarks evaluated out-of-sample, plus load/weather correlation.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(r"C:\MMXX\datas")
OUT = Path(r"C:\MMXX\analysis\out")


def load_ca(path):
    df = pd.read_excel(path, sheet_name="ISO NE CA")
    df["_date"] = pd.to_datetime(df["Date"], errors="coerce")
    hr = df["Hr_End"].astype(str).str.replace("X", "", regex=False)
    df["_hour"] = pd.to_numeric(hr, errors="coerce")
    df = df.sort_values(["_date", "_hour"]).reset_index(drop=True)
    # clock hour for profile features
    clock = df["_hour"].astype(int) % 24  # 24->0 ; 02X(2)->2
    df["_clock"] = clock
    df["_dow"] = df["_date"].dt.dayofweek
    return df


def metrics(y, pred, name):
    mask = pred.notna() & y.notna()
    y, p = y[mask], pred[mask]
    if len(y) == 0:
        return None
    rmse = float(np.sqrt(np.mean((y - p) ** 2)))
    mae = float(np.mean(np.abs(y - p)))
    mape = float(np.mean(np.abs(y - p) / y) * 100)
    return {"name": name, "n": int(len(y)), "RMSE_MW": round(rmse, 1),
            "MAE_MW": round(mae, 1), "MAPE_pct": round(mape, 2)}


res = {}
ca2024 = load_ca(DATA_DIR / "2024_smd_hourly.xlsx")
ca2025 = load_ca(DATA_DIR / "2025_smd_hourly.xlsx")
ca2026 = load_ca(DATA_DIR / "2026_smd_hourly.xlsx")
rt24 = ca2024["RT_Demand"].reset_index(drop=True)
rt25 = ca2025["RT_Demand"].reset_index(drop=True)
rt26 = ca2026["RT_Demand"].reset_index(drop=True)

# hour-of-week profile from 2024 (clock local)
wk = ca2024.groupby(["_dow", "_clock"])["RT_Demand"].mean()
prof24 = wk.rename("p")


def apply_profile(ca):
    return ca.apply(lambda r: prof24.get((int(r["_dow"]), int(r["_clock"])), np.nan), axis=1)


preds = {}
# on 2025
preds["2025_naive24"] = pd.Series(rt25).shift(24)
preds["2025_naive168"] = pd.Series(rt25).shift(168)
preds["2025_DA_as_pred"] = ca2025["DA_Demand"]
preds["2025_profile24"] = apply_profile(ca2025)
# on 2026 (Jan..Jul)
preds["2026_naive24"] = pd.Series(rt26).shift(24)
preds["2026_naive168"] = pd.Series(rt26).shift(168)
preds["2026_DA_as_pred"] = ca2026["DA_Demand"]
preds["2026_profile24"] = apply_profile(ca2026)

yref = {"2025": pd.Series(rt25), "2026": pd.Series(rt26)}
out = []
for yr in ("2025", "2026"):
    for k, v in preds.items():
        if k.startswith(yr):
            m = metrics(yref[yr], v.reset_index(drop=True), k)
            if m:
                out.append(m)

res["baselines"] = out

# residual gap: how good is DA_Demand vs actual RT (the achievable target & benchmark)
res["DA_RT_gap"] = {
    "2025_mean_abs": round(float((ca2025["DA_Demand"] - ca2025["RT_Demand"]).abs().mean()), 1),
    "2025_std": round(float((ca2025["DA_Demand"] - ca2025["RT_Demand"]).std()), 1),
    "2026_mean_abs": round(float((ca2026["DA_Demand"] - ca2026["RT_Demand"]).abs().mean()), 1),
    "2026_std": round(float((ca2026["DA_Demand"] - ca2026["RT_Demand"]).std()), 1),
}

# temperature-load correlation (CA weighted temp vs CA RT demand)
def corr_block(ca, tag):
    rt = ca["RT_Demand"]
    db = ca["Dry_Bulb"]
    dp = ca["Dew_Point"]
    hdd = np.clip(65 - db, 0, None)
    cdd = np.clip(db - 65, 0, None)
    return {
        tag + "_corr_RT_DryBulb": round(float(rt.corr(db)), 3),
        tag + "_corr_RT_CDD65": round(float(rt.corr(cdd)), 3),
        tag + "_corr_RT_HDD65": round(float(rt.corr(hdd)), 3),
        tag + "_corr_RT_DewPoint": round(float(rt.corr(dp)), 3),
        tag + "_mean_RT": round(float(rt.mean()), 1),
        tag + "_std_RT": round(float(rt.std()), 1),
        tag + "_p50_RT": round(float(rt.median()), 1),
    }


corr = {}
for name, ca in (("2024", ca2024), ("2025", ca2025), ("2026", ca2026)):
    corr.update(corr_block(ca, name))
res["correlations"] = corr

# profile sample: mean RT by weekday & hour (2024) for 0,12,18,23 and weekday/weekend averages
prof = pd.DataFrame({"dow": wk.index.get_level_values(0), "clock": wk.index.get_level_values(1), "mean": wk.values})
pivot = wk.unstack(0)
res["profile_sample"] = {
    "weekday_hours_mean": round(float(pivot.loc[:, [0, 1, 2, 3, 4]].mean(axis=1).mean()), 1),
    "weekend_hours_mean": round(float(pivot.loc[:, [5, 6]].mean(axis=1).mean()), 1),
    "mean_by_hour_p50_weekday": [round(float(pivot.loc[h, [0, 1, 2, 3, 4]].median()), 1) for h in (0, 6, 12, 18, 23)],
    "mean_by_hour_p50_weekend": [round(float(pivot.loc[h, [5, 6]].median()), 1) for h in (0, 6, 12, 18, 23)],
}

with open(OUT / "baselines_seasonality.json", "w", encoding="utf-8") as fh:
    json.dump(res, fh, ensure_ascii=False, indent=1)

for b in res["baselines"]:
    print(b)
print(json.dumps(res["correlations"], indent=1))
print(json.dumps(res["profile_sample"], indent=1))
print("DA_RT gap:", res["DA_RT_gap"])
