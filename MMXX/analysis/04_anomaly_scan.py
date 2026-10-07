# -*- coding: utf-8 -*-
"""
Step 4 - targeted anomaly & consistency analysis.
(1) CA vs sum(zones) RT/DA demand reconciliation
(2) monthly LMP stats per year for CA (spot the 2026 DA/RT spread anomaly)
(3) negative DA_Demand rows location for VT / ME
(4) weather sanity: monthly min/max Dry_Bulb for CA
(5) crude spike scan on RT_Demand by month+hour context (|z|>6)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(r"C:\MMXX\datas")
OUT = Path(r"C:\MMXX\analysis\out")
OUT.mkdir(parents=True, exist_ok=True)
report = {}

ZONES = ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]


def load(path, sheet):
    df = pd.read_excel(path, sheet_name=sheet)
    df["_date"] = pd.to_datetime(df["Date"], errors="coerce")
    hrend = df["Hr_End"].astype(str).str.replace("X", "", regex=False)
    df["_hour"] = pd.to_numeric(hrend, errors="coerce")
    return df


def ts_of(r):
    if pd.isna(r["_date"]) or pd.isna(r["_hour"]):
        return pd.NaT
    return r["_date"] + pd.Timedelta(hours=int(r["_hour"]))


for f in sorted(DATA_DIR.glob("*.xlsx")):
    year = f.stem[:4]
    rep = {}

    ca = load(f, "ISO NE CA")
    ca["ts"] = ca.apply(ts_of, axis=1)
    ca = ca.set_index("ts").sort_index()

    # (1) reconciliation CA RT/DA vs sum of zones
    rt_sum = None
    da_sum = None
    for z in ZONES:
        zdf = load(f, z)
        zdf["ts"] = zdf.apply(ts_of, axis=1)
        zdf = zdf.set_index("ts").sort_index()
        rt_sum = zdf["RT_Demand"] if rt_sum is None else rt_sum.add(zdf["RT_Demand"], fill_value=0)
        da_sum = zdf["DA_Demand"] if da_sum is None else da_sum.add(zdf["DA_Demand"], fill_value=0)
    idx = ca["RT_Demand"].index.intersection(rt_sum.index)
    diff_rt = (ca.loc[idx, "RT_Demand"] - rt_sum.loc[idx]).abs()
    diff_da = (ca.loc[idx, "DA_Demand"] - da_sum.loc[idx]).abs()
    rep["RT_ca_vs_sumzones"] = {
        "max_abs_diff": round(float(diff_rt.max()), 3),
        "mean_abs_diff": round(float(diff_rt.mean()), 3),
        "p99_abs_diff": round(float(diff_rt.quantile(0.99)), 3),
        "pct_abs_lt_1MW": round(float((diff_rt < 1).mean() * 100), 2),
    }
    rep["DA_ca_vs_sumzones"] = {
        "max_abs_diff": round(float(diff_da.max()), 3),
        "mean_abs_diff": round(float(diff_da.mean()), 3),
        "p99_abs_diff": round(float(diff_da.quantile(0.99)), 3),
    }

    # (2) monthly LMP stats (CA / Trading Hub)
    m = ca.set_index(ca.index).copy()
    m["ym"] = m.index.to_period("M")
    lmp = []
    for ym, g in m.groupby("ym"):
        lmp.append({
            "month": str(ym),
            "DA_LMP_med": round(float(g["DA_LMP"].median()), 2),
            "RT_LMP_med": round(float(g["RT_LMP"].median()), 2),
            "DA_LMP_p95": round(float(g["DA_LMP"].quantile(0.95)), 2),
            "RT_LMP_p95": round(float(g["RT_LMP"].quantile(0.95)), 2),
            "DA_minus_RT_mean": round(float((g["DA_LMP"] - g["RT_LMP"]).mean()), 2),
            "spread_p95_abs": round(float((g["DA_LMP"] - g["RT_LMP"]).abs().quantile(0.95)), 2),
            "DA_EC_med": round(float(g["DA_EC"].median()), 2),
            "RT_EC_med": round(float(g["RT_EC"].median()), 2),
        })
    rep["monthly_LMP"] = lmp

    # (3) negative DA_Demand rows VT/ME
    neg = {}
    for z in ("VT", "ME"):
        zdf = load(f, z)
        zdf["ts"] = zdf.apply(ts_of, axis=1)
        bad = zdf[zdf["DA_Demand"] < 0]
        neg[z] = {
            "n": int(len(bad)),
            "min": round(float(bad["DA_Demand"].min()), 2) if len(bad) else None,
            "by_month": {str(k): int(v) for k, v in bad["_date"].dt.to_period("M").value_counts().sort_index().items()},
            "sample_ts": [str(x) for x in bad["ts"].head(3).tolist()],
        }
    rep["negative_DA_Demand"] = neg

    # (4) weather sanity: Dry_Bulb min/max per month for CA + count of non-finite
    w = ca[["Dry_Bulb", "Dew_Point"]].copy()
    w["ym"] = ca.index.to_period("M")
    rep["CA_weather"] = {
        "Dry_Bulb_global": {"min": round(float(w["Dry_Bulb"].min()), 2),
                            "max": round(float(w["Dry_Bulb"].max()), 2),
                            "nan": int(w["Dry_Bulb"].isna().sum())},
        "Dew_Point_global": {"min": round(float(w["Dew_Point"].min()), 2),
                             "max": round(float(w["Dew_Point"].max()), 2),
                             "nan": int(w["Dew_Point"].isna().sum())},
        "month_minmax": [{"month": str(k),
                          "db_min": round(float(v["Dry_Bulb"].min()), 1),
                          "db_max": round(float(v["Dry_Bulb"].max()), 1)}
                         for k, v in w.groupby("ym")],
    }

    # (5) spike scan RT_Demand by (month, hour) context: z = (x-med)/MAD-ish
    rt = ca["RT_Demand"].copy()
    ref = pd.DataFrame({"rt": rt, "month": rt.index.month, "hour": rt.index.hour})
    spikes = []
    for (mo, hr), g in ref.groupby(["month", "hour"]):
        med = g["rt"].median()
        mad = (g["rt"] - med).abs().median() * 1.4826 + 1e-9
        z = (g["rt"] - med) / mad
        bad = g[z.abs() > 6]
        for ts_i, row in bad.iterrows():
            spikes.append({"ts": str(ts_i), "value": round(float(row["rt"]), 1),
                           "month_hr_med": round(float(med), 1), "z": round(float(z.loc[ts_i]), 1)})
    rep["RT_spikes_z6"] = spikes[:50]
    rep["RT_spikes_z6_count"] = len(spikes)

    report[year] = rep
    print(f"{year}: done ({len(lmp)} months, {len(spikes)} spikes)", flush=True)

with open(OUT / "anomalies.json", "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=1)
print("saved", OUT / "anomalies.json")
