"""Read-only diagnostics of existing models; never train or replace assets.

Run on the existing feature tables and production model definitions. Price
interval offsets are fitted only to an early validation slice; a later,
non-overlapping validation slice selects candidates before test is inspected.
The overlapping windows and weather provenance do not constitute an online
forecast experiment or an exchangeability guarantee.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]
HORIZON = 24
LEAD_BANDS = {"1-6h": (0, 6), "7-12h": (6, 12), "13-24h": (12, 24)}


def regression_metrics(actual, prediction, mask=None):
    actual, prediction = np.asarray(actual), np.asarray(prediction)
    mask = np.ones(actual.shape, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    y, p = actual[mask], prediction[mask]
    if not len(y):
        return {"points": 0, "MAE": None, "RMSE": None, "bias": None, "WAPE_pct": None}
    e = p - y
    return {"points": int(len(y)), "MAE": float(np.mean(np.abs(e))),
            "RMSE": float(np.sqrt(np.mean(e ** 2))), "bias": float(np.mean(e)),
            "WAPE_pct": float(np.sum(np.abs(e)) / np.sum(np.abs(y)) * 100) if np.sum(np.abs(y)) else None}


def interval_metrics(actual, quantiles, alpha=0.2):
    y, q = np.asarray(actual), np.asarray(quantiles)
    if q.shape != y.shape + (3,) or not np.isfinite(q).all() or not np.isfinite(y).all():
        raise ValueError("Finite aligned actual/P10/P50/P90 arrays are required")
    lo, median, hi = q[..., 0], q[..., 1], q[..., 2]
    if np.any(lo > median) or np.any(median > hi):
        raise ValueError("Quantiles are not ordered")
    width = hi - lo
    score = width + (2 / alpha) * np.maximum(lo - y, 0) + (2 / alpha) * np.maximum(y - hi, 0)
    return {"points": int(y.size), "coverage": float(np.mean((lo <= y) & (y <= hi))),
            "mean_width_USD_MWh": float(np.mean(width)), "interval_score": float(np.mean(score)),
            "P50_MAE_USD_MWh": float(np.mean(np.abs(median - y))),
            "P50_bias_USD_MWh": float(np.mean(median - y)),
            "negative_reference_points": int(np.sum(y < 0))}


def fit_offsets(actual, quantiles, by_lead, alpha=0.2):
    """Nonnegative empirical tail-error quantile; allows widening beyond [0,1]."""
    scores = np.maximum(np.maximum(quantiles[..., 0] - actual, actual - quantiles[..., 2]), 0)
    ranges = LEAD_BANDS if by_lead else {"all": (0, HORIZON)}
    offsets = {}
    for name, (start, end) in ranges.items():
        values = scores[:, start:end].ravel()
        if not len(values) or not np.isfinite(values).all():
            raise ValueError("Calibration requires finite validation errors")
        rank = min(len(values), int(np.ceil((len(values) + 1) * (1 - alpha))))
        offsets[name] = float(np.partition(values, rank - 1)[rank - 1])
    return offsets


def apply_offsets(quantiles, offsets):
    result = np.asarray(quantiles).copy()
    ranges = {"all": (0, HORIZON)} if "all" in offsets else LEAD_BANDS
    for name, (start, end) in ranges.items():
        value = float(offsets[name])
        if not np.isfinite(value) or value < 0:
            raise ValueError("Offset must be finite and nonnegative")
        result[:, start:end, 0] -= value
        result[:, start:end, 2] += value
    return result


def validation_slices(origins, fraction=0.75):
    """24-target embargo prevents calibration/selection sharing reference hours."""
    origins = np.asarray(origins)
    if len(origins) < 100:
        raise ValueError("Not enough validation windows for calibration and selection")
    boundary = int(origins[int(len(origins) * fraction)])
    fit = origins + HORIZON < boundary + 1
    selection = origins >= boundary
    if not np.any(fit) or not np.any(selection):
        raise ValueError("Empty chronological validation slice")
    assert int(np.max(origins[fit]) + HORIZON) < int(np.min(origins[selection]) + 1)
    return fit, selection


def select_calibration(y_val, q_val, origins):
    fit, selection = validation_slices(origins)
    raw = interval_metrics(y_val[selection], q_val[selection])
    candidates = []
    for by_lead in (False, True):
        offsets = fit_offsets(y_val[fit], q_val[fit], by_lead)
        metrics = interval_metrics(y_val[selection], apply_offsets(q_val[selection], offsets))
        eligible = (abs(metrics["coverage"] - 0.8) < abs(raw["coverage"] - 0.8)
                    and metrics["interval_score"] < raw["interval_score"])
        candidates.append({"name": "lead_band_offsets" if by_lead else "global_offset",
                           "offsets_USD_MWh": offsets, "selection_metrics": metrics,
                           "eligible_on_validation": bool(eligible)})
    eligible = [c for c in candidates if c["eligible_on_validation"]]
    selected = min(eligible, key=lambda c: c["selection_metrics"]["interval_score"]) if eligible else None
    return {"fit_windows": int(fit.sum()), "selection_windows": int(selection.sum()),
            "embargoed_windows": int(len(origins) - fit.sum() - selection.sum()),
            "raw_selection": raw, "candidates": candidates,
            "selected_candidate": selected["name"] if selected else None,
            "selected_offsets_USD_MWh": selected["offsets_USD_MWh"] if selected else None,
            "selection_rule": "Both closer to 80% coverage and lower interval score on held-out validation; test not used"}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def standardize(frame, columns, mean, scale):
    scale = np.asarray(scale)
    if np.any(scale <= 0):
        raise ValueError("Invalid saved scaler")
    result = ((frame[columns].to_numpy(dtype="float32") - np.asarray(mean)) / scale).astype("float32")
    return result


def infer(model, past, future, origins, lookback, batch_size):
    """Only each <=32-window batch is expanded in memory; no training dataset."""
    import tensorflow as tf
    run = tf.function(lambda x: model(x, training=False), reduce_retracing=True)
    output = []
    back = np.arange(-(lookback - 1), 1)
    forward = np.arange(1, HORIZON + 1)
    for i in range(0, len(origins), batch_size):
        batch = origins[i:i + batch_size]
        inputs = [past[batch[:, None] + back], future[batch[:, None] + forward]]
        if not all(np.isfinite(x).all() for x in inputs):
            raise ValueError("Nonfinite input; evaluation does not impute missing features")
        output.append(np.asarray(run(inputs)))
        if (i // batch_size + 1) % 20 == 0:
            print(f"inference: {min(i + batch_size, len(origins))}/{len(origins)} windows", flush=True)
    prediction = np.concatenate(output)
    if not np.isfinite(prediction).all():
        raise ValueError("Nonfinite model output")
    return prediction


def manifest(paths):
    result = []
    for path in paths:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        result.append({"path": str(path.relative_to(PROJECT)), "bytes": path.stat().st_size,
                       "sha256": digest.hexdigest()})
    return result


def split_origins(frame, split):
    ts = pd.to_datetime(frame["ts_local"])
    labels = np.full(len(frame), "discard", dtype=object)
    labels[ts <= pd.Timestamp(split["train_end"])] = "train"
    for name in ("val", "test"):
        start, end = map(pd.Timestamp, split[name])
        labels[(ts >= start) & (ts <= end)] = name
    origins = np.arange(335, len(frame) - HORIZON)
    targets = origins[:, None] + np.arange(1, HORIZON + 1)
    return {name: origins[np.all(labels[targets] == name, axis=1)] for name in ("val", "test")}, labels


def evaluate_split(task, output, batch_size):
    assets = PROJECT / "backend/models/tf_assets/tf_split_v1"
    scaler_path, weights = assets / f"{task}_scalers.json", assets / f"{task}_best.weights.h5"
    data = ROOT / "data/processed/ca_features.parquet"
    meta_path = ROOT / "runs/tf_split_v1/metrics.json"
    meta, scaler = json.loads(meta_path.read_text()), json.loads(scaler_path.read_text())
    frame = pd.read_parquet(data).sort_values("seq").reset_index(drop=True)
    frame["rt_yest"] = frame["RT_Demand"].shift(24)
    origins, labels = split_origins(frame, meta["split"])
    if any(len(origins[p]) != meta[task]["windows"][p] for p in origins):
        raise ValueError("Saved split contract/window counts differ from current data")
    definitions = load_module("evaluation_split_models", PROJECT / "backend/models/tensorflow_load/tf_split_models.py")
    past = standardize(frame, scaler["past_cols"], scaler["sp_mean"], scaler["sp_scale"])
    future = standardize(frame, scaler["future_cols"], scaler["sf_mean"], scaler["sf_scale"])
    model = definitions.build_model(len(scaler["past_cols"]), task)
    model.load_weights(str(weights))
    ys, predictions, indices = {}, {}, {}
    for part in ("val", "test"):
        idx = origins[part][:, None] + np.arange(1, HORIZON + 1)
        raw = infer(model, past, future, origins[part], 168, batch_size)
        unscaled = raw * np.asarray(scaler["sy_scale"]) + np.asarray(scaler["sy_mean"])
        predicted = np.sinh(unscaled) * 50.0 if task == "price" else unscaled[..., 0]
        actual = frame["RT_LMP" if task == "price" else "RT_Demand"].to_numpy()[idx]
        ys[part], predictions[part], indices[part] = actual, predicted, idx
        np.savez_compressed(output / f"{task}_{part}.npz", actual=actual, prediction=predicted,
                            origin_seq=frame["seq"].to_numpy()[origins[part]],
                            origin_local=frame["ts_local"].astype(str).to_numpy()[origins[part]],
                            target_seq=frame["seq"].to_numpy()[idx],
                            target_local=frame["ts_local"].astype(str).to_numpy()[idx])
        print(f"{task}/{part}: {len(origins[part])} windows", flush=True)
    report = {"split": meta["split"], "source_manifest": manifest([data, meta_path, scaler_path, weights]),
              "time_definition": "ISO-NE hour-ending; source seq retains DST ordering",
              "weather_scope": "Existing offline features; historical observed weather is not an issuance-time online forecast"}
    if task == "price":
        # Freeze selection before test arrays are passed to the reporting functions.
        calibration = select_calibration(ys["val"], predictions["val"], origins["val"])
        fit, selection = validation_slices(origins["val"])
        for label, mask in (("fit", fit), ("selection", selection)):
            rows = origins["val"][mask]
            calibration[f"{label}_target_local_range"] = [str(frame.ts_local.iloc[rows[0] + 1]), str(frame.ts_local.iloc[rows[-1] + HORIZON])]
        q, y = predictions["test"], ys["test"]
        report.update({"calibration": calibration, "raw_test": interval_metrics(y, q),
                       "test_by_lead": {name: interval_metrics(y[:, a:b], q[:, a:b]) for name, (a, b) in LEAD_BANDS.items()},
                       "production_enabled": False})
        report["candidate_test_diagnostics"] = [{"name": c["name"],
                "eligible_on_validation": c["eligible_on_validation"],
                "test_metrics": interval_metrics(y, apply_offsets(q, c["offsets_USD_MWh"])),
                "use_for_selection": False} for c in calibration["candidates"]]
        offsets = calibration["selected_offsets_USD_MWh"]
        if offsets:
            calibrated = apply_offsets(q, offsets)
            report["selected_candidate_test"] = interval_metrics(y, calibrated)
            report["candidate_test_by_lead"] = {name: interval_metrics(y[:, a:b], calibrated[:, a:b]) for name, (a, b) in LEAD_BANDS.items()}
            np.savez_compressed(output / "price_test_candidate.npz", actual=y, prediction=calibrated)
        else:
            report["selected_candidate_test"] = None
    else:
        y, p, idx = ys["test"], predictions["test"], indices["test"]
        train_threshold = float(frame.loc[labels == "train", "RT_Demand"].quantile(0.75))
        temperatures = frame["Dry_Bulb"].to_numpy()[idx]
        holiday = frame["is_holiday"].to_numpy()[idx] > 0.5
        groups = {"high_load_train_p75": y >= train_threshold, "hot_ge_86F": temperatures >= 86,
                  "cold_le_32F": temperatures <= 32, "holiday": holiday, "non_holiday": ~holiday}
        report.update({"overall_test": regression_metrics(y, p), "high_load_threshold_MW_fitted_train_only": train_threshold,
                       "groups": {name: regression_metrics(y, p, mask) for name, mask in groups.items()},
                       "legacy_test_p75_peak_MAE_MW": regression_metrics(y, p, y >= np.quantile(y, .75))["MAE"],
                       "test_by_lead": {name: regression_metrics(y[:, a:b], p[:, a:b]) for name, (a, b) in LEAD_BANDS.items()}})
    return report


def pv_metrics(actual, prediction, daylight):
    result = {"all": regression_metrics(actual, prediction),
              "daylight": regression_metrics(actual, prediction, daylight),
              "24h_window_energy_relative_error_pct": float(100 * np.mean(np.abs(prediction.sum(axis=1) - actual.sum(axis=1)) / np.maximum(actual.sum(axis=1), 1))),
              "24h_window_peak_abs_error_MW": float(np.mean(np.abs(prediction.max(axis=1) - actual.max(axis=1)))),
              "24h_window_peak_time_abs_error_hours": float(np.mean(np.abs(prediction.argmax(axis=1) - actual.argmax(axis=1))))}
    return result


def evaluate_pv(output, batch_size):
    assets = PROJECT / "backend/models/tf_assets/pv_v2"
    meta_path, weights = assets / "metadata.json", assets / "pv_v2_best.weights.h5"
    data = ROOT / "data/processed/pv_v2_features.parquet"
    meta = json.loads(meta_path.read_text())
    frame = pd.read_parquet(data).sort_values("ts_start").reset_index(drop=True)
    frame["ts_start"] = pd.to_datetime(frame["ts_start"])
    scaler = meta["scalers"]
    past = standardize(frame, scaler["past"]["cols"], scaler["past"]["mean"], scaler["past"]["scale"])
    future = standardize(frame, scaler["future"]["cols"], scaler["future"]["mean"], scaler["future"]["scale"])
    definitions = load_module("evaluation_pv_models", PROJECT / "backend/models/tensorflow_load/tf_pv_v2_models.py")
    model = definitions.load_trained_model(str(weights))
    report = {"source_manifest": manifest([data, meta_path, weights]),
              "reference_kind": "ISO-NE estimated BTM PV, not measured PV truth",
              "weather_scope": "Open-Meteo day-1 forecast feature table; not a fully replayed issuance-specific online record",
              "time_definition": "PV hour-starting; seq used within each 24-hour forecast window", "partitions": {}}
    labels = frame["split"].to_numpy()
    for part in ("val", "test"):
        all_origins = np.arange(95, len(frame) - HORIZON)
        targets = all_origins[:, None] + np.arange(1, HORIZON + 1)
        origins = all_origins[(labels[all_origins] == part) & np.all(labels[targets] == part, axis=1)]
        idx = origins[:, None] + np.arange(1, HORIZON + 1)
        raw = infer(model, past, future, origins, 96, batch_size)[..., 0]
        light = frame["sun_up"].to_numpy()[idx] > .5
        predicted = np.where(light, np.maximum(raw * meta["target_scale_mw"], 0), 0)
        actual = frame["pv_mw_ISONE"].to_numpy()[idx]
        daylight = light | (actual > 50)
        metrics = pv_metrics(actual, predicted, daylight)
        cloud_cols = [c for c in frame if c.startswith("cloud_")]
        cloud = frame[cloud_cols].mean(axis=1).to_numpy()[idx]
        metrics["cloud_groups_daylight"] = {name: regression_metrics(actual, predicted, daylight & mask)
            for name, mask in {"cloud_le_33pct": cloud <= 33, "cloud_33_to_66pct": (cloud > 33) & (cloud <= 66), "cloud_gt_66pct": cloud > 66}.items()}
        metrics["by_lead"] = {name: regression_metrics(actual[:, a:b], predicted[:, a:b], daylight[:, a:b]) for name, (a, b) in LEAD_BANDS.items()}
        # Select only complete local calendar days; skip 23/25-hour DST days.
        ts = frame["ts_start"].to_numpy()[idx]
        hours = pd.to_datetime(ts[:, 0]).hour
        normal_day = (hours == 0) & (ts[:, -1] - ts[:, 0] == np.timedelta64(23, "h"))
        metrics["complete_calendar_day_count"] = int(normal_day.sum())
        metrics["complete_calendar_days"] = pv_metrics(actual[normal_day], predicted[normal_day], daylight[normal_day]) if normal_day.any() else None
        metrics["windows"] = int(len(origins))
        report["partitions"][part] = metrics
        np.savez_compressed(output / f"pv_{part}.npz", actual=actual, prediction=predicted,
                            origin_local=frame["ts_start"].astype(str).to_numpy()[origins],
                            target_local=frame["ts_start"].astype(str).to_numpy()[idx], daylight=daylight)
        print(f"pv/{part}: {len(origins)} windows", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--tasks", nargs="+", choices=["price", "load", "pv"], default=["price", "load", "pv"])
    args = parser.parse_args()
    if not 1 <= args.batch <= 32:
        parser.error("Local inference batch must be between 1 and 32")
    output = args.output or ROOT / "runs" / ("prediction_audit_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    output = output.resolve()
    if not output.is_relative_to((ROOT / "runs").resolve()):
        parser.error("Output must be a new directory under MMXX/smart-grid/runs")
    output.mkdir(parents=True, exist_ok=False)
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    import tensorflow as tf
    tf.keras.utils.set_random_seed(42)
    for gpu in tf.config.list_physical_devices("GPU"):
        tf.config.experimental.set_memory_growth(gpu, True)
    started = time.perf_counter()
    report = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "framework": tf.__version__,
              "visible_gpus": [g.name for g in tf.config.list_physical_devices("GPU")], "batch": args.batch,
              "training_performed": False, "production_assets_modified": False,
              "limitations": ["Overlapping offline 24h windows; not independent online samples", "Frozen test contains only its existing seasonal dates", "No production calibration enabled", "PV reference is an estimate"]}
    for task in args.tasks:
        tf.keras.backend.clear_session()
        report[task] = evaluate_pv(output, args.batch) if task == "pv" else evaluate_split(task, output, args.batch)
        report["elapsed_seconds"] = time.perf_counter() - started
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(output), "seconds": report["elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
