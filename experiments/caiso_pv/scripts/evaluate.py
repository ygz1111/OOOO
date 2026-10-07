"""One final test evaluation, using identical origins/horizons for every model."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

PACIFIC = ZoneInfo("America/Los_Angeles")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)


def inverse_target(values: np.ndarray, scaler: dict) -> np.ndarray:
    if scaler.get("fitted_partition") != "train":
        raise ValueError("Target scaler must have been fitted on Train only")
    mean, scale = np.asarray(scaler["mean"]), np.asarray(scaler["scale"])
    if mean.shape != (1,) or scale.shape != (1,) or not np.isfinite(mean).all() or not np.isfinite(scale).all() or not np.all(scale > 0):
        raise ValueError("Target scaler must contain one finite positive scale")
    return np.asarray(values, dtype=np.float64) * scale + mean


def daylight_threshold(train_actual: np.ndarray) -> float:
    values = np.asarray(train_actual, dtype=np.float64)
    if not values.size or not np.isfinite(values).all():
        raise ValueError("Train actual Solar MW must be finite; signed nighttime values are retained")
    # Recorded once from Train, never retuned using Validation or Test.
    positive = values[values > 0]
    if not positive.size:
        raise ValueError("Cannot define a daylight threshold without positive Train Solar values")
    return max(1.0, float(np.quantile(positive, 0.99)) * 0.01)


def metrics(actual: np.ndarray, predicted: np.ndarray, threshold_mw: float) -> dict:
    actual, predicted = np.asarray(actual, float).reshape(-1), np.asarray(predicted, float).reshape(-1)
    if actual.shape != predicted.shape or not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Metrics require equal, finite arrays")
    if not actual.size:
        return {"count": 0, "mae_mw": None, "rmse_mw": None, "r2": None,
                "mape_daylight_pct": None, "daylight_count": 0, "bias_mw": None}
    error = predicted - actual
    variance = np.sum((actual - actual.mean()) ** 2)
    daylight = actual > threshold_mw
    return {"count": int(actual.size), "mae_mw": float(np.mean(np.abs(error))),
            "rmse_mw": float(np.sqrt(np.mean(error ** 2))),
            "r2": float(1 - np.sum(error ** 2) / variance) if variance > 1e-12 else None,
            "mape_daylight_pct": float(np.mean(np.abs(error[daylight]) / actual[daylight]) * 100) if daylight.any() else None,
            "daylight_count": int(daylight.sum()), "bias_mw": float(error.mean())}


def grouped_metrics(actual: np.ndarray, predicted: np.ndarray, target_ts: np.ndarray,
                    threshold_mw: float, cloud_cover: np.ndarray | None = None) -> dict:
    if actual.shape != predicted.shape or actual.shape[:2] != target_ts.shape:
        raise ValueError("Target timestamps and predictions must share the same sample/horizon index")
    actual, predicted = actual[..., 0], predicted[..., 0]
    hours = np.array([datetime.fromtimestamp(int(value), timezone.utc).astimezone(PACIFIC).hour
                      for value in target_ts.flat]).reshape(target_ts.shape)
    result = {"overall": metrics(actual, predicted, threshold_mw),
              "horizons": [{"horizon": horizon + 1, **metrics(actual[:, horizon], predicted[:, horizon], threshold_mw)}
                           for horizon in range(actual.shape[1])],
              "local_periods": {}}
    for name, mask in {"morning_06_10": (hours >= 6) & (hours < 10),
                       "midday_10_16": (hours >= 10) & (hours < 16),
                       "evening_16_20": (hours >= 16) & (hours < 20),
                       "night_other": (hours < 6) | (hours >= 20)}.items():
        result["local_periods"][name] = metrics(actual[mask], predicted[mask], threshold_mw)
    if cloud_cover is None:
        result["weather_groups"] = {"status": "unavailable", "reason": "No reliable aligned cloud-cover feature"}
    else:
        cloud_cover = np.asarray(cloud_cover)
        if cloud_cover.shape != target_ts.shape or not np.isfinite(cloud_cover).all():
            raise ValueError("Weather grouping requires finite cloud-cover percentages on the same index")
        changes = np.abs(np.diff(cloud_cover, axis=1, prepend=cloud_cover[:, :1]))
        result["weather_groups"] = {
            "basis": "Aligned future-weather cloud cover; not an observed cloud-category label",
            "clear_le_20pct": metrics(actual[cloud_cover <= 20], predicted[cloud_cover <= 20], threshold_mw),
            "cloudy_ge_80pct": metrics(actual[cloud_cover >= 80], predicted[cloud_cover >= 80], threshold_mw),
            "high_change_ge_25pp_per_hour": metrics(actual[changes >= 25], predicted[changes >= 25], threshold_mw),
        }
    return result


def export_predictions(path: Path, actual: np.ndarray, predicted: np.ndarray,
                       target_ts: np.ndarray, origin_ts: np.ndarray) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp", "timestamp_utc", "forecast_origin_utc", "actual_mw", "predicted_mw", "forecast_horizon"])
        for sample, origin in enumerate(origin_ts):
            origin_iso = datetime.fromtimestamp(int(origin), timezone.utc).isoformat()
            for horizon, timestamp in enumerate(target_ts[sample]):
                utc = datetime.fromtimestamp(int(timestamp), timezone.utc)
                writer.writerow([utc.astimezone(PACIFIC).isoformat(), utc.isoformat(), origin_iso,
                                 float(actual[sample, horizon, 0]), float(predicted[sample, horizon, 0]), horizon + 1])


def evaluate_run(run_dir: Path, dataset_dir: Path, *, batch_size: int = 64) -> dict:
    import tensorflow as tf
    config = read_json(run_dir / "model_config.json")
    scaler = read_json(run_dir / "scalers" / "target_scaler.json")
    threshold = config["daylight_threshold_mw"]
    digest = hashlib.sha256()
    with (dataset_dir / "dataset.npz").open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != config["dataset_sha256"]:
        raise ValueError("Final Test must use the exact frozen dataset used for Train/Validation")
    # Exclusive marker prevents another Test-based tuning/evaluation cycle in this run.
    write_json(run_dir / "test_evaluation_started.json", {"started_at": datetime.now(timezone.utc).isoformat(),
                "selection": "Validation only; Test evaluation exactly once"})
    with np.load(dataset_dir / "dataset.npz", allow_pickle=False) as dataset:
        actual = inverse_target(dataset["y_test"], scaler)
        target_ts, origin_ts = dataset["target_ts_test"], dataset["origin_ts_test"]
        baseline = dataset["baseline_test"]
        cloud_cover = dataset["cloud_cover_test"] if "cloud_cover_test" in dataset else None
        results = {"daylight_threshold_mw": threshold,
                   "target_name": "CAISO OASIS Solar Actual Generation",
                   "selection_protocol": "Lowest Validation MAE selects final model before any Test evaluation",
                   "prediction_policy": "Linear signed Solar MW; no zero-clipping or nighttime zeroing",
                   "baseline_definition": "Solar persistence with lag of 24 physical hours; DST wall-clock hour can differ",
                   "baseline": grouped_metrics(actual, baseline, target_ts, threshold, cloud_cover), "models": {}}
        prediction_paths = {}
        for name in config["models"]:
            model = tf.keras.models.load_model(run_dir / "models" / name / "best.keras", compile=False)
            standardized = model.predict({"past": dataset["X_past_test"], "future": dataset["X_future_test"]},
                                         batch_size=batch_size, verbose=0)
            predicted = inverse_target(standardized, scaler)
            results["models"][name] = grouped_metrics(actual, predicted, target_ts, threshold, cloud_cover)
            path = run_dir / "results" / f"test_predictions_{name}.csv"
            export_predictions(path, actual, predicted, target_ts, origin_ts)
            prediction_paths[name] = path
            if name == config["selected_model"]:
                export_predictions(run_dir / "results" / "test_predictions.csv", actual, predicted, target_ts, origin_ts)
                past_scaler = read_json(run_dir / "scalers" / "past_scaler.json")
                future_scaler = read_json(run_dir / "scalers" / "future_scaler.json")
                past_raw = dataset["X_past_test"][:2].astype(np.float64) * np.asarray(past_scaler["scale"]) + np.asarray(past_scaler["mean"])
                future_raw = dataset["X_future_test"][:2].astype(np.float64) * np.asarray(future_scaler["scale"]) + np.asarray(future_scaler["mean"])
                np.savez(run_dir / "results" / "reload_reference.npz", past=dataset["X_past_test"][:2],
                         future=dataset["X_future_test"][:2], expected=standardized[:2],
                         past_raw=past_raw, future_raw=future_raw, expected_mw=predicted[:2])
                _evaluation_plots(run_dir, actual, predicted, target_ts, results["models"][name])
            del model
            tf.keras.backend.clear_session()
    results["selected_model"] = config["selected_model"]
    write_json(run_dir / "metrics.json", results)
    return results


def _evaluation_plots(run_dir: Path, actual: np.ndarray, predicted: np.ndarray,
                      target_ts: np.ndarray, result: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    figure, axis = plt.subplots(figsize=(12, 4))
    x = [datetime.fromtimestamp(int(value), timezone.utc).astimezone(PACIFIC) for value in target_ts[0]]
    axis.plot(x, actual[0, :, 0], color="#183f65", label="Actual")
    axis.plot(x, predicted[0, :, 0], color="#b85f25", linestyle="--", label="Predicted")
    axis.set(xlabel="Target interval start (America/Los_Angeles)", ylabel="CAISO OASIS Solar Actual Generation (MW)",
             title="First Test forecast origin: all 24 physical hours")
    axis.xaxis.set_major_locator(mdates.HourLocator(interval=4, tz=PACIFIC))
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M %z", tz=PACIFIC))
    figure.autofmt_xdate()
    axis.legend()
    figure.tight_layout()
    figure.savefig(run_dir / "figures" / "actual_vs_predicted.png", dpi=160)
    plt.close(figure)
    figure, axis = plt.subplots(figsize=(9, 4))
    axis.plot(range(1, 25), [point["mae_mw"] for point in result["horizons"]], marker="o")
    axis.set(xlabel="Forecast horizon (physical hours)", ylabel="MAE (MW)", xticks=range(1, 25))
    figure.tight_layout()
    figure.savefig(run_dir / "figures" / "horizon_error.png", dpi=160)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    evaluate_run(args.run_dir, args.dataset_dir, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
