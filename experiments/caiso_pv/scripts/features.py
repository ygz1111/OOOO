"""CAISO weather/calendar features on continuous UTC physical hours.

Solar geometry uses pvlib's validated NREL SPA (nrel_numpy), evaluated at
the interval midpoint. Calendar cycles use America/Los_Angeles, preserving
both offset-bearing occurrences of the fall-back hour.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

if __package__:
    from .weather_data import SITES, TIMEZONE, VARIABLES, WeatherSite
else:
    from weather_data import SITES, TIMEZONE, VARIABLES, WeatherSite


CALENDAR_FEATURES = ("hour_sin", "hour_cos", "day_of_year_sin", "day_of_year_cos", "dow_sin", "dow_cos")
SOLAR_FEATURES = ("coszen_mean", "solar_elevation_mean", "sun_up_any", "sun_up_fraction")


def utc_index(values) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(values)
    if index.tz is None:
        raise ValueError("Feature timestamps require timezone-aware UTC/offset-bearing values")
    return index.tz_convert("UTC").as_unit("ns")


def calendar_solar_features(times, sites: tuple[WeatherSite, ...] = SITES) -> pd.DataFrame:
    from pvlib.solarposition import get_solarposition
    index = utc_index(times)
    if index.has_duplicates or (index != index.floor("h")).any():
        raise ValueError("Feature axis must contain unique UTC hour starts")
    local = index.tz_convert(TIMEZONE)
    hour = local.hour.to_numpy(dtype=float)
    day = local.dayofyear.to_numpy(dtype=float)
    days_per_year = np.where(local.is_leap_year, 366.0, 365.0)
    frame = pd.DataFrame(index=index)
    for label, values, period in (("hour", hour, 24), ("day_of_year", day - 1, days_per_year),
                                   ("dow", local.dayofweek.to_numpy(dtype=float), 7)):
        frame[f"{label}_sin"] = np.sin(2 * np.pi * values / period)
        frame[f"{label}_cos"] = np.cos(2 * np.pi * values / period)
    elevations, cosines, daylight = [], [], []
    midpoint = index + pd.Timedelta(minutes=30)
    for site in sites:
        position = get_solarposition(midpoint, site.latitude, site.longitude, method="nrel_numpy")
        elevation = position["elevation"].to_numpy(dtype=float)
        elevations.append(elevation)
        cosines.append(np.clip(np.cos(np.radians(position["zenith"].to_numpy())), 0, 1))
        daylight.append(elevation > 0)
    if not sites:
        raise ValueError("At least one solar-resource site is required")
    frame["coszen_mean"] = np.mean(cosines, axis=0)
    frame["solar_elevation_mean"] = np.mean(elevations, axis=0)
    frame["sun_up_any"] = np.any(daylight, axis=0).astype(float)
    frame["sun_up_fraction"] = np.mean(daylight, axis=0)
    return frame.astype("float32")


@dataclass
class FeatureTable:
    frame: pd.DataFrame
    feature_names: tuple[str, ...]


def weather_feature_names(sites: tuple[WeatherSite, ...] = SITES) -> tuple[str, ...]:
    # Means for all requested variables, spatial spread for radiation/cloud,
    # and site radiation/cloud retain geography without an arbitrary capacity weight.
    return (tuple(f"{v}__mean" for v in VARIABLES)
            + ("shortwave_radiation__std", "cloud_cover__std")
            + tuple(f"{v}__{s.site_id}" for v in ("shortwave_radiation", "cloud_cover") for s in sites)
            + CALENDAR_FEATURES + SOLAR_FEATURES)


def build_weather_features(records: pd.DataFrame, sites: tuple[WeatherSite, ...] = SITES) -> FeatureTable:
    required = {"interval_start_utc", "interval_end_utc", "site_id", "source_kind", "model", "batch_id",
                "availability_upper_bound_utc", "availability_basis", *VARIABLES}
    missing = sorted(required - set(records.columns))
    if missing:
        raise ValueError(f"Weather records missing provenance/features: {missing}")
    records = records.copy()
    records["interval_start_utc"] = utc_index(records["interval_start_utc"])
    records["interval_end_utc"] = utc_index(records["interval_end_utc"])
    if not (records["interval_end_utc"] - records["interval_start_utc"] == pd.Timedelta(hours=1)).all():
        raise ValueError("Weather rows must represent one physical UTC hour")
    keys = ["source_kind", "model", "batch_id", "interval_start_utc", "site_id"]
    if records.duplicated(keys).any():
        raise ValueError("Duplicate site-hour within a weather run; no silent averaging")
    wanted = [s.site_id for s in sites]
    if set(records["site_id"]) - set(wanted):
        raise ValueError("Weather records contain a site outside the configured resource locations")
    pieces = []
    geometry = calendar_solar_features(pd.DatetimeIndex(records["interval_start_utc"].unique()).sort_values(), sites)
    for (kind, model, batch), group in records.groupby(["source_kind", "model", "batch_id"], sort=True):
        axis = pd.DatetimeIndex(group["interval_start_utc"].unique()).sort_values()
        out = pd.DataFrame(index=axis)
        complete = pd.Series(True, index=axis)
        for variable in VARIABLES:
            matrix = group.pivot(index="interval_start_utc", columns="site_id", values=variable).reindex(index=axis, columns=wanted)
            complete &= np.isfinite(matrix.to_numpy(dtype=float)).all(axis=1)
            # skipna=False prevents missing stations from turning into a valid mean.
            out[f"{variable}__mean"] = matrix.mean(axis=1, skipna=False)
            if variable in ("shortwave_radiation", "cloud_cover"):
                out[f"{variable}__std"] = matrix.std(axis=1, ddof=0, skipna=False)
                for site in wanted:
                    out[f"{variable}__{site}"] = matrix[site]
        out = out.join(geometry)
        out["complete_weather"] = complete
        out["source_kind"] = kind
        out["model"] = model
        out["batch_id"] = batch
        availability = pd.to_datetime(group["availability_upper_bound_utc"], utc=True)
        availability_frame = pd.DataFrame({"timestamp": group["interval_start_utc"].to_numpy(), "available": availability.to_numpy()})
        out["availability_upper_bound_utc"] = availability_frame.groupby("timestamp")["available"].max().reindex(axis)
        # A forecast with even one unknown site's availability remains unknown.
        if str(kind).startswith("forecast_"):
            known = availability_frame.groupby("timestamp")["available"].count().reindex(axis).eq(len(sites))
            out.loc[~known, "availability_upper_bound_utc"] = pd.NaT
        out["availability_basis"] = ";".join(sorted(set(group["availability_basis"].astype(str))))
        pieces.append(out.rename_axis("interval_start_utc").reset_index())
    if not pieces:
        raise ValueError("No weather records supplied")
    return FeatureTable(pd.concat(pieces, ignore_index=True), weather_feature_names(sites))
