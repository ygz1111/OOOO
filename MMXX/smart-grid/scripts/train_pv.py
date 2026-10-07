# -*- coding: utf-8 -*-
"""
smart-grid / scripts / train_pv.py
==================================
PV forecasting model (ISO-NE behind-the-meter PV, normalized 0..1, ISONE total).
  past 96h: ghi/cloud/temp/geometry/PV history/calendar
  future 24h exog: ERA5 ghi/cloud + solar geometry + calendar (forecast = actual in training)
  heads: 24h normalized PV p50 (MAE). Epochs 100 cosine, best-val weights saved.
Artifacts -> runs/pv_v1/
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

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
for g in tf.config.list_physical_devices("GPU"):
    try:
        tf.config.experimental.set_memory_growth(g, True)
    except Exception:  # noqa
        pass
SEED = int(os.getenv("PV_SEED", "20260911"))
tf.keras.utils.set_random_seed(SEED)

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
RUN = ROOT / "runs" / "pv_v1"
RUN.mkdir(parents=True, exist_ok=True)
CKPT = ROOT / "models" / "pv_v1_best.weights.h5"
TB = ROOT / "runs" / "tensorboard" / "pv_v1"

LOOKBACK = 96
HORIZON = 24
EPOCHS = 100
BATCH = 256

PAST_COLS = ["ghi_mean", "cloud_mean", "temp_mean", "coszen", "sun_up",
             "pv_n_ISONE", "db_ca", "dp_ca",
             "hour_sin", "hour_cos", "dow_sin", "dow_cos"]
FUT_COLS = ["ghi_mean", "cloud_mean", "temp_mean", "coszen", "sun_up",
            "hour_sin", "hour_cos"]


def build_model(n_past, n_fut):
    past = tf.keras.Input(shape=(LOOKBACK, n_past), name="in_past")
    fut = tf.keras.Input(shape=(HORIZON, n_fut), name="in_fut")
    x = tf.keras.layers.GRU(128, return_sequences=False, dropout=0.15, name="enc")(past)
    ctx = tf.keras.layers.RepeatVector(HORIZON)(x)
    d = tf.keras.layers.Concatenate()([ctx, fut])
    d = tf.keras.layers.Dense(96, activation="swish")(d)
    d = tf.keras.layers.Dropout(0.15)(d)
    d = tf.keras.layers.Dense(64, activation="swish")(d)
    out = tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(1, name="pv"))(d)
    return tf.keras.Model(inputs=[past, fut], outputs=out)


def main():
    t0 = time.time()
    df = pd.read_parquet(PROC / "pv_features.parquet").sort_values("ts_start").reset_index(drop=True)
    zt = [f"temp_{z}" for z in ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]]
    df["temp_mean"] = df[zt].mean(axis=1)
    df["hour"] = df["ts_start"].dt.hour
    df["dow"] = df["ts_start"].dt.dayofweek
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["dow_sin"] = np.sin(2 * np.pi * df["dow"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["dow"] / 7)
    split = df["split"].values

    tr_rows = df[df["split"] == "train"]
    sp = StandardScaler().fit(tr_rows[PAST_COLS])
    sf = StandardScaler().fit(tr_rows[FUT_COLS])
    P = np.nan_to_num(sp.transform(df[PAST_COLS])).astype("float32")
    F = np.nan_to_num(sf.transform(df[FUT_COLS])).astype("float32")
    yraw = df["pv_n_ISONE"].astype("float32").values
    ymean, ystd = float(yraw[split == "train"].mean()), float(yraw[split == "train"].std())
    Y = ((yraw - ymean) / (ystd + 1e-6)).astype("float32")
    n = len(df)
    back = np.arange(-(LOOKBACK - 1), 1)
    fwd = np.arange(1, HORIZON + 1)

    def part(part_name):
        idx = np.arange(LOOKBACK, n - HORIZON)
        idx = idx[(split[idx] == part_name) & (split[idx + HORIZON - 1] == part_name)]
        return (P[idx[:, None] + back[None, :]], F[idx[:, None] + fwd[None, :]],
                Y[idx[:, None] + fwd[None, :]][..., None],
                yraw[idx[:, None] + fwd[None, :]])

    Xp_tr, Xf_tr, Ys_tr, _ = part("train")
    Xp_va, Xf_va, Ys_va, yva = part("val")
    Xp_te, Xf_te, Ys_te, yte = part("test")
    print(f"windows train={len(Xp_tr)} val={len(Xp_va)} test={len(Xp_te)}", flush=True)

    def ds(Xp, Xf, Yv, shuffle=False, repeat=False):
        d = tf.data.Dataset.from_tensor_slices(({"in_past": Xp, "in_fut": Xf}, Yv))
        if shuffle:
            d = d.shuffle(8192)
        if repeat:
            d = d.repeat()
        return d.batch(BATCH).prefetch(tf.data.AUTOTUNE)

    model = build_model(len(PAST_COLS), len(FUT_COLS))
    steps = int(np.ceil(len(Xp_tr) / BATCH))
    opt = tf.keras.optimizers.AdamW(learning_rate=3e-4, weight_decay=1e-5,
                                    clipnorm=1.0)
    model.compile(optimizer=opt, loss=tf.keras.losses.MeanAbsoluteError())
    model.summary()
    cbs = [
        tf.keras.callbacks.ModelCheckpoint(str(CKPT), monitor="val_loss", mode="min",
                                           save_best_only=True, save_weights_only=True),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=8,
                                             min_lr=1e-5),
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", mode="min", patience=18,
            restore_best_weights=True,
        ),
        tf.keras.callbacks.CSVLogger(str(RUN / "train_log.csv")),
        tf.keras.callbacks.TensorBoard(log_dir=str(TB)),
        tf.keras.callbacks.TerminateOnNaN(),
    ]
    hist = model.fit(ds(Xp_tr, Xf_tr, Ys_tr, shuffle=True, repeat=True),
                     validation_data=ds(Xp_va, Xf_va, Ys_va),
                     epochs=EPOCHS, steps_per_epoch=steps, callbacks=cbs, verbose=1)
    model.load_weights(str(CKPT))

    def eval(Xp, Xf, Ys, yy, tag):
        p = model.predict([Xp, Xf], batch_size=BATCH, verbose=0)[..., 0]
        pred = p * ystd + ymean
        true = yy
        pred = np.clip(pred, 0, 1)
        mae = float(np.mean(np.abs(true - pred)))
        rmse = float(np.sqrt(np.mean((true - pred) ** 2)))
        day = true > 0.002
        mae_day = float(np.mean(np.abs(true[day] - pred[day]))) if day.any() else None
        rmse_day = float(np.sqrt(np.mean((true[day] - pred[day]) ** 2))) if day.any() else None
        nmae_day = float(mae_day / true[day].mean()) if mae_day is not None else None
        print(f"[{tag}] MAE={mae:.4f} RMSE={rmse:.4f} dayMAE={mae_day:.4f} "
              f"daynMAE={nmae_day:.4f}", flush=True)
        return {"MAE": round(mae, 5), "RMSE": round(rmse, 5),
                "daytime_MAE": round(mae_day, 5) if mae_day else None,
                "daytime_nMAE": round(nmae_day, 5) if nmae_day else None}

    # baselines (daytime normalized MAE on test)
    def baseline_metrics(yy, tag):
        y = yy
        b24 = np.roll(y, 24, axis=1)  # not aligned per row; computed properly below
        return b24

    res = {"epochs_done": int(len(hist.history["loss"])),
           "seed": SEED,
           "solar_geometry": "noaa_local_v2",
           "norm_mean": ymean, "norm_std": ystd,
           "val": eval(Xp_va, Xf_va, Ys_va, yva, "val"),
           "test": eval(Xp_te, Xf_te, Ys_te, yte, "test")}
    # naive-24 baseline evaluated properly on test (row-wise yesterday same horizon)
    yt = yte
    pred24 = np.empty_like(yt)
    for k in range(HORIZON):
        pred24[:, k] = yt[:, k - 24] if False else 0.0
    # day template from train (mean pv_n by hour-of-year bucket too heavy) -> naive daily shift:
    # naive24: for origin rows at absolute positions, use value 24h before each target hour
    idx_te = np.arange(LOOKBACK, n - HORIZON)
    idx_te = idx_te[(split[idx_te] == "test") & (split[idx_te + HORIZON - 1] == "test")]
    for k in range(HORIZON):
        pred24[:, k] = yraw[idx_te + k + 1 - 24]
    day = yt > 0.002
    b_mae = float(np.mean(np.abs(yt[day] - pred24[day])))
    res["naive24_daytime_MAE"] = round(b_mae, 5)
    print("naive24 daytime MAE test:", b_mae)
    (RUN / "metrics.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("DONE", round((time.time() - t0) / 60, 1), "min | metrics ->", RUN / "metrics.json")


if __name__ == "__main__":
    main()
