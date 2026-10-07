# -*- coding: utf-8 -*-
"""Fetch ERA5 hourly solar/cloud/temp from Open-Meteo archive for NE stations (2017..latest)."""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

STATIONS = {  # zone -> representative coordinate (approx, from ISO-NE notes)
    "ME": (43.66, -70.26),
    "NH": (43.21, -71.54),
    "VT": (44.47, -73.15),
    "CT": (41.94, -72.68),
    "RI": (41.72, -71.43),
    "SEMA": (41.72, -71.43),
    "WCMA": (42.27, -71.87),
    "NEMA": (42.36, -71.06),
}
YEARS = list(range(2017, 2027))  # 2017..2026 (2026 partial handled by end date)
VARS = "shortwave_radiation,direct_radiation,diffuse_radiation,cloud_cover,temperature_2m,dew_point_2m"
OUT = Path("/home/wy/ai-projects/smart-grid/data/raw/era5_radiation")
OUT.mkdir(parents=True, exist_ok=True)

BASE = "https://archive-api.open-meteo.com/v1/archive"


def fetch(lat, lon, y):
    end = f"{y}-12-31"
    if y == 2026:          # archive horizon / matches BTM PV end
        end = "2026-04-30"
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "start_date": f"{y}-01-01", "end_date": end,
        "hourly": VARS, "timezone": "America/New_York"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(BASE + "?" + q, timeout=90) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            print("retry", lat, lon, y, attempt, type(e).__name__, e, flush=True)
            time.sleep(2 + 3 * attempt)
    return None


def main():
    done, fail = [], []
    for zone, (lat, lon) in STATIONS.items():
        for y in YEARS:
            fn = OUT / f"{zone}_{y}.json"
            if fn.exists():
                done.append(fn.name)
                continue
            d = fetch(lat, lon, y)
            if d is None:
                fail.append(fn.name)
                continue
            fn.write_text(json.dumps(d), encoding="utf-8")
            done.append(fn.name)
            time.sleep(0.25)
            print("fetched", fn.name, flush=True)
    print("done", len(done), "fail", len(fail))
    if fail:
        print("FAILED:", fail)


if __name__ == "__main__":
    main()
