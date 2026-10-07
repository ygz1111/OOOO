# -*- coding: utf-8 -*-
"""
smart-grid / scripts / stage1_build_canonical.py
=================================================
Stage 1 (data processing): read the three ISO-NE SMD workbooks in data/raw
and build canonical hourly datasets used by every later stage.

Outputs (data/processed/):
  ca_hourly.parquet         -- ISO NE CA control area, one row per physical hour
  zone_hourly.parquet       -- 8 load zones, long format (seq aligned with CA)
  zone_weather_wide.parquet -- per-zone Dry_Bulb/Dew_Point wide (station-aware)
  audit_stage1.json         -- validation report

Conventions
  - ts_local  : hour-ENDING wall-clock label in US Eastern local time
  - date      : ISO-NE calendar date of the observation (day the hour starts)
  - clock_hour: local hour 0..23 (Hr_End 24 -> 0, '02X' -> 2)
  - seq       : globally unique hour id derived from the CA table chronological
                order. CA, zone-long and zone-weather-wide tables all share the
                SAME seq for the same physical hour -> joinable on seq.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

ZONES = ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]
CA_SHEET = "ISO NE CA"

CA_COLS_ORIG = [
    "DA_Demand", "RT_Demand",
    "DA_LMP", "DA_EC", "DA_CC", "DA_MLC",
    "RT_LMP", "RT_EC", "RT_CC", "RT_MLC",
    "Dry_Bulb", "Dew_Point",
    "System_Load",
    "Reg_Service_Price", "Reg_Capacity_Price",
    "Min_5min_RSP", "Max_5min_RSP", "Min_5min_RCP", "Max_5min_RCP",
]
ZONE_COLS_ORIG = [
    "DA_Demand", "RT_Demand",
    "DA_LMP", "DA_EC", "DA_CC", "DA_MLC",
    "RT_LMP", "RT_EC", "RT_CC", "RT_MLC",
    "Dry_Bulb", "Dew_Point",
]

KEEP_EXTRA = ["seq", "ts_local", "date", "clock_hour", "dst_dup"]


def hr_key(raw) -> float:
    s = str(raw).strip()
    if s.endswith("X"):
        return int(s[:-1]) + 0.5
    return float(int(s))


def parse_sheet(path: Path, sheet: str, keep: list[str]) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet)
    cols = ["Date", "Hr_End"] + keep
    df = df[[c for c in cols if c in df.columns]].copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Hr_End"] = df["Hr_End"].astype(str).str.strip()
    for c in keep:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    is_x = df["Hr_End"].str.endswith("X")
    num = df["Hr_End"].str.replace("X", "", regex=False).astype(int)
    df["clock_hour"] = num % 24
    df["dst_dup"] = is_x
    df["hr_sort"] = df["Hr_End"].map(hr_key)
    df["ts_local"] = df.apply(
        lambda r: (r["Date"] + pd.Timedelta(hours=int(r["Hr_End"].replace("X", "")))) if pd.notna(r["Date"]) else pd.NaT,
        axis=1,
    )
    return df


def main() -> None:
    files = sorted(RAW.glob("*.xlsx"))
    print(f"found {len(files)} workbooks in {RAW}: {[f.name for f in files]}")
    ca_frames, zone_frames = [], []
    audit_rep = {"files": [f.name for f in files]}

    for path in files:
        ca = parse_sheet(path, CA_SHEET, CA_COLS_ORIG)
        # schema consistency across all downloaded years
        expect = set(["Date", "Hr_End"] + CA_COLS_ORIG)
        got = set(ca.columns)
        assert expect.issubset(got), f"{path.name} CA schema mismatch: missing={expect - got}"
        ca_frames.append(ca)
        for z in ZONES:
            zd = parse_sheet(path, z, ZONE_COLS_ORIG)
            assert set(["Date", "Hr_End"] + ZONE_COLS_ORIG).issubset(set(zd.columns)), \
                f"{path.name}::{z} schema mismatch"
            zd.insert(0, "zone", z)
            zone_frames.append(zd)
        print(f"  parsed {path.name}: CA rows={len(ca)}", flush=True)

    # ---- CA canonical table (defines the hour id space) ---------------------
    ca_all = pd.concat(ca_frames, ignore_index=True)
    ca_all = ca_all.sort_values(["Date", "hr_sort"], kind="stable").reset_index(drop=True)
    ca_all["seq"] = np.arange(len(ca_all))
    ca_all["date"] = pd.to_datetime(ca_all["Date"].dt.date)
    hour_map = {(d.date(), hk): s for d, hk, s in zip(ca_all["Date"], ca_all["hr_sort"], ca_all["seq"])}

    # ---- zone table: attach CA hour ids -------------------------------------
    zone_all = pd.concat(zone_frames, ignore_index=True)
    key = list(zip(zone_all["Date"].dt.date, zone_all["hr_sort"]))
    zone_all["seq"] = [hour_map[k] for k in key]
    zone_all["date"] = pd.to_datetime(zone_all["Date"].dt.date)
    zone_all["zone"] = pd.Categorical(zone_all["zone"], categories=ZONES)
    zone_all = zone_all.sort_values(["zone", "seq"]).reset_index(drop=True)
    # every (zone, seq) pair must be unique; seq is shared across zones by design
    assert zone_all["seq"].notna().all(), "unmapped zone hour"
    assert zone_all.duplicated(subset=["zone", "seq"]).sum() == 0, "dup (zone, seq)"
    assert zone_all["seq"].between(0, len(ca_all) - 1).all(), "seq out of CA range"

    # drop raw helpers that are not needed downstream
    def slim(df: pd.DataFrame) -> pd.DataFrame:
        return df.drop(columns=["Date", "Hr_End", "hr_sort"])

    ca_out = slim(ca_all)
    zone_out = slim(zone_all)
    for df in (ca_out, zone_out):
        df["ts_local"] = pd.to_datetime(df["ts_local"])
        df["clock_hour"] = df["clock_hour"].astype("int16")
        df["dst_dup"] = df["dst_dup"].astype(bool)

    ca_out.to_parquet(OUT / "ca_hourly.parquet", index=False)
    zone_out.to_parquet(OUT / "zone_hourly.parquet", index=False)

    # ---- wide weather per seq x zone ----------------------------------------
    w = zone_all[["seq", "zone", "Dry_Bulb", "Dew_Point"]]
    wet = w.pivot(index="seq", columns="zone")
    wet.columns = [f"{m}_{z}" for m, z in wet.columns]
    weather_wide = ca_all[KEEP_EXTRA].join(wet, on="seq").sort_values("seq").reset_index(drop=True)
    weather_wide.to_parquet(OUT / "zone_weather_wide.parquet", index=False)

    # ---- audit ----------------------------------------------------------------
    def audit(df: pd.DataFrame, tag: str) -> None:
        gsize = df.groupby("date").size()
        audit_rep[tag] = {
            "rows": int(len(df)),
            "date_min": str(df["date"].min().date()),
            "date_max": str(df["date"].max().date()),
            "n_dst_dup_rows": int(df["dst_dup"].sum()),
            "n_duplicate_ts_local": int(df["ts_local"].duplicated().sum()),
            "spring_days_23h": {str(k): int(v) for k, v in gsize.items() if v == 23},
            "fall_days_25h": {str(k): int(v) for k, v in gsize.items() if v == 25},
            "nan_by_numeric_col": {c: int(v) for c, v in df.isna().sum().items() if v > 0},
            "neg_rt_demand": int((df["RT_Demand"] < 0).sum()),
        }

    audit(ca_out, "ca_total")
    for z in ZONES:
        audit(zone_out[zone_out["zone"] == z], f"zone_{z}")
    audit_rep["totals"] = {
        "ca_rows": int(len(ca_out)),
        "zone_rows": int(len(zone_out)),
        "files": [f.name for f in files],
        "ca_rows_by_file": {path.name: int(len(ca_frames[i])) for i, path in enumerate(files)},
        "zone_rows_per_zone": {z: int((zone_all["zone"] == z).sum()) for z in ZONES},
        "weather_wide_nan": {c: int(v) for c, v in weather_wide.isna().sum().items() if v > 0},
    }
    (OUT / "audit_stage1.json").write_text(
        json.dumps(audit_rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    t = audit_rep["totals"]
    print(f"\nCA rows total {t['ca_rows']} | zone rows {t['zone_rows']} | weather_wide_nan={t['weather_wide_nan']}")
    print("by file:", t["ca_rows_by_file"])
    for k, v in audit_rep.items():
        if k in ("files", "totals"):
            continue
        print(f"{k:12s} rows={v['rows']:6d} dup_ts={v['n_duplicate_ts_local']} 02X={v['n_dst_dup_rows']} "
              f"spring23={len(v['spring_days_23h'])} fall25={len(v['fall_days_25h'])} nan={v['nan_by_numeric_col']} "
              f"negRT={v['neg_rt_demand']}")
    print("wrote ca_hourly.parquet | zone_hourly.parquet | zone_weather_wide.parquet | audit_stage1.json")


if __name__ == "__main__":
    main()
