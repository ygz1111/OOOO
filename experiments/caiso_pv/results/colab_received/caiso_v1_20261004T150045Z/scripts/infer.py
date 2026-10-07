"""Infer 24 signed CAISO OASIS Solar Actual Generation MW values from raw features."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import tensorflow as tf

try:
    from .evaluate import inverse_target
except ImportError:
    from evaluate import inverse_target

ROOT = Path(__file__).resolve().parents[1]


def _transform(values: np.ndarray, scaler: dict) -> np.ndarray:
    if scaler.get("kind") != "standard" or scaler.get("fitted_partition") != "train":
        raise ValueError("Only the saved Train-fitted scaler may transform inference inputs")
    mean, scale = np.asarray(scaler["mean"], float), np.asarray(scaler["scale"], float)
    if values.shape[-1] != len(mean) or scale.shape != mean.shape or not np.isfinite(mean).all() or not np.isfinite(scale).all() or not np.all(scale > 0):
        raise ValueError("Input features and scaler dimensions disagree")
    return ((values - mean) / scale).astype(np.float32)


def predict(run_dir: Path, past: np.ndarray, future: np.ndarray) -> np.ndarray:
    for device in tf.config.list_physical_devices("GPU"):
        if not tf.config.experimental.get_memory_growth(device):
            tf.config.experimental.set_memory_growth(device, True)
    feature_config = json.loads((run_dir / "feature_config.json").read_text(encoding="utf-8"))
    past, future = np.asarray(past, float), np.asarray(future, float)
    if past.ndim == 2:
        past = past[None, ...]
    if future.ndim == 2:
        future = future[None, ...]
    if past.shape[1:] != (96, len(feature_config["past_features"])) or future.shape != (len(past), 24, len(feature_config["future_features"])):
        raise ValueError("Raw inference input must be [batch,96,Fpast] + [batch,24,Ffuture] in the saved feature order")
    if not np.isfinite(past).all() or not np.isfinite(future).all():
        raise ValueError("Missing/nonfinite input cannot be silently imputed at inference")
    scalers = {name: json.loads((run_dir / "scalers" / f"{name}_scaler.json").read_text(encoding="utf-8"))
               for name in ("past", "future", "target")}
    for name in ("past", "future"):
        if scalers[name].get("feature_names") != feature_config[f"{name}_features"]:
            raise ValueError(f"Saved {name} scaler feature order disagrees with Feature Config")
    if scalers["target"].get("kind") != "standard" or scalers["target"].get("feature_names") != ["solar_actual_mw"]:
        raise ValueError("Saved target scaler must describe the official Solar MW label")
    model = tf.keras.models.load_model(run_dir / "models" / "final.keras", compile=False)
    standardized = model({"past": _transform(past, scalers["past"]),
                          "future": _transform(future, scalers["future"])}, training=False).numpy()
    result = inverse_target(standardized, scalers["target"])
    if result.shape != (len(past), 24, 1) or not np.isfinite(result).all():
        raise ValueError("Model inference produced invalid output")
    # Solar is an official signed aggregate; do not clip negative/nighttime values.
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--input-npz", type=Path, required=True,
                        help="raw past/future arrays, their ordered feature_names, origin_ts, past_ts, target_ts and future_available_upper_bound_ts")
    parser.add_argument("--output-csv", type=Path, required=True)
    args = parser.parse_args()
    if not args.run_dir.resolve().is_relative_to(ROOT) or not args.output_csv.resolve().is_relative_to(ROOT):
        raise ValueError("Inference run and new CSV must remain inside the independent CAISO experiment")
    with np.load(args.input_npz, allow_pickle=False) as inputs:
        feature_config = json.loads((args.run_dir / "feature_config.json").read_text(encoding="utf-8"))
        for kind in ("past", "future"):
            if f"{kind}_feature_names" not in inputs or inputs[f"{kind}_feature_names"].tolist() != feature_config[f"{kind}_features"]:
                raise ValueError(f"Raw {kind} feature names/order must match the saved Feature Config")
        origin = int(inputs["origin_ts"].item())
        if inputs["past_ts"].shape != (96,) or not np.array_equal(inputs["past_ts"], origin + np.arange(-96, 0) * 3600):
            raise ValueError("Raw past features must cover [origin-96h,origin) physical hours")
        if inputs["future_available_upper_bound_ts"].shape != (24,) or not np.all(inputs["future_available_upper_bound_ts"] <= origin):
            raise ValueError("Future forecast availability must precede the supplied origin")
        result = predict(args.run_dir, inputs["past"], inputs["future"])
        timestamps = inputs["target_ts"]
    if timestamps.shape != (24,) or not np.array_equal(timestamps, origin + np.arange(24) * 3600) or len(result) != 1:
        raise ValueError("CSV inference expects one origin with 24 consecutive physical-hour timestamps")
    with args.output_csv.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp", "timestamp_utc", "predicted_mw", "forecast_horizon"])
        for horizon, timestamp in enumerate(timestamps):
            utc = datetime.fromtimestamp(int(timestamp), timezone.utc)
            writer.writerow([utc.astimezone(ZoneInfo("America/Los_Angeles")).isoformat(), utc.isoformat(),
                             float(result[0, horizon, 0]), horizon + 1])


if __name__ == "__main__":
    main()
