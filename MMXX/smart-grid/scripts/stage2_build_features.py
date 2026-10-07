# -*- coding: utf-8 -*-
"""
smart-grid / scripts / stage2_build_features.py
================================================
Stage 2 (data processing): build the CA-level feature frame + splits.

Inputs : data/processed/ca_hourly.parquet, zone_weather_wide.parquet
Outputs: data/processed/ca_features.parquet   (one row per physical hour)
         data/processed/splits.json
         data/processed/audit_stage2.json

Split policy (time-ordered, no shuffle leakage):
  train: ts_local <  2025-11-01 00:00   (2017 .. 2025-10-31)
  val  : 2025-11-01 <= ts_local < 2026-01-01   (2025-11 .. 2025-12)
  test : 2026-01-01 <= ts_local                (all of 2026 available rows)
ts_local is the hour-ENDING label of each row.

Notes
  * row-aligned DA_Demand / DA_LMP are the day-ahead market outcome for the
    delivery hour itself (published the previous afternoon) -> known at origin.
  * *_lag24/*_lag168 are same-clock lags one day / one week back.
  * *_prevNN_mean are rolling means of the PREVIOUS window (closed left).
  * temp_mem: shifted exponential-memory temperature (thermal inertia proxy).
  * raw target series are kept unchanged for the window/training stage.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

SPLIT_BOUNDS = {"val_start": "2025-11-01 00:00:00", "test_start": "2026-01-01 00:00:00"}
BALANCE_F = 65.0

ZONES = ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]


# --------------------------- US holidays / DST -------------------------------
def _nth_weekday(y: int, m: int, wd: int, n: int) -> date:
    first = date(y, m, 1)
    return first + timedelta(days=(wd - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(y: int, m: int, wd: int) -> date:
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - wd) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def us_federal_holidays(y0: int = 2016, y1: int = 2027) -> dict[date, str]:
    out = {}
    for y in range(y0, y1 + 1):
        base = [
            (date(y, 1, 1), "New Year"),
            (_nth_weekday(y, 1, 0, 3), "MLK Day"),
            (_nth_weekday(y, 2, 0, 3), "Presidents Day"),
            (_last_weekday(y, 5, 0), "Memorial Day"),
            (date(y, 6, 19), "Juneteenth"),
            (date(y, 7, 4), "Independence Day"),
            (_nth_weekday(y, 9, 0, 1), "Labor Day"),
            (_nth_weekday(y, 10, 0, 2), "Columbus Day"),
            (date(y, 11, 11), "Veterans Day"),
            (_nth_weekday(y, 11, 3, 4), "Thanksgiving"),
            (date(y, 12, 25), "Christmas"),
        ]
        for d, name in base:
            out[_observed(d)] = name
    return out


def us_dst_start_end(y: int) -> tuple[date, date]:
    return _nth_weekday(y, 3, 6, 2), _nth_weekday(y, 11, 6, 1)


# ----------------------------------------------------------------------------
def main() -> None:
    ca = pd.read_parquet(PROC / "ca_hourly.parquet")
    wet = pd.read_parquet(PROC / "zone_weather_wide.parquet")
    ca["date"] = pd.to_datetime(ca["date"])
    ts = pd.to_datetime(ca["ts_local"])

    out = pd.DataFrame({"seq": ca["seq"], "ts_local": ts, "date": ca["date"]})
    out["clock_hour"] = ca["clock_hour"].astype("int16")
    out["dst_dup"] = ca["dst_dup"].astype(bool)

    for c in ["RT_Demand", "DA_Demand", "System_Load", "RT_LMP", "DA_LMP",
              "Dry_Bulb", "Dew_Point", "RT_EC", "DA_EC"]:
        out[c] = pd.to_numeric(ca[c], errors="coerce").astype("float32")

    # ----- calendar -----
    d = out["date"].dt
    out["dow"] = d.dayofweek.astype("int8")
    out["month"] = d.month.astype("int8")
    out["dayofyear"] = d.dayofyear.astype("float32")
    out["is_weekend"] = (out["dow"] >= 5).astype("int8")
    for col, cyc in [("clock_hour", 24), ("dow", 7), ("month", 12)]:
        ang = 2 * np.pi * out[col] / cyc
        out[f"{col}_sin"] = np.sin(ang).astype("float32")
        out[f"{col}_cos"] = np.cos(ang).astype("float32")

    hol = us_federal_holidays()
    hol_days = set(hol)
    dates = out["date"].dt.date
    out["holiday_name"] = dates.map(lambda x: hol.get(x, ""))
    out["is_holiday"] = (out["holiday_name"] != "").astype("int8")
    out["holiday_shoulder"] = dates.apply(
        lambda x: any(abs((x - h).days) <= 2 for h in hol_days)
    ).astype("int8")
    out["is_dst"] = dates.map(lambda x: us_dst_start_end(x.year)[0] <= x < us_dst_start_end(x.year)[1]).astype("int8")

    # ----- weather derived (CA weighted temp) -----
    db = out["Dry_Bulb"].astype("float64")
    out["hdd65"] = np.clip(BALANCE_F - db, 0, None).astype("float32")
    out["cdd65"] = np.clip(db - BALANCE_F, 0, None).astype("float32")
    out["db_lag24"] = db.shift(24).astype("float32")
    out["db_lag168"] = db.shift(168).astype("float32")
    out["db_delta_24"] = (db - db.shift(24)).astype("float32")
    out["db_prev24_mean"] = db.shift(1).rolling(24).mean().astype("float32")
    out["temp_mem"] = db.shift(1).ewm(alpha=0.1, adjust=False).mean().astype("float32")

    # station temps wide
    for z in ZONES:
        out[f"db_{z}"] = wet[f"Dry_Bulb_{z}"].values.astype("float32")
        out[f"dp_{z}"] = wet[f"Dew_Point_{z}"].values.astype("float32")

    # ----- load / price lags & rolling -----
    rt = out["RT_Demand"].astype("float64")
    rtp = out["RT_LMP"].astype("float64")
    for lag in (1, 24, 168, 336):
        out[f"rt_lag{lag}"] = rt.shift(lag).astype("float32")
    out["da_lag24"] = out["DA_Demand"].astype("float64").shift(24).astype("float32")
    out["rt_prev24_mean"] = rt.shift(1).rolling(24).mean().astype("float32")
    out["rt_prev168_mean"] = rt.shift(1).rolling(168).mean().astype("float32")
    for lag in (1, 24, 168):
        out[f"rtlmp_lag{lag}"] = rtp.shift(lag).astype("float32")
    out["da_lmp_lag24"] = out["DA_LMP"].astype("float64").shift(24).astype("float32")
    out["rtlmp_prev24_mean"] = rtp.shift(1).rolling(24).mean().astype("float32")

    # ----- splits -----
    v0 = pd.Timestamp(SPLIT_BOUNDS["val_start"])
    t0 = pd.Timestamp(SPLIT_BOUNDS["test_start"])
    out["split"] = np.select([ts < v0, ts < t0], ["train", "val"], default="test")
    out = out.sort_values("seq").reset_index(drop=True)
    out.to_parquet(PROC / "ca_features.parquet", index=False)

    splits = {
        "boundaries": SPLIT_BOUNDS,
        "note": "ts_local = hour-ending; train 2017..2025-10-31 | val 2025-11..12 | test 2026 (all 2026 rows)",
        "counts": {k: int(v) for k, v in out["split"].value_counts().items()},
        "date_range_by_split": {
            k: [str(out.loc[out["split"] == k, "ts_local"].min()),
                str(out.loc[out["split"] == k, "ts_local"].max())]
            for k in ("train", "val", "test")
        },
    }
    (PROC / "splits.json").write_text(json.dumps(splits, ensure_ascii=False, indent=1), encoding="utf-8")

    # ----- audit -----
    nan_cols = {c: int(v) for c, v in out.isna().sum().items() if v > 0 and c != "holiday_name"}
    audit = {
        "rows": int(len(out)),
        "dup_seq": int(out["seq"].duplicated().sum()),
        "dup_ts_local": int(out["ts_local"].duplicated().sum()),
        "counts_by_split": splits["counts"],
        "feature_cols": int(out.shape[1]),
        "warmup_only": "lags/rollings NaN only in the first 336 rows by design",
        "nan_cols": nan_cols,
        "nan_all_le_336": bool(nan_cols and max(nan_cols.values()) <= 336) if nan_cols else True,
        "holiday_rows": int((out["is_holiday"] == 1).sum()),
        "holiday_rows_train": int(((out["split"] == "train") & (out["is_holiday"] == 1)).sum()),
    }
    (PROC / "audit_stage2.json").write_text(json.dumps(audit, ensure_ascii=False, indent=1), encoding="utf-8")

    # ----- console -----
    print("== stage2 summary ==")
    print(f"rows={audit['rows']} cols={audit['feature_cols']} dup_seq={audit['dup_seq']} dup_ts={audit['dup_ts_local']}")
    print("split counts:", splits["counts"])
    print("NaN columns (should be warmup head only, <=336):")
    for c, v in sorted(audit["nan_cols"].items()):
        print(f"   {c:20s} nan={v}")
    print("holiday rows total / train:", audit["holiday_rows"], "/", audit["holiday_rows_train"])
    print("warmup-only check:", audit["nan_all_le_336"])


if __name__ == "__main__":
    main()
