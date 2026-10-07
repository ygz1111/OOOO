"""Authorized, resumable monthly weather acquisition for this experiment.

Nothing is downloaded until logs/training_authorization.json says approved.
Only explicit ERA5 history and GFS fixed-lead day2 forecasts are supported;
this is not a hidden replacement for a selected single-run dataset.
Free-tier limits: https://open-meteo.com/en/pricing (checked 2026-10-04).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import threading
import time

import numpy as np
import pandas as pd
import requests

if __package__:
    from .weather_data import ENDPOINTS, EXPERIMENT_ROOT, SITES, VARIABLES, normalize_weather, utc_timestamp
else:
    from weather_data import ENDPOINTS, EXPERIMENT_ROOT, SITES, VARIABLES, normalize_weather, utc_timestamp


def require_authorization() -> dict:
    path = EXPERIMENT_ROOT / "logs" / "training_authorization.json"
    if not path.is_file():
        raise PermissionError("Official-label sample confirmation is pending; no bulk weather download is authorized")
    authorization = json.loads(path.read_text(encoding="utf-8-sig"))
    if authorization.get("status") != "approved":
        raise PermissionError("training_authorization.json must explicitly have status approved before bulk download")
    return authorization


def monthly_chunks(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if start >= end or start != start.floor("h") or end != end.floor("h"):
        raise ValueError("Weather range requires UTC whole-hour start < end (end exclusive)")
    result, cursor = [], start
    while cursor < end:
        month_end = (cursor.normalize().replace(day=1) + pd.offsets.MonthBegin(1)).tz_convert("UTC")
        finish = min(month_end, end)
        result.append((cursor, finish))
        cursor = finish
    return result


class RateLimiter:
    def __init__(self, interval_seconds: float = 3.0):
        if interval_seconds < 3:
            raise ValueError("Monthly 9-variable requests must be globally spaced at least three seconds")
        self.interval = interval_seconds
        self.next_time = 0.0
        self.lock = threading.Lock()

    def acquire(self) -> None:
        with self.lock:
            delay = max(0.0, self.next_time - time.monotonic())
            if delay:
                time.sleep(delay)
            self.next_time = time.monotonic() + self.interval


def _immutable_bytes(path: Path, value: bytes) -> None:
    if path.exists():
        if path.read_bytes() != value:
            raise ValueError(f"Refusing to overwrite a different cached artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(value)


def _parameters(site, mode: str, model: str, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    suffix = "_previous_day2" if mode == "previous_day2" else ""
    # Include the next endpoint: radiation t represents [t-1h,t), so an
    # interval ending exactly at end is needed for the last requested hour.
    return {"latitude": site.latitude, "longitude": site.longitude,
            "start_date": start.date().isoformat(), "end_date": end.date().isoformat(),
            "hourly": ",".join(v + suffix for v in VARIABLES), "timezone": "UTC",
            "timeformat": "unixtime", "wind_speed_unit": "ms", "models": model}


def _align(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    axis = pd.date_range(start, end, freq="h", inclusive="left")
    aligned = frame.set_index("interval_start_utc").reindex(axis)
    missing = aligned["interval_end_utc"].isna()
    for column in ("site_id", "source_kind", "model", "source_url", "retrieved_at_utc", "batch_id", "availability_basis",
                   "radiation_time_basis", "instantaneous_time_basis"):
        if column in frame:
            aligned.loc[missing, column] = frame[column].iloc[0]
    aligned["interval_end_utc"] = axis + pd.Timedelta(hours=1)
    aligned["missing_api_hour"] = missing.to_numpy()
    # This availability bound never turns a missing weather value into usable input.
    if frame["source_kind"].eq("forecast_fixed_lead_day2").all():
        aligned["availability_upper_bound_utc"] = axis - pd.Timedelta(hours=41)
    return aligned.rename_axis("interval_start_utc").reset_index()


def fetch_chunk(site, mode: str, model: str, start: pd.Timestamp, end: pd.Timestamp, *, limiter: RateLimiter,
                refresh_incomplete: bool = False, attempts: int = 4, timeout: float = 45,
                session: requests.Session | None = None) -> tuple[pd.DataFrame, dict]:
    """Cache immutable raw bytes/manifests; refresh only when explicitly requested.

    This helper is used by the authorization-gated orchestrator below. Its
    transport is injectable for isolated offline recovery/cache tests.
    """
    require_authorization()
    params = _parameters(site,mode,model,start,end)
    source_url = requests.Request("GET", ENDPOINTS[mode], params=params).prepare().url
    request_id = hashlib.sha256(source_url.encode()).hexdigest()
    cache = EXPERIMENT_ROOT / "data" / "cache" / "weather" / request_id
    pointer = cache / "latest.json"
    manifest, content = None, None
    if pointer.is_file():
        candidate = json.loads(pointer.read_text(encoding="utf-8"))
        raw = cache / f"{candidate['sha256']}.json"
        if raw.is_file() and hashlib.sha256(raw.read_bytes()).hexdigest() == candidate["sha256"]:
            if not refresh_incomplete or candidate.get("missing_cells", 1) == 0:
                manifest, content = candidate, raw.read_bytes()
    if content is None:
        client = session or requests.Session()
        last_error = None
        for attempt in range(attempts):
            limiter.acquire()
            try:
                response = client.get(ENDPOINTS[mode], params=params, timeout=timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = RuntimeError(f"Open-Meteo HTTP {response.status_code}: {response.text[:200]}")
                    if attempt + 1 < attempts:
                        wait = response.headers.get("Retry-After", "")
                        time.sleep(min(60.0, max(2.0, float(wait) if wait.isdigit() else 2.0 ** (attempt+1))))
                        continue
                    raise last_error
                response.raise_for_status()
                payload = response.json()
                content = response.content
                retrieved = pd.Timestamp.now(tz="UTC")
                frame = normalize_weather(payload,site=site,mode=mode,model=model,retrieved_at=retrieved,source_url=response.url)
                aligned = _align(frame,start,end)
                digest = hashlib.sha256(content).hexdigest()
                manifest = {"source_url": response.url, "sha256": digest, "retrieved_at_utc": retrieved.isoformat(),
                    "mode": mode, "model": model, "site_id": site.site_id, "requested_start_utc": start.isoformat(),
                    "requested_end_exclusive_utc": end.isoformat(), "rows": len(aligned),
                    "missing_cells": int(aligned[list(VARIABLES)].isna().sum().sum()),
                    "missing_by_variable": aligned[list(VARIABLES)].isna().sum().to_dict(),
                    "missing_api_hours": int(aligned.missing_api_hour.sum()),
                    "availability_note": "day2 offset + six-hour publication delay assumption; no verified issued_at",
                    "raw_path": str(cache / f"{digest}.json")}
                cache.mkdir(parents=True,exist_ok=True)
                _immutable_bytes(cache / f"{digest}.json", content)
                manifest_bytes = json.dumps(manifest,indent=2).encode()
                metadata_digest = hashlib.sha256(manifest_bytes).hexdigest()
                _immutable_bytes(cache / f"manifest-{metadata_digest}.json", manifest_bytes)
                temporary = cache / f"latest-{threading.get_ident()}.tmp"
                temporary.write_bytes(manifest_bytes)
                temporary.replace(pointer)
                break
            except requests.RequestException as error:
                last_error = error
                if (isinstance(error, requests.HTTPError) and error.response is not None
                    and error.response.status_code < 500 and error.response.status_code != 429):
                    raise
                if attempt + 1 == attempts:
                    raise
                time.sleep(min(60.0,2.0 ** (attempt+1)))
        if content is None:
            raise RuntimeError(f"Weather request exhausted retries: {last_error}")
    payload = json.loads(content)
    frame = normalize_weather(payload,site=site,mode=mode,model=model,retrieved_at=manifest["retrieved_at_utc"],source_url=manifest["source_url"])
    return _align(frame,start,end), manifest


def download_weather(start: pd.Timestamp, end: pd.Timestamp, *, output_id: str, forecast_model: str = "gfs_global",
                     workers: int = 2, refresh_incomplete: bool = False) -> dict:
    authorization = require_authorization()  # Must precede directories, cache writes and requests.
    start, end = utc_timestamp(start), utc_timestamp(end)
    if workers not in (1,2) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}",output_id):
        raise ValueError("Use one or two workers and a simple new output identifier")
    if forecast_model not in ("gfs_global", "gfs_seamless"):
        raise ValueError("Only explicitly selected GFS models are allowed for this day2 acquisition")
    if authorization.get("weather_kind", "forecast_fixed_lead_day2") != "forecast_fixed_lead_day2":
        raise PermissionError("Approved weather kind does not authorize fixed-lead day2 acquisition")
    chunks = monthly_chunks(start,end)
    # At most ~3 weighted calls per one-site month (nine variables, <=32 dates).
    if len(chunks)*len(SITES)*2*3 > 9000:
        raise ValueError("Planned monthly weather volume exceeds this conservative free-tier daily budget")
    output = EXPERIMENT_ROOT / "data" / "processed" / "weather" / output_id
    output.mkdir(parents=True,exist_ok=False)
    limiter, frames, manifests, errors = RateLimiter(), {"reanalysis": [], "previous_day2": []}, [], []
    tasks = [(site,mode,"era5" if mode == "reanalysis" else forecast_model,a,b)
             for mode in frames for site in SITES for a,b in chunks]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_chunk,*task,limiter=limiter,refresh_incomplete=refresh_incomplete): task for task in tasks}
        for future in as_completed(futures):
            site,mode,model,a,b = futures[future]
            try:
                frame,manifest = future.result()
                frames[mode].append(frame); manifests.append(manifest)
            except Exception as error:
                errors.append({"site_id": site.site_id,"mode": mode,"model": model,"start_utc": a.isoformat(),
                               "end_exclusive_utc": b.isoformat(),"error_type": type(error).__name__,"error": str(error)})
            print(json.dumps({"weather_chunks_finished": len(manifests)+len(errors),"weather_chunks_total": len(tasks),"failed": len(errors)}),flush=True)
    for mode,parts in frames.items():
        if parts:
            table = pd.concat(parts,ignore_index=True).sort_values(["interval_start_utc","site_id"])
            if table.duplicated(["interval_start_utc","site_id"]).any():
                raise ValueError("Conflicting weather cache chunks produced duplicate physical site hours")
            table.to_parquet(output / ("history.parquet" if mode == "reanalysis" else "future_day2.parquet"),index=False)
    result = {"start_utc": start.isoformat(),"end_exclusive_utc": end.isoformat(),"forecast_model": forecast_model,
        "future_weather_kind": "forecast_fixed_lead_day2","history_model": "era5","workers": workers,"global_request_interval_seconds": 3,
        "status": "partial" if errors else "downloaded_with_missing_values_preserved","manifests": manifests,"errors": errors,
        "history_note": "ERA5 may lag five days; missing values are retained, not filled",
        "availability_note": "day2 fixed48h offset plus assumed6h release delay, exact run and issuance unknown",
        "output_directory": str(output)}
    (output / "manifest.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorization-gated CAISO weather bulk download; no training")
    parser.add_argument("--start",required=True,help="UTC/offset timestamp, inclusive")
    parser.add_argument("--end",required=True,help="UTC/offset timestamp, exclusive")
    parser.add_argument("--output-id",required=True)
    parser.add_argument("--forecast-model",choices=("gfs_global","gfs_seamless"),default="gfs_global")
    parser.add_argument("--workers",type=int,choices=(1,2),default=2)
    parser.add_argument("--refresh-incomplete",action="store_true")
    args=parser.parse_args()
    result=download_weather(utc_timestamp(args.start),utc_timestamp(args.end),output_id=args.output_id,
        forecast_model=args.forecast_model,workers=args.workers,refresh_incomplete=args.refresh_incomplete)
    print(json.dumps({key:value for key,value in result.items() if key != "manifests"},indent=2))


if __name__ == "__main__":
    main()
