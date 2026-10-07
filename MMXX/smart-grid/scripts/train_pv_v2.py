# -*- coding: utf-8 -*-
"""Train the production-oriented TensorFlow pv_v2 day-ahead model.

The model predicts ISO-NE regional estimated BTM PV in MW for the next 24
hours.  It uses only information available at forecast time: the previous 96
hours of PV and Open-Meteo day-1 forecasts aligned to every input/output hour.
Splits are chronological and scalers are fitted on training rows only.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.preprocessing import StandardScaler


SEEDS = [7, 42, 20260912]
LOOKBACK = 96
HORIZON = 24
BATCH = 256
EPOCHS = 120
ZONES = ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]

WEATHER_COLS = (
    [f"ghi_{zone}" for zone in ZONES]
    + [f"cloud_{zone}" for zone in ZONES]
    + ["temp_mean", "dew_mean"]
)
COMMON_COLS = WEATHER_COLS + [
    "coszen", "sun_up", "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "doy_sin", "doy_cos", "trend_days",
]
PAST_COLS = COMMON_COLS + ["pv_mw_ISONE"]
FUTURE_COLS = COMMON_COLS

_COLAB_DATA = Path("/content/pv_v2_features.parquet")
_DEFAULT_ROOT = Path("/content/pv_v2_output") if _COLAB_DATA.exists() else Path(__file__).resolve().parents[1]
ROOT = Path(os.getenv("PV_V2_ROOT", _DEFAULT_ROOT))
DATA = Path(os.getenv("PV_V2_DATA", _COLAB_DATA if _COLAB_DATA.exists()
                       else ROOT / "data" / "processed" / "pv_v2_features.parquet"))
RUN = Path(os.getenv("PV_V2_RUN", ROOT / "runs" / "pv_v2"))
MODEL_DIR = Path(os.getenv("PV_V2_MODEL_DIR", ROOT / "models"))
RUN.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)


def configure_gpu() -> None:
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    for gpu in tf.config.list_physical_devices("GPU"):
        try:
            tf.config.experimental.set_memory_growth(gpu, True)
        except RuntimeError:
            pass
    print("TensorFlow:", tf.__version__, flush=True)
    print("GPUs:", tf.config.list_physical_devices("GPU"), flush=True)


def residual_tcn(x, filters: int, dilation: int, name: str):
    residual = x
    if int(x.shape[-1]) != filters:
        residual = tf.keras.layers.Conv1D(filters, 1, name=f"{name}_projection")(residual)
    y = tf.keras.layers.Conv1D(
        filters, 3, padding="causal", dilation_rate=dilation,
        activation="swish", name=f"{name}_conv1",
    )(x)
    y = tf.keras.layers.SpatialDropout1D(0.10, name=f"{name}_dropout")(y)
    y = tf.keras.layers.Conv1D(
        filters, 3, padding="causal", dilation_rate=dilation,
        name=f"{name}_conv2",
    )(y)
    return tf.keras.layers.LayerNormalization(name=f"{name}_norm")(residual + y)


def build_model() -> tf.keras.Model:
    past = tf.keras.Input((LOOKBACK, len(PAST_COLS)), name="past_features")
    future = tf.keras.Input((HORIZON, len(FUTURE_COLS)), name="future_features")

    encoded = residual_tcn(past, 64, 1, "tcn1")
    encoded = residual_tcn(encoded, 64, 2, "tcn2")
    encoded = residual_tcn(encoded, 64, 4, "tcn3")
    encoded, state = tf.keras.layers.GRU(
        96, return_sequences=True, return_state=True,
        dropout=0.10, name="history_gru",
    )(encoded)

    query = tf.keras.layers.Dense(96, activation="swish", name="future_embedding")(future)
    cross = tf.keras.layers.MultiHeadAttention(
        num_heads=4, key_dim=24, dropout=0.10, name="history_attention",
    )(query=query, value=encoded, key=encoded)
    query = tf.keras.layers.LayerNormalization(name="attention_norm")(query + cross)
    context = tf.keras.layers.RepeatVector(HORIZON, name="repeat_state")(state)
    decoded = tf.keras.layers.Concatenate(name="decoder_inputs")([query, context])
    decoded = tf.keras.layers.GRU(
        96, return_sequences=True, dropout=0.10, name="decoder_gru",
    )(decoded)
    decoded = tf.keras.layers.Dense(64, activation="swish", name="output_dense")(decoded)
    decoded = tf.keras.layers.Dropout(0.10, name="output_dropout")(decoded)
    output = tf.keras.layers.Dense(1, activation="softplus", name="pv_ratio")(decoded)
    return tf.keras.Model([past, future], output, name="pv_v2_tcn_gru_attention")


def pv_loss(y_true, y_pred):
    """Daylight-weighted Huber plus daily energy and peak-shape penalties."""
    error = y_pred - y_true
    absolute = tf.abs(error)
    delta = tf.constant(0.05, dtype=y_true.dtype)
    huber = tf.where(absolute <= delta, 0.5 * tf.square(error), delta * (absolute - 0.5 * delta))
    weights = 0.25 + 1.75 * tf.clip_by_value(y_true, 0.0, 1.25)
    point_loss = tf.reduce_sum(huber * weights) / tf.maximum(tf.reduce_sum(weights), 1.0)
    energy_loss = tf.reduce_mean(tf.abs(tf.reduce_sum(y_pred, axis=1) - tf.reduce_sum(y_true, axis=1))) / HORIZON
    peak_loss = tf.reduce_mean(tf.abs(tf.reduce_max(y_pred, axis=1) - tf.reduce_max(y_true, axis=1)))
    return point_loss + 0.12 * energy_loss + 0.08 * peak_loss


def scaler_dict(scaler: StandardScaler, columns: list[str]) -> dict:
    return {
        "cols": columns,
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
    }


def metrics(true: np.ndarray, pred: np.ndarray, sun_up: np.ndarray) -> dict:
    error = pred - true
    daylight = (sun_up > 0.5) | (true > 50.0)
    high = true > 500.0
    result = {
        "mae_mw_all": float(np.mean(np.abs(error))),
        "rmse_mw_all": float(np.sqrt(np.mean(np.square(error)))),
        "mae_mw_daylight": float(np.mean(np.abs(error[daylight]))),
        "rmse_mw_daylight": float(np.sqrt(np.mean(np.square(error[daylight])))),
        "wape_daylight_pct": float(100 * np.sum(np.abs(error[daylight])) / np.sum(true[daylight])),
        "mape_gt_500mw_pct": float(100 * np.mean(np.abs(error[high]) / true[high])),
        "mean_energy_error_pct": float(100 * np.mean(
            np.abs(pred.sum(axis=1) - true.sum(axis=1)) / np.maximum(true.sum(axis=1), 1.0)
        )),
        "mean_peak_error_mw": float(np.mean(np.abs(pred.max(axis=1) - true.max(axis=1)))),
        "points": int(true.size),
        "daylight_points": int(daylight.sum()),
        "high_output_points": int(high.sum()),
    }
    return {key: round(value, 4) if isinstance(value, float) else value for key, value in result.items()}


def main() -> None:
    configure_gpu()
    started = time.time()
    df = pd.read_parquet(DATA).sort_values("ts_start").reset_index(drop=True)
    df["ts_start"] = pd.to_datetime(df["ts_start"])
    missing = sorted(set(PAST_COLS + FUTURE_COLS + ["split"]) - set(df.columns))
    if missing:
        raise ValueError(f"pv_v2 dataset is missing columns: {missing}")

    split = df["split"].to_numpy()
    train_rows = split == "train"
    past_scaler = StandardScaler().fit(df.loc[train_rows, PAST_COLS])
    future_scaler = StandardScaler().fit(df.loc[train_rows, FUTURE_COLS])
    target_scale = float(df.loc[train_rows, "pv_mw_ISONE"].quantile(0.999))
    past_matrix = np.nan_to_num(past_scaler.transform(df[PAST_COLS])).astype("float32")
    future_matrix = np.nan_to_num(future_scaler.transform(df[FUTURE_COLS])).astype("float32")
    target = df["pv_mw_ISONE"].to_numpy("float32")
    target_ratio = (target / target_scale).astype("float32")
    sun_up = df["sun_up"].to_numpy("float32")

    back = np.arange(-(LOOKBACK - 1), 1)
    forward = np.arange(1, HORIZON + 1)
    partitions = {}
    absolute_indices = {}
    for name in ("train", "val", "test"):
        origins = np.arange(LOOKBACK - 1, len(df) - HORIZON)
        origins = origins[
            (split[origins] == name)
            & (split[origins + 1] == name)
            & (split[origins + HORIZON] == name)
        ]
        x_past = past_matrix[origins[:, None] + back[None, :]]
        x_future = future_matrix[origins[:, None] + forward[None, :]]
        y = target_ratio[origins[:, None] + forward[None, :]][..., None]
        partitions[name] = (x_past, x_future, y)
        absolute_indices[name] = origins
        print(f"{name}: {len(origins)} origins / {len(origins) * HORIZON} target points", flush=True)

    def dataset(name: str, shuffle: bool = False):
        x_past, x_future, y = partitions[name]
        ds = tf.data.Dataset.from_tensor_slices((
            {"past_features": x_past, "future_features": x_future}, y,
        ))
        if shuffle:
            ds = ds.shuffle(min(len(x_past), 8192), seed=1234, reshuffle_each_iteration=True)
        return ds.batch(BATCH).prefetch(tf.data.AUTOTUNE)

    candidate_results = []
    for seed in SEEDS:
        print(f"\n=== candidate seed {seed} ===", flush=True)
        tf.keras.backend.clear_session()
        tf.keras.utils.set_random_seed(seed)
        model = build_model()
        checkpoint = RUN / f"candidate_seed{seed}.weights.h5"
        model.compile(
            optimizer=tf.keras.optimizers.AdamW(
                learning_rate=4e-4, weight_decay=2e-5, clipnorm=1.0,
            ),
            loss=pv_loss,
            metrics=[tf.keras.metrics.MeanAbsoluteError(name="mae_ratio")],
        )
        callbacks = [
            tf.keras.callbacks.ModelCheckpoint(
                checkpoint, monitor="val_loss", mode="min",
                save_best_only=True, save_weights_only=True,
            ),
            tf.keras.callbacks.ReduceLROnPlateau(
                monitor="val_loss", factor=0.5, patience=7, min_lr=1e-5, verbose=1,
            ),
            tf.keras.callbacks.EarlyStopping(
                monitor="val_loss", mode="min", patience=16,
                restore_best_weights=True, verbose=1,
            ),
            tf.keras.callbacks.CSVLogger(RUN / f"train_seed{seed}.csv"),
            tf.keras.callbacks.TerminateOnNaN(),
        ]
        history = model.fit(
            dataset("train", shuffle=True), validation_data=dataset("val"),
            epochs=EPOCHS, callbacks=callbacks, verbose=2,
        )
        best_val = float(np.min(history.history["val_loss"]))
        candidate_results.append({
            "seed": seed,
            "best_val_loss": best_val,
            "epochs": len(history.history["loss"]),
            "checkpoint": str(checkpoint),
        })
        print(f"seed {seed}: best val_loss={best_val:.7f}", flush=True)

    best = min(candidate_results, key=lambda item: item["best_val_loss"])
    model = build_model()
    model.load_weights(best["checkpoint"])
    final_weights = MODEL_DIR / "pv_v2_best.weights.h5"
    model.save_weights(final_weights)
    print(f"selected seed {best['seed']} -> {final_weights}", flush=True)

    evaluations = {}
    predictions = {}
    for name in ("val", "test"):
        x_past, x_future, _ = partitions[name]
        origin = absolute_indices[name]
        raw = model.predict([x_past, x_future], batch_size=BATCH, verbose=0)[..., 0]
        pred = np.maximum(raw * target_scale, 0.0)
        target_idx = origin[:, None] + forward[None, :]
        true = target[target_idx]
        light = sun_up[target_idx]
        # Physical validity only: no smoothing, interpolation, or capacity scaling.
        pred = np.where(light > 0.5, pred, 0.0)
        evaluations[name] = metrics(true, pred, light)
        predictions[name] = (true, pred, target_idx)
        print(name, json.dumps(evaluations[name], indent=2), flush=True)

    true, _, target_idx = predictions["test"]
    naive = target[target_idx - 24]
    light = sun_up[target_idx]
    evaluations["naive24_test"] = metrics(true, naive, light)
    print("naive24_test", json.dumps(evaluations["naive24_test"], indent=2), flush=True)

    metadata = {
        "model_name": "pv_v2",
        "framework": "TensorFlow/Keras",
        "architecture": "causal TCN + GRU encoder + cross-attention + GRU decoder",
        "lookback": LOOKBACK,
        "horizon": HORIZON,
        "past_features": PAST_COLS,
        "future_features": FUTURE_COLS,
        "target": "ISO-NE estimated BTM PV MW",
        "target_scale_mw": target_scale,
        "selected_seed": best["seed"],
        "candidate_results": candidate_results,
        "scalers": {
            "past": scaler_dict(past_scaler, PAST_COLS),
            "future": scaler_dict(future_scaler, FUTURE_COLS),
        },
        "splits": {
            "train": ["2025-02-01", "2026-06-30"],
            "validation": ["2026-07-01", "2026-08-15"],
            "test": ["2026-08-16", "2026-09-10"],
        },
        "metrics": evaluations,
        "parameters": int(model.count_params()),
        "postprocessing": "set output to zero only when sun_up == 0; no smoothing or capacity multiplier",
        "elapsed_minutes": round((time.time() - started) / 60, 2),
    }
    (RUN / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2), flush=True)
    print("TRAINING_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
