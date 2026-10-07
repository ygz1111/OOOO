# -*- coding: utf-8 -*-
import json
import pandas as pd
import numpy as np
from pathlib import Path

P = Path(r"C:\MMXX\datas\btm_pv_data.xlsx")

# Notes sheet text
notes = pd.read_excel(P, sheet_name="User Notes", header=None)
print("=== User Notes (rows 0..60) ===")
for i, r in notes.head(60).iterrows():
    vals = [str(v).strip() for v in r.tolist() if isinstance(v, str) and v.strip()]
    if vals:
        print(f"  row{i}: " + " | ".join(vals)[:240])

for sheet in ["BTM PV", "Normalized BTM PV"]:
    df = pd.read_excel(P, sheet_name=sheet)
    print("\n" + "=" * 30, sheet, "=" * 30)
    print("shape:", df.shape)
    df["dt"] = pd.to_datetime(dict(year=df["Year"], month=df["Month"], day=df["Day"]), errors="coerce")
    print("date min/max:", df["dt"].min(), df["dt"].max())
    print("rows by year:", df.groupby("Year").size().to_dict())
    he = df["HourEnding"].astype(str)
    print("HourEnding unique sample:", sorted(he.unique())[:5], "...", sorted(he.unique())[-5:], "nuniq:", he.nunique())
    zone_cols = [c for c in df.columns if c not in ("Year", "Month", "Day", "HourEnding", "dt")]
    rep = {}
    for c in zone_cols:
        s = df[c]
        rep[c] = dict(n=int(len(s)), nan=int(s.isna().sum()), min=round(float(s.min()), 3),
                      mean=round(float(s.mean()), 3), max=round(float(s.max()), 3),
                      neg=int((s < 0).sum()), zero=int((s == 0).sum()), nz_rate=round(float((s > 0).mean()) * 100, 2))
    print("zone stats:", json.dumps(rep, indent=1))
    # rows per day (DST check)
    cnt = df.groupby(df["dt"].dt.date).size()
    print("days rows!=24:", {str(k): int(v) for k, v in cnt.items() if v != 24})
