# -*- coding: utf-8 -*-
"""
smart-grid / scripts/stage_pv_build.py
=======================================
Build the PV forecasting dataset:
  BTM PV (raw MW + normalized 0..1, ISONE + 8 zones, 2014..2026-04)
+ ERA5 hourly radiation/cloud/temp per zone (2017..2026, open-meteo archive)
+ SMD CA weather / demand (2017..2026) for context
+ solar geometry features (cos zenith at zone coordinates)
-> data/processed/pv_features.parquet  (one row per aligned hour, 2017-01..2026-04-30)
Splits mirror load task: train < 2025-11 | val 2025-11..12 | test 2026-01..04.
Hour convention: ts_start = start of the hour (SMD hour-ending H -> ts_start H-1).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
ERA = RAW / "era5_radiation"
BTM = RAW / "btm_pv_data.xlsx"

ZONES = ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]
COORDS = {"ME": (43.66, -70.26), "NH": (43.21, -71.54), "VT": (44.47, -73.15),
          "CT": (41.94, -72.68), "RI": (41.72, -71.43), "SEMA": (41.72, -71.43),
          "WCMA": (42.27, -71.87), "NEMA": (42.36, -71.06)}


def solar_coszen(dt: pd.DatetimeIndex, lat: float, lon: float) -> pd.Series:
    """cos(zenith) for America/New_York local hour-start timestamps."""
    import numpy as np
    dt = dt.tz_localize(None)
    jday = dt.dayofyear
    lst_h = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
    gamma = 2 * np.pi * (jday - 1 + (lst_h - 12) / 24.0) / 365.0
    decl = (0.006918 - 0.399912 * np.cos(gamma) + 0.070257 * np.sin(gamma)
            - 0.006758 * np.cos(2 * gamma) + 0.000907 * np.sin(2 * gamma)
            - 0.002697 * np.cos(3 * gamma) + 0.00148 * np.sin(3 * gamma))
    equation_of_time = 229.18 * (
        0.000075 + 0.001868 * np.cos(gamma) - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2 * gamma) - 0.040849 * np.sin(2 * gamma)
    )

    def is_dst_day(value) -> bool:
        value = pd.Timestamp(value)
        march_8 = pd.Timestamp(year=value.year, month=3, day=8)
        dst_start = march_8 + pd.Timedelta(days=(6 - march_8.dayofweek) % 7)
        november_1 = pd.Timestamp(year=value.year, month=11, day=1)
        dst_end = november_1 + pd.Timedelta(days=(6 - november_1.dayofweek) % 7)
        return dst_start.date() <= value.date() < dst_end.date()

    dst_hours = np.fromiter(
        (1.0 if is_dst_day(value) else 0.0 for value in dt.date),
        dtype=float,
        count=len(dt),
    )
    standard_minutes = (lst_h.to_numpy(dtype=float) - dst_hours) * 60.0
    true_solar_minutes = standard_minutes + equation_of_time.to_numpy(dtype=float) \
        + 4.0 * (lon - (-75.0))
    hra = np.radians(true_solar_minutes / 4.0 - 180.0)
    lat_r = np.radians(lat)
    cosz = np.sin(lat_r) * np.sin(decl) + np.cos(lat_r) * np.cos(decl) * np.cos(hra)
    return pd.Series(np.clip(cosz, 0.0, None), index=dt).astype("float32")


def load_era5(zone: str) -> pd.DataFrame:
    frames = []
    for y in range(2017, 2027):
        f = ERA / f"{zone}_{y}.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        h = d["hourly"]
        fr = pd.DataFrame({
            "time": h["time"], "ghi": h["shortwave_radiation"],
            "dir": h["direct_radiation"], "dif": h["diffuse_radiation"],
            "cloud": h["cloud_cover"], "temp": h["temperature_2m"], "dp": h["dew_point_2m"]})
        frames.append(fr)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df["ts_start"] = pd.to_datetime(df["time"])
    return df.set_index("ts_start").sort_index()


def main() -> None:
    # ---- BTM PV ---------------------------------------------------------
    raw = pd.read_excel(BTM, sheet_name="BTM PV")
    norm = pd.read_excel(BTM, sheet_name="Normalized BTM PV")
    for df in (raw, norm):
        df["ts_start"] = pd.to_datetime(
            dict(year=df["Year"], month=df["Month"], day=df["Day"])) \
            + pd.to_timedelta(df["HourEnding"].astype(int) - 1, unit="h")
    pv = pd.DataFrame({"ts_start": raw["ts_start"]})
    pv["date"] = raw["ts_start"].dt.date
    for c in ["ISONE"] + ZONES:
        pv[f"pv_mw_{c}"] = raw[c].astype("float32")
        pv[f"pv_n_{c}"] = norm[c].astype("float32")
    pv = pv.set_index("ts_start").sort_index()

    # ---- ERA5 + geometry ------------------------------------------------
    era_frames = []
    for z in ZONES:
        e = load_era5(z)
        if e is None:
            raise SystemExit(f"missing era5 for {z}")
        keep = e[["ghi", "cloud", "temp"]].rename(columns={
            "ghi": f"ghi_{z}", "cloud": f"cloud_{z}", "temp": f"temp_{z}"})
        era_frames.append(keep)
    era = pd.concat(era_frames, axis=1, join="outer")
    for c in era.columns:
        era[c] = era[c].ffill().bfill()
    era["ghi_mean"] = era[[f"ghi_{z}" for z in ZONES]].mean(axis=1)
    era["cloud_mean"] = era[[f"cloud_{z}" for z in ZONES]].mean(axis=1)

    # geometry (mean across zones for ISONE solar elevation)
    latm = float(np.mean([COORDS[z][0] for z in ZONES]))
    lonm = float(np.mean([COORDS[z][1] for z in ZONES]))
    geom = pd.DataFrame({"coszen": solar_coszen(era.index, latm, lonm)})
    geom["sun_up"] = (geom["coszen"] > 0.02).astype("int8")

    # ---- SMD context (CA) ----------------------------------------------
    ca = pd.read_parquet(PROC / "ca_hourly.parquet").sort_values("seq").reset_index(drop=True)
    ca["ts_start"] = pd.to_datetime(ca["ts_local"]) - pd.Timedelta(hours=1)
    ctx = ca.set_index("ts_start")[["Dry_Bulb", "Dew_Point", "RT_Demand", "DA_Demand"]].rename(
        columns={"Dry_Bulb": "db_ca", "Dew_Point": "dp_ca",
                 "RT_Demand": "rt_demand", "DA_Demand": "da_demand"})
    ctx = ctx[~ctx.index.duplicated(keep="first")]

    # ---- merge -----------------------------------------------------------
    base = era.join(geom, how="left")
    df = base.join(pv, how="inner").join(ctx, how="left")
    df = df[(df.index >= "2017-01-01") & (df.index <= "2026-04-30 23:00")].sort_index()
    df["hour"] = df.index.hour
    df["dow"] = df.index.dayofweek
    df["date"] = df.index.date.astype("datetime64[ns]")
    df = df.dropna(subset=["pv_n_ISONE"])
    assert df.index.is_monotonic_increasing and not df.index.duplicated().any()

    # ---- splits -----------------------------------------------------------
    df["split"] = np.select(
        [df.index < pd.Timestamp("2025-11-01"),
         df.index < pd.Timestamp("2026-01-01")],
        ["train", "val"], default="test")
    df = df.reset_index()
    df.to_parquet(PROC / "pv_features.parquet", index=False)

    print("rows:", len(df), "range:", df["ts_start"].min(), "->", df["ts_start"].max())
    print("by split:", df["split"].value_counts().to_dict())
    print("by year:", df["ts_start"].dt.year.value_counts().sort_index().to_dict())
    nan = {c: int(v) for c, v in df.isna().sum().items() if v > 0 and c != "date"}
    print("NaN cols (head-only expected):", nan)
    print("wrote pv_features.parquet")


if __name__ == "__main__":
    main()
