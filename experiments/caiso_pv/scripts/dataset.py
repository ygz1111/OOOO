"""Build leakage-checked 96->24 CAISO datasets without downloading anything.

All computation uses a continuous UTC axis. Calendar partition boundaries
are local Los Angeles midnights (23/25-hour days remain intact). A window is
admitted only if all 24 physical-hour labels belong to the same partition.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

if __package__:
    from .features import FeatureTable, build_weather_features, utc_index, weather_feature_names
    from .weather_data import EXPERIMENT_ROOT, SITE_EVIDENCE, SITES, TIMEZONE
else:
    from features import FeatureTable, build_weather_features, utc_index, weather_feature_names
    from weather_data import EXPERIMENT_ROOT, SITE_EVIDENCE, SITES, TIMEZONE

PAST_HOURS = 96
HORIZON_HOURS = 24
FORECAST_KINDS = ("forecast_single_run", "forecast_fixed_lead_day2")


def validate_labels(labels: pd.DataFrame) -> pd.DataFrame:
    labels = labels.rename(columns={"timestamp": "interval_start_utc"}) if "interval_start_utc" not in labels else labels
    required = {"interval_start_utc", "interval_end_utc", "solar_actual_mw", "source_kind", "source_id", "unit"}
    missing = sorted(required - set(labels.columns))
    if missing:
        raise ValueError(f"Official CAISO hourly labels missing fields: {missing}")
    frame = labels.copy()
    frame["interval_start_utc"] = utc_index(frame["interval_start_utc"])
    frame["interval_end_utc"] = utc_index(frame["interval_end_utc"])
    if frame["interval_start_utc"].duplicated().any():
        raise ValueError("Duplicate CAISO UTC hour; refusing to merge offset-distinct or conflicting records")
    if (frame["interval_start_utc"] != frame["interval_start_utc"].dt.floor("h")).any():
        raise ValueError("CAISO labels must start on whole UTC hours")
    if not (frame["interval_end_utc"] - frame["interval_start_utc"] == pd.Timedelta(hours=1)).all():
        raise ValueError("CAISO labels must cover one physical hour")
    if not frame["source_kind"].eq("actual").all():
        raise ValueError("Only official CAISO Solar Actual labels are eligible")
    if frame["source_id"].nunique(dropna=False) != 1 or frame["source_id"].isna().any():
        raise ValueError("A dataset must use one declared official CAISO label source, never mix OASIS and telemetry")
    if not frame["unit"].eq("MW").all():
        raise ValueError("CAISO actual generation labels must be in MW")
    frame["solar_actual_mw"] = pd.to_numeric(frame["solar_actual_mw"], errors="coerce")
    if "is_complete" not in frame and not {"sample_count", "source_resolution_minutes"}.issubset(frame.columns):
        raise ValueError("Hourly labels require the official parser's completeness qualification")
    frame["eligible"] = np.isfinite(frame["solar_actual_mw"])
    if "is_complete" in frame:
        frame["eligible"] &= frame["is_complete"].eq(True)
    else:
        resolution = pd.to_numeric(frame["source_resolution_minutes"], errors="coerce")
        expected = 60 / resolution
        frame["eligible"] &= resolution.gt(0) & expected.eq(np.floor(expected)) & frame["sample_count"].eq(expected)
    if "qualified_hour" in frame:
        frame["eligible"] &= frame["qualified_hour"].eq(True)
    return frame.sort_values("interval_start_utc").set_index("interval_start_utc")


def calendar_split_info(labels: pd.DataFrame, *, validation_days: int = 30, test_days: int = 60,
                        source_complete_hours: pd.Series | None = None) -> dict:
    if validation_days < 1 or test_days < 1:
        raise ValueError("Validation and test require positive calendar-day ranges")
    local = labels.index.tz_convert(TIMEZONE)
    eligible = labels["eligible"]
    if source_complete_hours is not None:
        eligible = eligible & source_complete_hours.reindex(labels.index, fill_value=False).eq(True)
    complete_days = []
    for local_date in sorted(set(local.date)):
        start = pd.Timestamp(local_date).tz_localize(TIMEZONE)
        end = (pd.Timestamp(local_date) + pd.Timedelta(days=1)).tz_localize(TIMEZONE)
        expected = pd.date_range(start.tz_convert("UTC"), end.tz_convert("UTC"), freq="h", inclusive="left")
        if eligible.reindex(expected, fill_value=False).all():
            complete_days.append(local_date)
    if not complete_days:
        raise ValueError("No complete official local calendar date is available")
    end_local = (pd.Timestamp(complete_days[-1]) + pd.Timedelta(days=1)).tz_localize(TIMEZONE)
    test_start = end_local - pd.DateOffset(days=test_days)
    val_start = test_start - pd.DateOffset(days=validation_days)
    start = (pd.Timestamp(complete_days[0]).tz_localize(TIMEZONE).tz_convert("UTC")
             if source_complete_hours is not None else labels.index.min())
    if val_start.tz_convert("UTC") - start < pd.Timedelta(hours=PAST_HOURS + HORIZON_HOURS):
        raise ValueError("Insufficient earlier training data before the validation/test calendar ranges")
    boundaries = {"train": (start, val_start.tz_convert("UTC")),
                  "val": (val_start.tz_convert("UTC"), test_start.tz_convert("UTC")),
                  "test": (test_start.tz_convert("UTC"), end_local.tz_convert("UTC"))}
    return {"timezone": TIMEZONE, "time_basis": "UTC hour-start; half-open [start,end) physical-hour intervals",
            "latest_complete_local_date": str(complete_days[-1]),
            "first_complete_local_date": str(complete_days[0]),
            "partition_axis_basis": "complete official labels plus all configured weather sites and fields" if source_complete_hours is not None else "complete official label dates",
            "source_axis_start_utc": start.isoformat(), "source_axis_end_exclusive_utc": end_local.tz_convert("UTC").isoformat(),
            "requested_label_axis_start_utc": labels.index.min().isoformat(),
            "requested_label_axis_end_exclusive_utc": (labels.index.max()+pd.Timedelta(hours=1)).isoformat(),
            "internal_missing_hours_policy": "retain the continuous UTC axis; reject affected windows without interpolation",
            "validation_calendar_days": validation_days,
            "test_calendar_days": test_days, "partitions": {
                name: {"start_utc": a.isoformat(), "end_exclusive_utc": b.isoformat(),
                       "start_local": a.tz_convert(TIMEZONE).isoformat(), "end_exclusive_local": b.tz_convert(TIMEZONE).isoformat()}
                for name, (a, b) in boundaries.items()}}


def fit_scaler(values: np.ndarray, feature_names: list[str], *, start: str, end: str) -> dict:
    matrix = values.reshape(-1, values.shape[-1]).astype("float64")
    if len(matrix) == 0 or not np.isfinite(matrix).all():
        raise ValueError("A scaler requires finite training data only")
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale = np.where(scale == 0, 1.0, scale)
    return {"kind": "standard", "feature_names": feature_names, "mean": mean.tolist(), "scale": scale.tolist(),
            "fitted_partition": "train", "fitted_start": start, "fitted_end": end,
            "fitted_values": len(matrix), "fitting_basis": "admitted training-window values; overlapping hours repeated"}


def _source_coverage(complete: pd.Series) -> dict:
    """Describe acquired physical hours without pretending internal gaps vanish."""
    qualified = complete.index[complete.eq(True)]
    return {"requested_start_utc": complete.index.min().isoformat(),
            "requested_end_exclusive_utc": (complete.index.max()+pd.Timedelta(hours=1)).isoformat(),
            "physical_hours": len(complete), "complete_hours": int(complete.eq(True).sum()),
            "missing_or_incomplete_hours": int((~complete.eq(True)).sum()),
            "first_complete_hour_utc": qualified.min().isoformat() if len(qualified) else None,
            "last_complete_hour_utc": qualified.max().isoformat() if len(qualified) else None}


def transform(values: np.ndarray, scaler: dict) -> np.ndarray:
    return ((values - np.asarray(scaler["mean"])) / np.asarray(scaler["scale"])).astype("float32")


def select_future_window(table: FeatureTable, target_times: pd.DatetimeIndex, origin: pd.Timestamp,
                         weather_kind: str, indexed: pd.DataFrame | None = None) -> pd.DataFrame | None:
    if weather_kind not in FORECAST_KINDS:
        raise ValueError("Future input must be single-run or explicitly selected fixed-lead day2 forecast")
    frame = table.frame
    if indexed is None and not frame["source_kind"].eq(weather_kind).all():
        raise ValueError("One future dataset must contain exactly its declared forecast kind; no silent fallback")
    indexed = frame.set_index("interval_start_utc").sort_index() if indexed is None else indexed
    eligible = indexed.loc[target_times[0]:target_times[-1]]
    eligible = eligible[eligible["complete_weather"]].reset_index()
    eligible = eligible[pd.to_datetime(eligible["availability_upper_bound_utc"], utc=True).le(origin)]
    choices = []
    for _, candidate in eligible.groupby(["model", "batch_id"]):
        candidate = candidate.set_index("interval_start_utc").sort_index()
        if candidate.index.has_duplicates or not candidate.index.equals(target_times):
            continue
        if np.isfinite(candidate[list(table.feature_names)].to_numpy()).all():
            choices.append(candidate)
    if not choices:
        return None
    return max(choices, key=lambda item: pd.to_datetime(item["availability_upper_bound_utc"], utc=True).max())


def build_dataset(labels: pd.DataFrame, historical: FeatureTable, future: FeatureTable, *, weather_kind: str,
                  validation_days: int = 30, test_days: int = 60, stride_hours: int = 1) -> tuple[dict, dict, dict]:
    if stride_hours < 1:
        raise ValueError("Window stride must be positive")
    actual = validate_labels(labels)
    if historical.feature_names != future.feature_names:
        raise ValueError("Past and future weather/calendar feature definitions differ")
    history = historical.frame.set_index("interval_start_utc").sort_index()
    if history.index.has_duplicates:
        raise ValueError("Historical inputs need one explicitly selected source per physical hour")
    if not history["source_kind"].isin(["historical_reanalysis", "historical_analysis"]).all():
        raise ValueError("Historical weather must declare its reconstruction/analysis provenance")
    if not future.frame["source_kind"].eq(weather_kind).all() or weather_kind not in FORECAST_KINDS:
        raise ValueError("Future weather observations/stitched analyses or mixed forecast kinds are prohibited")
    if future.frame["model"].nunique(dropna=False) != 1 or future.frame["model"].isna().any():
        raise ValueError("A future dataset must use one explicit forecast model without substitutions")
    names = list(future.feature_names)
    if set(names) - set(weather_feature_names()):
        raise ValueError("Future feature names include undefined or target-derived features; future Solar is prohibited")
    forecast_index = future.frame.set_index("interval_start_utc").sort_index()
    future_finite = np.isfinite(future.frame[names].to_numpy(dtype=float)).all(axis=1)
    future_complete = pd.Series(future.frame["complete_weather"].eq(True).to_numpy() & future_finite,
                                index=pd.DatetimeIndex(future.frame["interval_start_utc"]))
    # Several runs may contain the same valid hour. The boundary only requires
    # a complete source hour; the stricter one-batch and release guard below
    # still determines whether any actual 24-hour window can be admitted.
    future_complete = future_complete.groupby(level=0).any()
    history_complete = history["complete_weather"].eq(True) & np.isfinite(history[names].to_numpy(dtype=float)).all(axis=1)
    common_hours = history_complete.reindex(actual.index, fill_value=False) & future_complete.reindex(actual.index, fill_value=False)
    splits = calendar_split_info(actual, validation_days=validation_days, test_days=test_days,
                                 source_complete_hours=common_hours)
    axis = pd.date_range(actual.index.min(), actual.index.max(), freq="h")
    all_labels = actual.reindex(axis)
    all_history = history.reindex(axis)
    partitions = {}
    skipped = {name: {"missing_labels_or_history": 0, "missing_available_forecast": 0} for name in ("train", "val", "test")}
    for name, boundary in splits["partitions"].items():
        low, high = pd.Timestamp(boundary["start_utc"]), pd.Timestamp(boundary["end_exclusive_utc"])
        items = {key: [] for key in ("X_past", "X_future", "y", "baseline", "cloud_cover", "origin_ts", "target_ts", "forecast_batch", "forecast_available_upper_bound_ts")}
        for i in range(PAST_HOURS, len(axis) - HORIZON_HOURS + 1, stride_hours):
            origin, last = axis[i], axis[i + HORIZON_HOURS - 1]
            if origin < low or last + pd.Timedelta(hours=1) > high:
                continue
            past_labels = all_labels.iloc[i-PAST_HOURS:i]
            target_labels = all_labels.iloc[i:i+HORIZON_HOURS]
            past_weather = all_history.iloc[i-PAST_HOURS:i]
            if (not past_labels["eligible"].eq(True).all() or not target_labels["eligible"].eq(True).all()
                or not past_weather["complete_weather"].eq(True).all()
                or not np.isfinite(past_weather[names].to_numpy(dtype=float)).all()):
                skipped[name]["missing_labels_or_history"] += 1
                continue
            target_times = axis[i:i+HORIZON_HOURS]
            forecast = select_future_window(future, target_times, origin, weather_kind, forecast_index)
            if forecast is None:
                skipped[name]["missing_available_forecast"] += 1
                continue
            items["X_past"].append(np.column_stack([past_labels["solar_actual_mw"].to_numpy(), past_weather[names].to_numpy()]))
            items["X_future"].append(forecast[names].to_numpy())
            items["y"].append(target_labels["solar_actual_mw"].to_numpy()[:, None])
            items["baseline"].append(all_labels.iloc[i-24:i]["solar_actual_mw"].to_numpy()[:, None])
            items["cloud_cover"].append(forecast["cloud_cover__mean"].to_numpy())
            items["origin_ts"].append(int(origin.timestamp()))
            items["target_ts"].append((target_times.as_unit("ns").asi8 // 1_000_000_000).astype("int64"))
            items["forecast_batch"].append(str(forecast["batch_id"].iloc[0]))
            items["forecast_available_upper_bound_ts"].append((pd.DatetimeIndex(forecast["availability_upper_bound_utc"]).as_unit("ns").asi8 // 1_000_000_000).astype("int64"))
        if not items["y"]:
            raise ValueError(f"No admissible {name} windows: {skipped[name]}; obtain complete official labels and availability-qualified forecast weather")
        partitions[name] = {key: np.asarray(value) for key, value in items.items()}
        splits["partitions"][name].update(samples=len(items["y"]), target_points=len(items["y"]) * HORIZON_HOURS,
            first_origin_utc=pd.Timestamp(items["origin_ts"][0], unit="s", tz="UTC").isoformat(),
            last_origin_utc=pd.Timestamp(items["origin_ts"][-1], unit="s", tz="UTC").isoformat(), rejected_windows=skipped[name])
    train = partitions["train"]
    scaler_range = {"start": splits["partitions"]["train"]["start_utc"], "end": splits["partitions"]["train"]["end_exclusive_utc"]}
    scalers = {
        "past_scaler": fit_scaler(train["X_past"], ["solar_actual_mw"] + names, **scaler_range),
        "future_scaler": fit_scaler(train["X_future"], names, **scaler_range),
        "target_scaler": fit_scaler(train["y"], ["solar_actual_mw"], **scaler_range),
    }
    arrays = {}
    for name, part in partitions.items():
        for key, value in part.items():
            arrays[f"{key}_{name}"] = transform(value, scalers[{"X_past": "past_scaler", "X_future": "future_scaler", "y": "target_scaler"}[key]]) if key in ("X_past", "X_future", "y") else value
    positive_train_targets = train["y"][train["y"] > 0]
    effective_origins = {name: {"first_origin_utc": partition["first_origin_utc"], "last_origin_utc": partition["last_origin_utc"]}
                         for name, partition in splits["partitions"].items()}
    feature_config = {"past_hours": PAST_HOURS, "horizon_hours": HORIZON_HOURS,
        "past_features": ["solar_actual_mw"] + names, "future_features": names,
        "timezone": TIMEZONE, "time_basis": splits["time_basis"],
        "origin_definition": "first future interval start; past [origin-96h,origin), targets [origin,origin+24h)",
        "requested_label_axis_start_utc": actual.index.min().isoformat(),
        "requested_label_axis_end_exclusive_utc": (actual.index.max()+pd.Timedelta(hours=1)).isoformat(),
        "actual_source_axis_start_utc": splits["source_axis_start_utc"],
        "actual_source_axis_end_exclusive_utc": splits["source_axis_end_exclusive_utc"],
        "partition_axis_basis": splits["partition_axis_basis"],
        "source_axis_audit": {
            "official_actual_labels": _source_coverage(actual["eligible"]),
            "historical_weather_all_sites_fields": _source_coverage(history_complete.reindex(actual.index, fill_value=False)),
            "forecast_weather_all_sites_fields": _source_coverage(future_complete.reindex(actual.index, fill_value=False)),
            "all_sources_joint": _source_coverage(actual["eligible"] & common_hours),
        },
        "effective_admitted_origins": effective_origins,
        "future_weather_kind": weather_kind, "future_availability_check": "each site's availability upper bound <= origin",
        "future_weather_model": str(future.frame["model"].iloc[0]),
        "future_availability_basis": sorted(set(future.frame["availability_basis"].astype(str))),
        "forecast_batch_note": "one model initialization per window" if weather_kind == "forecast_single_run" else "48h fixed-lead values vary by valid hour; not one issued batch",
        "historical_weather_kind": sorted(set(history["source_kind"].astype(str))),
        "historical_weather_note": "historical reconstruction may be revised after forecast origin; it is not an archived live input snapshot",
        "solar_label_source_id": str(actual["source_id"].iloc[0]),
        "solar_label_availability_verified": False,
        "solar_label_publication_limitation": "OASIS actual reporting may be published on the following day; first publication timestamps are absent. Latest past96 Solar inputs are retrospective actual values, not verified available at forecast origin. This dataset does not establish a fully causal online input vintage.",
        "online_readiness": "not_established_requires_historical_solar_availability_and_live_weather_contract_validation",
        "radiation_alignment": "API time t preceding-hour mean assigned to CAISO [t-1h,t); instantaneous weather at end t",
        "solar_geometry": "pvlib nrel_numpy NREL SPA at UTC interval midpoint; no target-derived future features",
        "sites": [asdict(s) for s in SITES], "site_selection_sources": list(SITE_EVIDENCE),
        "regional_weighting": "equal weather-site mean; no invented generating-capacity weights",
        "baseline": "physical-hour lag24 (not wall-clock same hour on DST transition)",
        "mape_daylight_threshold_mw": max(1.0, float(np.quantile(positive_train_targets, 0.99)) * 0.01) if positive_train_targets.size else 1.0,
        "mape_daylight_threshold_basis": "1% of admitted Train positive actual MW P99, minimum 1MW; no validation/test fitting",
        "scalers": scalers}
    return arrays, feature_config, splits


def save_dataset(arrays: dict, config: dict, splits: dict, output: Path) -> None:
    output = output.resolve()
    allowed = (EXPERIMENT_ROOT / "data" / "processed").resolve()
    if not output.is_relative_to(allowed):
        raise ValueError("New dataset artifacts must stay inside experiments/caiso_pv/data/processed")
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output / "dataset.npz", **arrays)
    for name, scaler in config["scalers"].items():
        (output / f"{name}.json").write_text(json.dumps(scaler, indent=2), encoding="utf-8")
    (output / "feature_config.json").write_text(json.dumps({k: v for k, v in config.items() if k != "scalers"}, indent=2), encoding="utf-8")
    (output / "split_info.json").write_text(json.dumps(splits, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a new CAISO dataset from validated local files, never download")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--historical-weather", type=Path, required=True)
    parser.add_argument("--future-weather", type=Path, required=True)
    parser.add_argument("--weather-kind", choices=FORECAST_KINDS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    labels = pd.read_csv(args.labels)
    history = pd.read_parquet(args.historical_weather)
    future = pd.read_parquet(args.future_weather)
    arrays, config, splits = build_dataset(labels, build_weather_features(history), build_weather_features(future), weather_kind=args.weather_kind)
    config["input_sources"] = [{"path": str(p.resolve()), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in (args.labels, args.historical_weather, args.future_weather)]
    save_dataset(arrays, config, splits, args.output)
    print(json.dumps(splits, indent=2))


if __name__ == "__main__":
    main()
