"""Train dedicated TensorFlow load and price models without temporal leakage.

The former tf_v2 model jointly optimized load and price.  This experiment keeps
the same 168h -> 24h forecasting contract but trains two separate networks:

* ``load`` predicts CA real-time demand in MW;
* ``price`` predicts RT-LMP P10/P50/P90 using a signed asinh transform, so
  negative LMP observations are retained rather than clipped to zero.

Data split (by target timestamp, never random):
  train: 2017-01-01 .. 2026-04-30
  val:   2026-05-01 .. 2026-06-30
  test:  2026-07-01 .. 2026-08-01

This script is deliberately an experiment trainer.  It does not replace any
production asset.  Only a model that beats the frozen tf_v2 baseline on the
final test partition should be considered for deployment.
"""
from __future__ import annotations

import gc
import json
import os
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.metrics import r2_score
from sklearn.preprocessing import StandardScaler


SEED = 42
LOOKBACK = 168
HORIZON = 24
# Longest engineered lag is 168h.  Starting here ensures no window contains
# an unfilled lag at the beginning of the historical table.
FIRST_ORIGIN = LOOKBACK * 2 - 1
BATCH = int(os.environ.get("BATCH", "256"))
EPOCHS = int(os.environ.get("EPOCHS", "120"))
PATIENCE = int(os.environ.get("PATIENCE", "16"))
RUN_TAG = os.environ.get("TRAIN_TAG", "tf_split_v1")
PRICE_SCALE = 50.0

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "processed" / "ca_features.parquet"
RUN = ROOT / "runs" / RUN_TAG
MODEL_DIR = ROOT / "models" / RUN_TAG
RUN.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

TRAIN_END = pd.Timestamp("2026-04-30 23:00:00")
VAL_START, VAL_END = pd.Timestamp("2026-05-01 00:00:00"), pd.Timestamp("2026-06-30 23:00:00")
TEST_START, TEST_END = pd.Timestamp("2026-07-01 00:00:00"), pd.Timestamp("2026-08-01 00:00:00")

# All future features are known at forecast issuance time: day-ahead market,
# calendar, weather forecast, or a completed same-clock-yesterday observation.
LOAD_PAST = [
    "RT_Demand", "DA_Demand", "RT_LMP", "DA_LMP", "Dry_Bulb", "Dew_Point",
    "hdd65", "cdd65", "temp_mem", "clock_hour_sin", "clock_hour_cos",
    "dow_sin", "dow_cos", "month_sin", "month_cos", "is_holiday", "is_dst",
    "rt_lag24", "rt_lag168", "rt_prev24_mean", "rt_prev168_mean",
]
LOAD_FUTURE = [
    "DA_Demand", "DA_LMP", "Dry_Bulb", "Dew_Point", "hdd65", "cdd65",
    "temp_mem", "clock_hour_sin", "clock_hour_cos", "dow_sin", "dow_cos",
    "month_sin", "month_cos", "is_holiday", "holiday_shoulder", "is_dst", "rt_yest",
]
PRICE_PAST = LOAD_PAST + [
    "rtlmp_lag1", "rtlmp_lag24", "rtlmp_lag168", "rtlmp_prev24_mean", "da_lmp_lag24",
]
PRICE_FUTURE = LOAD_FUTURE


def setup_runtime() -> None:
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    random.seed(SEED)
    np.random.seed(SEED)
    tf.keras.utils.set_random_seed(SEED)
    for gpu in tf.config.list_physical_devices("GPU"):
        try:
            tf.config.experimental.set_memory_growth(gpu, True)
        except RuntimeError:
            pass


class PinballLoss(tf.keras.losses.Loss):
    """Quantile loss for P10/P50/P90 on signed scaled price values."""

    def __init__(self, name: str = "pinball"):
        super().__init__(name=name)
        self.taus = tf.constant([0.1, 0.5, 0.9], dtype=tf.float32)

    def call(self, y_true, y_pred):
        err = y_true - y_pred
        tau = tf.reshape(self.taus, (1, 1, 3))
        return tf.reduce_mean(tf.maximum(tau * err, (tau - 1.0) * err))


class OrderedQuantiles(tf.keras.layers.Layer):
    """Turn three raw channels into strictly ordered P10/P50/P90 values."""

    def call(self, raw):
        lower = raw[..., 1:2] - tf.nn.softplus(raw[..., 0:1])
        median = raw[..., 1:2]
        upper = raw[..., 1:2] + tf.nn.softplus(raw[..., 2:3])
        return tf.concat([lower, median, upper], axis=-1)


def build_model(n_past: int, n_future: int, task: str) -> tf.keras.Model:
    """Dedicated recurrent encoder-decoder.  Quantile head is monotonic."""
    past = tf.keras.Input((LOOKBACK, n_past), name="in_past")
    future = tf.keras.Input((HORIZON, n_future), name="in_future")

    x = tf.keras.layers.LayerNormalization(name="past_norm")(past)
    x = tf.keras.layers.Bidirectional(
        tf.keras.layers.GRU(112, return_sequences=True, dropout=0.10), name="encoder_bi_gru"
    )(x)
    x = tf.keras.layers.GRU(144, dropout=0.10, name="encoder_gru")(x)
    context = tf.keras.layers.RepeatVector(HORIZON, name="context_repeat")(x)
    f = tf.keras.layers.LayerNormalization(name="future_norm")(future)
    f = tf.keras.layers.Dense(72, activation="swish", name="future_projection")(f)
    x = tf.keras.layers.Concatenate(name="decoder_input")([context, f])
    x = tf.keras.layers.GRU(144, return_sequences=True, dropout=0.10, name="decoder_gru")(x)
    x = tf.keras.layers.Dense(96, activation="swish", name="decoder_dense")(x)

    if task == "load":
        output = tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(1), name="load")(x)
    elif task == "price":
        raw = tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(3), name="price_raw")(x)
        # p10 <= p50 <= p90 by construction; avoids visually invalid fan charts.
        output = OrderedQuantiles(name="price")(raw)
    else:
        raise ValueError(f"Unknown task: {task}")
    return tf.keras.Model([past, future], output, name=f"tf_split_{task}")


def split_label(ts: pd.Series) -> np.ndarray:
    labels = np.full(len(ts), "discard", dtype=object)
    labels[ts <= TRAIN_END] = "train"
    labels[(ts >= VAL_START) & (ts <= VAL_END)] = "val"
    labels[(ts >= TEST_START) & (ts <= TEST_END)] = "test"
    return labels


def load_frame() -> pd.DataFrame:
    df = pd.read_parquet(DATA_PATH).sort_values("seq").reset_index(drop=True).copy()
    df["ts_local"] = pd.to_datetime(df["ts_local"])
    # This lag is only used after its source hour has completed.
    df["rt_yest"] = df["RT_Demand"].shift(24)
    df["price_asinh"] = np.arcsinh(df["RT_LMP"].astype("float64") / PRICE_SCALE)
    df["partition"] = split_label(df["ts_local"])
    needed = set(LOAD_PAST + LOAD_FUTURE + PRICE_PAST + PRICE_FUTURE + ["RT_Demand", "price_asinh"])
    if missing := [c for c in sorted(needed) if c not in df.columns]:
        raise ValueError(f"Feature frame missing columns: {missing}")
    usable = df.iloc[FIRST_ORIGIN - LOOKBACK + 1:]
    if usable[list(needed)].isna().any().any():
        bad = usable[list(needed)].isna().sum()
        raise ValueError(f"Feature frame contains missing values: {bad[bad > 0].to_dict()}")
    return df


def build_windows(
    df: pd.DataFrame, past_cols: list[str], future_cols: list[str], target: str, scaler_p: StandardScaler,
    scaler_f: StandardScaler, scaler_y: StandardScaler, partition: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Windows are selected by all 24 target rows, never by a random row split."""
    p = scaler_p.transform(df[past_cols]).astype("float32")
    f = scaler_f.transform(df[future_cols]).astype("float32")
    y = scaler_y.transform(df[[target]]).astype("float32")[:, 0]
    n = len(df)
    origins = np.arange(FIRST_ORIGIN, n - HORIZON)
    targets = origins[:, None] + np.arange(1, HORIZON + 1)[None, :]
    labels = df["partition"].to_numpy()
    keep = np.all(labels[targets] == partition, axis=1)
    origins = origins[keep]
    targets = targets[keep]
    back = np.arange(-(LOOKBACK - 1), 1)
    xp = p[origins[:, None] + back[None, :]]
    xf = f[targets]
    yy = y[targets][..., None]
    return xp, xf, yy


def metrics_load(y: np.ndarray, pred: np.ndarray) -> dict:
    err = pred - y
    peak = y >= np.quantile(y, 0.75)
    return {
        "MAE_MW": round(float(np.mean(np.abs(err))), 2),
        "RMSE_MW": round(float(np.sqrt(np.mean(err ** 2))), 2),
        "MAPE_pct": round(float(np.mean(np.abs(err) / np.maximum(np.abs(y), 1.0)) * 100), 3),
        "bias_MW": round(float(np.mean(err)), 2),
        "R2": round(float(r2_score(y.ravel(), pred.ravel())), 5),
        "peak_MAE_MW": round(float(np.mean(np.abs(err[peak]))), 2),
    }


def metrics_price(y: np.ndarray, q: np.ndarray) -> dict:
    p10, p50, p90 = q[..., 0], q[..., 1], q[..., 2]
    err = p50 - y
    valid = np.abs(y) >= 1.0
    return {
        "P50_MAE_USD_MWh": round(float(np.mean(np.abs(err))), 3),
        "P50_RMSE_USD_MWh": round(float(np.sqrt(np.mean(err ** 2))), 3),
        "P50_bias_USD_MWh": round(float(np.mean(err)), 3),
        "P50_MAPE_pct_abs_actual_ge_1": round(float(np.mean(np.abs(err[valid]) / np.abs(y[valid])) * 100), 3),
        "P10_P90_coverage": round(float(np.mean((y >= p10) & (y <= p90))), 4),
        "negative_actual_count": int(np.sum(y < 0)),
    }


def train_task(df: pd.DataFrame, task: str) -> dict:
    if task == "load":
        past_cols, future_cols, target = LOAD_PAST, LOAD_FUTURE, "RT_Demand"
        loss = tf.keras.losses.Huber(delta=0.75)
    else:
        past_cols, future_cols, target = PRICE_PAST, PRICE_FUTURE, "price_asinh"
        loss = PinballLoss()

    train_rows = df["partition"] == "train"
    sp = StandardScaler().fit(df.loc[train_rows, past_cols].dropna())
    sf = StandardScaler().fit(df.loc[train_rows, future_cols].dropna())
    sy = StandardScaler().fit(df.loc[train_rows, [target]].dropna())
    datasets = {part: build_windows(df, past_cols, future_cols, target, sp, sf, sy, part) for part in ("train", "val", "test")}
    xp_tr, xf_tr, y_tr = datasets["train"]
    xp_va, xf_va, y_va = datasets["val"]
    xp_te, xf_te, y_te = datasets["test"]
    if min(len(xp_tr), len(xp_va), len(xp_te)) == 0:
        raise RuntimeError(f"{task} has an empty temporal partition")

    model = build_model(len(past_cols), len(future_cols), task)
    model.compile(optimizer=tf.keras.optimizers.AdamW(learning_rate=8e-4, weight_decay=1e-4), loss=loss)
    checkpoint = MODEL_DIR / f"{task}_best.weights.h5"
    callbacks = [
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=PATIENCE, restore_best_weights=True),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", patience=6, factor=0.5, min_lr=1e-5),
        tf.keras.callbacks.ModelCheckpoint(checkpoint, monitor="val_loss", save_best_only=True, save_weights_only=True),
        tf.keras.callbacks.CSVLogger(RUN / f"{task}_train_log.csv"),
        tf.keras.callbacks.TerminateOnNaN(),
    ]
    started = time.time()
    hist = model.fit([xp_tr, xf_tr], y_tr, validation_data=([xp_va, xf_va], y_va), batch_size=BATCH,
                     epochs=EPOCHS, callbacks=callbacks, verbose=2, shuffle=True)
    model.load_weights(checkpoint)
    prediction = model.predict([xp_te, xf_te], batch_size=BATCH, verbose=0)

    raw_target = df[target].to_numpy("float64")
    # Recreate test target indices for inverse-transform/evaluation alignment.
    origins = np.arange(FIRST_ORIGIN, len(df) - HORIZON)
    target_idx = origins[:, None] + np.arange(1, HORIZON + 1)[None, :]
    labels = df["partition"].to_numpy()
    target_idx = target_idx[np.all(labels[target_idx] == "test", axis=1)]
    if task == "load":
        actual = raw_target[target_idx]
        predicted = sy.inverse_transform(prediction.reshape(-1, 1)).reshape(prediction.shape[:-1])
        report = metrics_load(actual, predicted)
    else:
        actual = np.sinh(raw_target[target_idx]) * PRICE_SCALE
        scaled_q = sy.inverse_transform(prediction.reshape(-1, 3)).reshape(prediction.shape)
        predicted = np.sinh(scaled_q) * PRICE_SCALE
        report = metrics_price(actual, predicted)

    scalers = {"past_cols": past_cols, "future_cols": future_cols, "target": target,
               "price_transform": "asinh(RT_LMP / 50)" if task == "price" else None,
               "sp_mean": sp.mean_.tolist(), "sp_scale": sp.scale_.tolist(),
               "sf_mean": sf.mean_.tolist(), "sf_scale": sf.scale_.tolist(),
               "sy_mean": sy.mean_.tolist(), "sy_scale": sy.scale_.tolist()}
    (MODEL_DIR / f"{task}_scalers.json").write_text(json.dumps(scalers, indent=2), encoding="utf-8")
    result = {"task": task, "epochs": len(hist.history["loss"]), "seconds": round(time.time() - started, 1),
              "windows": {part: int(len(datasets[part][0])) for part in datasets}, "test": report,
              "model_path": str(checkpoint.relative_to(ROOT)), "scaler_path": str((MODEL_DIR / f"{task}_scalers.json").relative_to(ROOT))}
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    del xp_tr, xf_tr, y_tr, xp_va, xf_va, y_va, xp_te, xf_te, y_te, model
    tf.keras.backend.clear_session()
    gc.collect()
    return result


def main() -> None:
    setup_runtime()
    df = load_frame()
    summary = {
        "run_tag": RUN_TAG,
        "data_range": [str(df.ts_local.min()), str(df.ts_local.max())],
        "split": {"train_end": str(TRAIN_END), "val": [str(VAL_START), str(VAL_END)], "test": [str(TEST_START), str(TEST_END)]},
        "gpu": [d.name for d in tf.config.list_physical_devices("GPU")],
        "load": train_task(df, "load"),
        "price": train_task(df, "price"),
    }
    (RUN / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("TRAINING_COMPLETE", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
