"""Open-Meteo weather provenance and explicitly limited sample acquisition.

Official references checked 2026-10-04:
https://open-meteo.com/en/docs/historical-weather-api
https://open-meteo.com/en/docs/historical-forecast-api
https://open-meteo.com/en/docs/previous-runs-api
https://open-meteo.com/en/docs/single-runs-api
https://open-meteo.com/en/docs/model-updates

Radiation at API timestamp t is the mean over [t-1h,t). Instantaneous
variables retain their endpoint t, rather than being described as hourly means.
Single-run initialization is NOT issuance/publication. A six-hour release
delay is an explicit assumption, not historical publication evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
TIMEZONE = "America/Los_Angeles"
VARIABLES = (
    "temperature_2m", "relative_humidity_2m", "cloud_cover",
    "shortwave_radiation", "direct_radiation", "diffuse_radiation",
    "direct_normal_irradiance", "wind_speed_10m", "surface_pressure",
)
RADIATION = frozenset(VARIABLES[3:7])
SITE_EVIDENCE = (
    "https://www.energy.ca.gov/data-reports/energy-almanac/california-electricity-data",
    "https://cecgis-caenergy.opendata.arcgis.com/documents/1cf3d9dd53e846149c2fc96e9a93c468/about",
    "https://www.energy.ca.gov/sites/default/files/2019-09/2018_Utility-Scale_Solar_Capacity_and_Electrical_Generation-by_County-Map.pdf",
)


@dataclass(frozen=True)
class WeatherSite:
    site_id: str
    latitude: float
    longitude: float
    region: str


# Meteorological proxy locations spanning CEC solar-generation counties.
# These are neither individual generators nor assumed CAISO capacity weights.
# Imperial includes neighboring balancing-authority territory: its weather is
# regional context, not a claim that all county solar is in the CAISO label.
SITES = (
    WeatherSite("kern_west", 35.10, -119.55, "western Kern / southern Central Valley"),
    WeatherSite("fresno_kings", 36.50, -120.30, "Fresno-Kings / Central Valley"),
    WeatherSite("mojave", 34.86, -117.97, "Mojave / Antelope Valley inland desert"),
    WeatherSite("riverside_east", 33.61, -114.70, "eastern Riverside / Colorado desert"),
    WeatherSite("imperial", 32.79, -115.56, "Imperial Valley meteorological context"),
    WeatherSite("san_diego_east", 32.83, -116.75, "eastern San Diego inland/coastal transition"),
    WeatherSite("central_coast", 35.29, -119.99, "San Luis Obispo / California Valley"),
)

ENDPOINTS = {
    "reanalysis": "https://archive-api.open-meteo.com/v1/archive",
    "historical_analysis": "https://historical-forecast-api.open-meteo.com/v1/forecast",
    "previous_day2": "https://previous-runs-api.open-meteo.com/v1/forecast",
    "single_run": "https://single-runs-api.open-meteo.com/v1/forecast",
}


def utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError("A UTC or offset-bearing timestamp is required; naive local times are ambiguous")
    return timestamp.tz_convert("UTC")


def normalize_weather(
    payload: dict, *, site: WeatherSite, mode: str, model: str,
    retrieved_at: Any, source_url: str, run_initialization: Any = None,
    release_delay_hours: float = 6.0, published_at: Any = None,
) -> pd.DataFrame:
    """Return long weather records; retain missing values for rejection downstream.

    `published_at` may only be supplied from independently verified release
    metadata. `retrieved_at` is a present-day download time, not past issuance.
    Fixed day2 records are not falsely assigned an exact run or issued_at.
    """
    if mode not in ENDPOINTS:
        raise ValueError(f"Unknown weather mode: {mode}")
    if release_delay_hours < 6:
        raise ValueError("The assumed global-model release delay must be at least six hours")
    hourly = payload.get("hourly", {})
    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        raise ValueError("Open-Meteo returned no hourly time axis")
    if isinstance(times[0], (int, float)):
        ends = pd.DatetimeIndex(pd.to_datetime(times, unit="s", utc=True))
    else:
        if payload.get("utc_offset_seconds", 0) != 0:
            raise ValueError("Request UTC weather; local naive weather timestamps are not accepted")
        ends = pd.DatetimeIndex(pd.to_datetime(times, utc=True))
    if ends.has_duplicates or not ends.is_monotonic_increasing or (ends != ends.floor("h")).any():
        raise ValueError("Weather timestamps must be unique, increasing UTC hours")
    frame = pd.DataFrame({"interval_start_utc": ends - pd.Timedelta(hours=1), "interval_end_utc": ends})
    units = payload.get("hourly_units", {})
    suffix = "_previous_day2" if mode == "previous_day2" else ""
    expected_units = {"temperature_2m": "°C", "relative_humidity_2m": "%", "cloud_cover": "%",
                      "wind_speed_10m": "m/s", "surface_pressure": "hPa"}
    expected_units.update({name: "W/m²" for name in RADIATION})
    for variable in VARIABLES:
        key = variable + suffix
        values = hourly.get(key)
        if not isinstance(values, list) or len(values) != len(frame):
            raise ValueError(f"Open-Meteo missing or mismatched variable: {key}")
        if units.get(key) != expected_units[variable]:
            raise ValueError(f"Unexpected unit for {key}: {units.get(key)!r}")
        frame[variable] = pd.to_numeric(values, errors="coerce")
    frame["site_id"] = site.site_id
    frame["source_kind"] = {"single_run": "forecast_single_run", "previous_day2": "forecast_fixed_lead_day2",
                            "reanalysis": "historical_reanalysis", "historical_analysis": "historical_analysis"}[mode]
    frame["model"] = model
    frame["source_url"] = source_url
    frame["retrieved_at_utc"] = utc_timestamp(retrieved_at)
    frame["issued_at_utc"] = pd.NaT
    frame["run_initialization_utc"] = pd.NaT
    frame["availability_upper_bound_utc"] = pd.NaT
    frame["availability_basis"] = "retrospective_history_not_online_availability"
    frame["batch_id"] = mode
    if mode == "single_run":
        if run_initialization is None:
            raise ValueError("A single-run record requires its UTC initialization time")
        initialization = utc_timestamp(run_initialization)
        frame["run_initialization_utc"] = initialization
        frame["batch_id"] = f"{model}:{initialization.isoformat()}"
        if published_at is not None:
            published = utc_timestamp(published_at)
            if published < initialization:
                raise ValueError("Publication cannot precede model initialization")
            frame["issued_at_utc"] = published
            frame["availability_upper_bound_utc"] = published
            frame["availability_basis"] = "verified_publication"
        else:
            frame["availability_upper_bound_utc"] = initialization + pd.Timedelta(hours=release_delay_hours)
            frame["availability_basis"] = f"assumed_initialization_plus_{release_delay_hours:g}h"
    elif mode == "previous_day2":
        frame["availability_upper_bound_utc"] = ends - pd.Timedelta(hours=48 - release_delay_hours)
        frame["availability_basis"] = f"fixed_48h_offset_plus_assumed_{release_delay_hours:g}h_release_delay"
    frame["radiation_time_basis"] = "preceding_hour_mean"
    frame["instantaneous_time_basis"] = "interval_end_instant"
    return frame


class OpenMeteoClient:
    """Sample-only client until the official CAISO sample is confirmed.

    A call is limited to one site and at most two UTC dates. There is no bulk
    loop, weather interpolation, model substitution, or hidden paid fallback.
    """
    def __init__(self, timeout: float = 45, session: requests.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()

    def fetch_sample(self, *, site: WeatherSite, start: date, end: date, mode: str,
                     model: str, run_initialization: Any = None) -> tuple[dict, pd.DataFrame, dict]:
        if mode not in ENDPOINTS or not 0 <= (end - start).days <= 1:
            raise ValueError("Weather sample must use a known mode and one or two UTC dates")
        suffix = "_previous_day2" if mode == "previous_day2" else ""
        parameters = {"latitude": site.latitude, "longitude": site.longitude,
                      "start_date": start.isoformat(), "end_date": end.isoformat(),
                      "hourly": ",".join(variable + suffix for variable in VARIABLES),
                      "timezone": "UTC", "timeformat": "unixtime", "wind_speed_unit": "ms", "models": model}
        if mode == "single_run":
            initialization = utc_timestamp(run_initialization)
            parameters["run"] = initialization.strftime("%Y-%m-%dT%H:%M")
            # The running endpoint rejects start_date/end_date for single runs,
            # despite the general docs describing otherwise shared parameters.
            parameters.pop("start_date")
            parameters.pop("end_date")
            parameters["forecast_hours"] = 48
        response = self.session.get(ENDPOINTS[mode], params=parameters, timeout=self.timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            try:
                reason = response.json().get("reason", "unknown upstream error")
            except (ValueError, AttributeError):
                reason = response.text[:240]
            raise RuntimeError(f"Open-Meteo HTTP {response.status_code}: {reason}; source={response.url}") from error
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError(f"Open-Meteo error: {payload.get('reason') if isinstance(payload, dict) else 'unexpected response'}")
        retrieved = pd.Timestamp.now(tz="UTC")
        frame = normalize_weather(payload, site=site, mode=mode, model=model, retrieved_at=retrieved,
                                  source_url=response.url, run_initialization=run_initialization)
        if mode == "single_run":
            begin = pd.Timestamp(start, tz="UTC")
            finish = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
            frame = frame.loc[frame["interval_end_utc"].between(begin, finish, inclusive="left")].reset_index(drop=True)
            if frame.empty:
                raise ValueError("Requested sample dates are outside the first 48 hours of this run")
        manifest = {"source_url": response.url, "retrieved_at_utc": retrieved.isoformat(),
                    "sha256": hashlib.sha256(response.content).hexdigest(), "site": asdict(site),
                    "mode": mode, "model": model, "rows": len(frame),
                    "finite_rows": int(np.isfinite(frame[list(VARIABLES)].to_numpy()).all(axis=1).sum()),
                    "missing_by_variable": frame[list(VARIABLES)].isna().sum().to_dict(),
                    "availability_note": "Six-hour publication delay is an assumption; retrieval is not past issuance",
                    "site_selection_sources": list(SITE_EVIDENCE)}
        return payload, frame, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch one small official Open-Meteo weather sample")
    parser.add_argument("--mode", choices=ENDPOINTS, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--site", choices=[site.site_id for site in SITES], default="kern_west")
    parser.add_argument("--model", required=True)
    parser.add_argument("--run", help="Offset-bearing initialization timestamp, e.g. 2026-05-01T00:00:00Z")
    args = parser.parse_args()
    _, frame, manifest = OpenMeteoClient().fetch_sample(site=next(s for s in SITES if s.site_id == args.site),
        start=args.start, end=args.end or args.start, mode=args.mode, model=args.model, run_initialization=args.run)
    print(json.dumps(manifest, indent=2, default=str))
    print(frame.head(3).to_string(index=False))


if __name__ == "__main__":
    main()
