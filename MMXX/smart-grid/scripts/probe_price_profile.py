# -*- coding: utf-8 -*-
"""Ground the quantile-price explanation in real numbers (RT_LMP hub)."""
import numpy as np
import pandas as pd
from pathlib import Path

PROC = Path("/home/wy/ai-projects/smart-grid/data/processed")
df = pd.read_parquet(PROC / "ca_features.parquet").sort_values("seq").reset_index(drop=True)
ts = pd.to_datetime(df["ts_local"])
rt = df["RT_LMP"].astype("float64")

# --- hour-of-day profile on the evaluation window 2026-06..07 ----------------
m = (ts >= "2026-06-01") & (ts < "2026-08-01")
sub = pd.DataFrame({"rt": rt[m], "hour": ts[m].dt.hour})
print("== RT_LMP $/MWh by hour, 2026-06..07 (p10 / p50 / p90) ==")
for h in (0, 8, 12, 16, 18, 21, 23):
    g = sub[sub["hour"] == h]["rt"]
    print(f"  hour {h:02d}: p10={g.quantile(.1):6.1f}  p50={g.median():6.1f}  p90={g.quantile(.9):6.1f}  "
          f"n={len(g)}")

# --- how often are prices 'spiky'? -------------------------------------------
for name, mm in [("2025", (ts >= "2025-01-01") & (ts < "2026-01-01")),
                 ("2026-01..07", (ts >= "2026-01-01") & (ts < "2026-08-01")),
                 ("val+test 06..07", m)]:
    g = rt[mm]
    thr = (50, 100, 200)
    print(f"\n== {name}: n={len(g)} mean={g.mean():.1f} med={g.median():.1f} p95={g.quantile(.95):.1f} "
          f"max={g.max():.1f}")
    for t in thr:
        print(f"    P(RT_LMP>{t}) = {(g > t).mean() * 100:.2f}%")

# --- what does a 'typical day' vs 'spike day' look like (July 2026 daily peaks)
jul = df[(ts >= "2026-07-01") & (ts < "2026-08-01")].copy()
daily = jul.groupby(pd.to_datetime(jul["ts_local"]).dt.date)["RT_LMP"].agg(["max", "median"])
print("\n== July 2026 daily max RT_LMP (top 6 days) ==")
print(daily.sort_values("max", ascending=False).head(6).round(1).to_string())
