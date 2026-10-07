# -*- coding: utf-8 -*-
"""Build the leakage-safe pv_v2 TensorFlow training dataset.

Sources
-------
* ISO-NE five-minute estimated zonal load API for the complete model period.
* Open-Meteo Previous Runs API, using the day-1 forecast that was available
  before each target hour (not retrospective observed weather).

All timestamps are ISO-NE local wall-clock hour starts (America/New_York).
The output is intentionally model-neutral and contains no fitted scalers.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
BTM_EXTENSION = RAW / "pv_v2_btm_actual_2025_2026.parquet"
WEATHER_CACHE = RAW / "pv_v2_day1_weather.parquet"
OUTPUT = PROC / "pv_v2_features.parquet"
AUDIT = PROC / "pv_v2_dataset_audit.json"

START = pd.Timestamp("2025-02-01 00:00")
END = pd.Timestamp(os.getenv("PV_V2_END", "2026-09-10 23:00"))
API_EXTENSION_START = START
ZONES = ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]
ZONE_IDS = tuple(range(4001, 4009))
COORDS = {
    "ME": (43.66, -70.26), "NH": (43.21, -71.54),
    "VT": (44.47, -73.15), "CT": (41.94, -72.68),
    "RI": (41.72, -71.43), "SEMA": (41.72, -71.43),
    "WCMA": (42.27, -71.87), "NEMA": (42.36, -71.06),
}
OPEN_METEO_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
ISO_NE_URL = "https://webservices.iso-ne.com/api/v1.1"


def session(pool_size: int = 8) -> requests.Session:
    client = requests.Session()
    retry = Retry(
        total=5, connect=5, read=5, backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(("GET",)),
    )
    client.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=pool_size))
    return client


def records(value, wanted: str) -> list[dict]:
    """Find a record collection regardless of API wrapper casing."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() == wanted.lower():
                if isinstance(item, list):
                    return item
                return [item] if isinstance(item, dict) else []
        for item in value.values():
            found = records(item, wanted)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = records(item, wanted)
            if found:
                return found
    return []


def local_naive(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("America/New_York").tz_localize(None)
    return ts


def fetch_iso_day(day: date, username: str, password: str) -> list[tuple]:
    client = session(2)
    stamp = day.strftime("%Y%m%d")
    response = client.get(
        f"{ISO_NE_URL}/fiveminuteestimatedzonalload/day/{stamp}",
        auth=(username, password), headers={"Accept": "application/json"},
        timeout=45,
    )
    response.raise_for_status()
    rows = records(response.json(), "five_min_estimated_zonal_load")
    result = []
    for item in rows:
        begin = item.get("interval_begin_date")
        zone = item.get("load_zone_id")
        pv = item.get("estimated_btm_pv_mw")
        if begin is None or zone is None or pv is None:
            continue
        zone = int(zone)
        if zone in ZONE_IDS:
            result.append((local_naive(begin).floor("h"), zone, float(pv)))
    return result


def load_btm_extension() -> pd.DataFrame:
    if BTM_EXTENSION.exists():
        cached = pd.read_parquet(BTM_EXTENSION)
        cached["ts_start"] = pd.to_datetime(cached["ts_start"])
        if cached["ts_start"].min() <= API_EXTENSION_START and cached["ts_start"].max() >= END:
            return cached[cached["ts_start"].between(API_EXTENSION_START, END)]

    load_dotenv(REPO_ROOT / ".env", override=False)
    username = os.getenv("ISO_NE_USERNAME") or os.getenv("ISONE_USERNAME")
    password = os.getenv("ISO_NE_PASSWORD") or os.getenv("ISONE_PASSWORD")
    if not username or not password:
        raise RuntimeError("ISO-NE credentials are missing from the repository .env")

    days = pd.date_range(API_EXTENSION_START.normalize(), END.normalize(), freq="D").date
    raw_rows: list[tuple] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_iso_day, day, username, password): day for day in days}
        done = 0
        for future in as_completed(futures):
            day = futures[future]
            values = future.result()
            if not values:
                raise RuntimeError(f"ISO-NE returned no BTM PV rows for {day}")
            raw_rows.extend(values)
            done += 1
            if done % 20 == 0 or done == len(days):
                print(f"ISO-NE BTM days: {done}/{len(days)}", flush=True)

    raw = pd.DataFrame(raw_rows, columns=["ts_start", "zone", "pv_mw"])
    grouped = raw.groupby(["ts_start", "zone"])
    pv = grouped["pv_mw"].mean().unstack().reindex(columns=ZONE_IDS)
    counts = grouped.size().unstack().reindex(columns=ZONE_IDS)
    complete = pv.notna().all(axis=1) & (counts.min(axis=1) >= 10)
    hourly = pd.DataFrame({"ts_start": pv.index, "pv_mw_ISONE": pv.sum(axis=1)})
    hourly = hourly.loc[complete.to_numpy()].reset_index(drop=True)
    hourly.to_parquet(BTM_EXTENSION, index=False)
    return hourly


def load_targets() -> pd.DataFrame:
    result = load_btm_extension()
    result["pv_mw_ISONE"] = pd.to_numeric(result["pv_mw_ISONE"], errors="coerce")
    return result.groupby("ts_start", as_index=False)["pv_mw_ISONE"].mean().sort_values("ts_start")


def half_year_ranges() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    ranges = []
    cursor = START
    while cursor <= END:
        boundary = pd.Timestamp(cursor.year, 6 if cursor.month <= 6 else 12, 1)
        chunk_end = boundary + pd.offsets.MonthEnd(0) + pd.Timedelta(hours=23)
        chunk_end = min(chunk_end, END)
        ranges.append((cursor, chunk_end))
        cursor = chunk_end.normalize() + pd.Timedelta(days=1)
    return ranges


def fetch_weather_chunk(zone: str, begin: pd.Timestamp, finish: pd.Timestamp) -> pd.DataFrame:
    lat, lon = COORDS[zone]
    response = session(2).get(
        OPEN_METEO_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": begin.strftime("%Y-%m-%d"),
            "end_date": finish.strftime("%Y-%m-%d"),
            "hourly": ",".join((
                "shortwave_radiation_previous_day1",
                "cloud_cover_previous_day1",
                "temperature_2m_previous_day1",
                "dew_point_2m_previous_day1",
            )),
            "timezone": "America/New_York",
        },
        timeout=120,
    )
    response.raise_for_status()
    hourly = response.json()["hourly"]
    frame = pd.DataFrame({
        "ts_start": pd.to_datetime(hourly["time"]),
        f"ghi_{zone}": hourly["shortwave_radiation_previous_day1"],
        f"cloud_{zone}": hourly["cloud_cover_previous_day1"],
        f"temp_{zone}": hourly["temperature_2m_previous_day1"],
        f"dew_{zone}": hourly["dew_point_2m_previous_day1"],
    })
    for column in frame.columns[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame.iloc[:, 1:].notna().mean().min() < 0.95:
        raise RuntimeError(f"Open-Meteo day-1 forecast is incomplete for {zone} {begin.date()}..{finish.date()}")
    return frame


def load_weather() -> pd.DataFrame:
    if WEATHER_CACHE.exists():
        cached = pd.read_parquet(WEATHER_CACHE)
        cached["ts_start"] = pd.to_datetime(cached["ts_start"])
        expected = {f"ghi_{zone}" for zone in ZONES}
        if cached["ts_start"].min() <= START and cached["ts_start"].max() >= END \
                and expected.issubset(cached.columns):
            return cached[cached["ts_start"].between(START, END)]

    tasks = [(zone, begin, finish) for zone in ZONES for begin, finish in half_year_ranges()]
    frames: dict[str, list[pd.DataFrame]] = {zone: [] for zone in ZONES}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(fetch_weather_chunk, zone, begin, finish): (zone, begin)
            for zone, begin, finish in tasks
        }
        done = 0
        for future in as_completed(futures):
            zone, _ = futures[future]
            frames[zone].append(future.result())
            done += 1
            print(f"Open-Meteo forecast chunks: {done}/{len(tasks)}", flush=True)

    merged = None
    for zone in ZONES:
        zone_frame = pd.concat(frames[zone], ignore_index=True)
        zone_frame = zone_frame.groupby("ts_start", as_index=False).mean(numeric_only=True)
        merged = zone_frame if merged is None else merged.merge(zone_frame, on="ts_start", how="outer")
    merged = merged.sort_values("ts_start").reset_index(drop=True)
    merged.to_parquet(WEATHER_CACHE, index=False)
    return merged


def solar_coszen(index: pd.DatetimeIndex) -> np.ndarray:
    """NOAA solar geometry for ISO-NE local wall-clock hour starts."""
    lat = float(np.mean([COORDS[zone][0] for zone in ZONES]))
    lon = float(np.mean([COORDS[zone][1] for zone in ZONES]))
    local = index.tz_localize(None)
    jday = local.dayofyear.to_numpy(dtype=float)
    hour = local.hour.to_numpy(dtype=float) + local.minute.to_numpy(dtype=float) / 60.0
    gamma = 2 * np.pi * (jday - 1 + (hour - 12) / 24.0) / 365.0
    decl = (0.006918 - 0.399912 * np.cos(gamma) + 0.070257 * np.sin(gamma)
            - 0.006758 * np.cos(2 * gamma) + 0.000907 * np.sin(2 * gamma)
            - 0.002697 * np.cos(3 * gamma) + 0.00148 * np.sin(3 * gamma))
    equation = 229.18 * (
        0.000075 + 0.001868 * np.cos(gamma) - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2 * gamma) - 0.040849 * np.sin(2 * gamma)
    )
    localized = local.tz_localize("America/New_York", ambiguous=False, nonexistent="shift_forward")
    utc_offset = np.array([value.utcoffset().total_seconds() / 3600 for value in localized])
    standard_hour = hour - (utc_offset == -4).astype(float)
    solar_minutes = standard_hour * 60 + equation + 4 * (lon - (-75.0))
    hra = np.radians(solar_minutes / 4 - 180)
    lat_r = np.radians(lat)
    return np.clip(
        np.sin(lat_r) * np.sin(decl) + np.cos(lat_r) * np.cos(decl) * np.cos(hra),
        0.0, None,
    )


def main() -> None:
    started = time.time()
    targets = load_targets()
    weather = load_weather()
    index = pd.date_range(START, END, freq="h")
    frame = pd.DataFrame({"ts_start": index}).merge(targets, on="ts_start", how="left")
    frame = frame.merge(weather, on="ts_start", how="left")

    weather_cols = [column for column in frame if column.startswith(("ghi_", "cloud_", "temp_", "dew_"))]
    frame[weather_cols] = frame[weather_cols].interpolate(limit=2).ffill().bfill()
    # Only DST spring-forward can create a single absent local target hour.
    frame["pv_mw_ISONE"] = frame["pv_mw_ISONE"].interpolate(limit=1)
    if frame[["pv_mw_ISONE", *weather_cols]].isna().any().any():
        missing = frame[["pv_mw_ISONE", *weather_cols]].isna().sum()
        raise RuntimeError(f"pv_v2 dataset still contains missing values: {missing[missing > 0].to_dict()}")

    for prefix in ("ghi", "cloud", "temp", "dew"):
        columns = [f"{prefix}_{zone}" for zone in ZONES]
        frame[f"{prefix}_mean"] = frame[columns].mean(axis=1)
        frame[f"{prefix}_std"] = frame[columns].std(axis=1)
    frame["coszen"] = solar_coszen(pd.DatetimeIndex(frame["ts_start"])).astype("float32")
    frame["sun_up"] = (frame["coszen"] > 0.02).astype("int8")
    hour = frame["ts_start"].dt.hour
    dow = frame["ts_start"].dt.dayofweek
    doy = frame["ts_start"].dt.dayofyear
    frame["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    frame["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    frame["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    frame["dow_cos"] = np.cos(2 * np.pi * dow / 7)
    frame["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    frame["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    frame["trend_days"] = (frame["ts_start"] - START).dt.total_seconds() / 86400.0

    frame["split"] = np.select(
        [frame["ts_start"] < pd.Timestamp("2026-07-01"),
         frame["ts_start"] < pd.Timestamp("2026-08-16")],
        ["train", "val"], default="test",
    )
    frame.to_parquet(OUTPUT, index=False)
    audit = {
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "range": [str(frame["ts_start"].min()), str(frame["ts_start"].max())],
        "rows": int(len(frame)),
        "split_rows": {key: int(value) for key, value in frame["split"].value_counts().items()},
        "target": "ISO-NE estimated BTM PV, regional sum, MW",
        "weather": "Open-Meteo Previous Runs API day-1 forecasts",
        "timezone": "America/New_York local wall-clock hour start",
        "target_stats_mw": {
            "max": float(frame["pv_mw_ISONE"].max()),
            "mean": float(frame["pv_mw_ISONE"].mean()),
            "nonzero_hours": int((frame["pv_mw_ISONE"] > 1).sum()),
        },
    }
    AUDIT.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2), flush=True)
    print(f"wrote {OUTPUT} in {(time.time() - started) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
