# -*- coding: utf-8 -*-
"""
smart-grid / scripts / train_tf.py
==================================
Stage-2 TF deep multi-task trainer (CA RT load + RT LMP quantiles, 24h ahead).
  - context encoder: GRU over 168h history
  - direct decoder: 24 forecast steps conditioned on known future features
    (calendar, DA cleared curve, weather forecast, yesterday-same-hour load)
  - heads: load p50 (MAE loss) | price log1p quantiles p10/p50/p90 (pinball)
  - training: up to EPOCHS (80) with early stopping on val total loss
  - artefacts under runs/tf_v1/ (logs, best weights, metrics, predictions)

Run with the GPU env wrapper:
  bash gpu_env.sh $VENV/python scripts/train_tf.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import r2_score

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
for g in tf.config.list_physical_devices("GPU"):
    try:
        tf.config.experimental.set_memory_growth(g, True)
    except Exception:  # noqa
        pass

SEED = 42
tf.random.set_seed(SEED)
np.random.seed(SEED)

# runtime-configurable: TRAIN_TAG | EPOCHS | PATIENCE (0 = no early stop)
RUN_TAG = os.environ.get("TRAIN_TAG", "tf_v3")
EPOCHS = int(os.environ.get("EPOCHS", "80"))
PATIENCE = int(os.environ.get("PATIENCE", "0"))

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
RUN = ROOT / "runs" / RUN_TAG
RUN.mkdir(parents=True, exist_ok=True)
LOG = RUN / "train_log.csv"
TB = ROOT / "runs" / "tensorboard" / RUN_TAG
CKPT = ROOT / "models" / f"{RUN_TAG}_best.weights.h5"

LOOKBACK = 168          # history hours
HORIZON = 24            # forecast hours
BATCH = 256

PAST_COLS = ["RT_Demand", "DA_Demand", "RT_LMP", "DA_LMP", "Dry_Bulb", "Dew_Point",
             "hdd65", "cdd65", "temp_mem",
             "clock_hour_sin", "clock_hour_cos", "dow_sin", "dow_cos",
             "is_holiday", "is_dst"]
FUT_COLS = ["DA_Demand", "DA_LMP", "Dry_Bulb", "Dew_Point", "hdd65", "cdd65",
            "clock_hour_sin", "clock_hour_cos", "dow_sin", "dow_cos",
            "is_holiday", "is_dst", "rt_yest"]

TAUS = np.array([0.1, 0.5, 0.9], dtype="float32")


class Pinball(tf.keras.losses.Loss):
    """mean pinball over channels(tau) x steps for one batch"""

    def call(self, y_true, y_pred):
        err = y_true - y_pred                        # (B, H, 1) vs (B, H, 3)
        tau = tf.reshape(tf.constant(TAUS), (1, 1, 3))
        loss = tf.maximum(tau * err, (tau - 1.0) * err)
        return tf.reduce_mean(loss)


def build_model(n_past: int, n_fut: int):
    past = tf.keras.Input(shape=(LOOKBACK, n_past), name="in_past")
    fut = tf.keras.Input(shape=(HORIZON, n_fut), name="in_fut")
    x = tf.keras.layers.Masking(mask_value=0.0)(past)
    x = tf.keras.layers.GRU(192, return_sequences=False, dropout=0.15,
                            recurrent_dropout=0.0, name="encoder")(x)
    ctx = tf.keras.layers.RepeatVector(HORIZON, name="ctx_tile")(x)
    dec = tf.keras.layers.Concatenate(axis=-1)([ctx, fut])
    dec = tf.keras.layers.Dense(128, activation="swish", name="dec_d1")(dec)
    dec = tf.keras.layers.Dropout(0.15)(dec)
    dec = tf.keras.layers.Dense(96, activation="swish", name="dec_d2")(dec)
    load = tf.keras.layers.TimeDistributed(
        tf.keras.layers.Dense(1, name="load_head"), name="load_td")(dec)       # (B,24,1)
    price_q = tf.keras.layers.TimeDistributed(
        tf.keras.layers.Dense(3, name="price_head"), name="price_td")(dec)     # (B,24,3)
    model = tf.keras.Model(inputs=[past, fut], outputs={"load": load, "price": price_q})
    return model


def main() -> None:
    t0 = time.time()
    df = pd.read_parquet(PROC / "ca_features.parquet").sort_values("seq").reset_index(drop=True)
    df["rt_yest"] = df["RT_Demand"].shift(24)                       # known same-clock yesterday
    df["price_log"] = np.log1p(np.maximum(df["RT_LMP"], 0.0))
    split = df["split"].values

    # ---------------- scalers (train only) --------------------------------
    tr_rows = df[split == "train"]
    sp = StandardScaler().fit(tr_rows[PAST_COLS].dropna())
    sf = StandardScaler().fit(tr_rows[FUT_COLS].dropna())
    sl = StandardScaler().fit(tr_rows[["RT_Demand"]])
    sy = StandardScaler().fit(tr_rows[["price_log"]])

    P = sp.transform(df[PAST_COLS]).astype("float32")
    F = sf.transform(df[FUT_COLS]).astype("float32")
    Y = np.stack([sl.transform(df[["RT_Demand"]])[:, 0],
                  sy.transform(df[["price_log"]])[:, 0]], axis=1).astype("float32")

    n = len(df)
    back_off = np.arange(-(LOOKBACK - 1), 1)
    fwd = np.arange(1, HORIZON + 1)

    def build_part(part: str):
        idx = np.arange(LOOKBACK + 24, n - HORIZON)                 # warmup for cols
        idx = idx[(split[idx] == part) & (split[idx + HORIZON - 1] == part)]
        if len(idx) == 0:
            return None
        return (P[idx[:, None] + back_off[None, :]],
                F[idx[:, None] + fwd[None, :]],
                Y[idx[:, None] + fwd[None, :]])                     # (n,H,2)

    Xp_tr, Xf_tr, Y_tr = build_part("train")
    Xp_va, Xf_va, Y_va = build_part("val")
    Xp_te, Xf_te, Y_te = build_part("test")
    print(f"windows: train={Xp_tr.shape[0]} val={Xp_va.shape[0]} test={Xp_te.shape[0]} "
          f"| seq_len={LOOKBACK} horizon={HORIZON}", flush=True)

    def ds(Xp, Xf, Yv, shuffle=False, repeat=False):
        d = tf.data.Dataset.from_tensor_slices(({"in_past": Xp, "in_fut": Xf},
                                                {"load": Yv[..., :1], "price": Yv[..., 1:2]}))
        if shuffle:
            d = d.shuffle(4096)
        if repeat:
            d = d.repeat()
        return d.batch(BATCH).prefetch(tf.data.AUTOTUNE)

    model = build_model(len(PAST_COLS), len(FUT_COLS))
    # Cosine LR (or AdamW default when early stopping enabled)
    if PATIENCE <= 0:
        steps_per_epoch = int(np.ceil(len(Xp_tr) / BATCH))
        decay_steps = max(1, EPOCHS * steps_per_epoch)
        lr = tf.keras.optimizers.schedules.CosineDecay(1e-3, decay_steps, alpha=0.05)
        opt = tf.keras.optimizers.AdamW(learning_rate=lr, weight_decay=1e-4)
    else:
        opt = tf.keras.optimizers.AdamW(learning_rate=1e-3, weight_decay=1e-4)
    model.compile(
        optimizer=opt,
        loss={"load": tf.keras.losses.MeanAbsoluteError(), "price": Pinball()},
        loss_weights={"load": 1.0, "price": 0.6},
        metrics={},
    )
    model.summary()

    cbs = []
    if PATIENCE > 0:
        cbs.append(tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=PATIENCE,
                                                    restore_best_weights=True, mode="min"))
        cbs.append(tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=6,
                                                        min_lr=1e-5, verbose=1))
    cbs += [
        tf.keras.callbacks.ModelCheckpoint(str(CKPT), monitor="val_loss", mode="min",
                                           save_best_only=True, save_weights_only=True, verbose=1),
        tf.keras.callbacks.CSVLogger(str(LOG)),
        tf.keras.callbacks.TensorBoard(log_dir=str(TB), histogram_freq=0, write_graph=False),
        tf.keras.callbacks.TerminateOnNaN(),
    ]
    hist = model.fit(ds(Xp_tr, Xf_tr, Y_tr, shuffle=True, repeat=True),
                     validation_data=ds(Xp_va, Xf_va, Y_va),
                     epochs=EPOCHS, steps_per_epoch=int(np.ceil(len(Xp_tr) / BATCH)),
                     callbacks=cbs, verbose=1)

    # best weights were restored by early stopping
    model.load_weights(str(CKPT))
    epochs_done = len(hist.history["loss"])

    def evaluate(Xp, Xf, Yv, tag):
        pr = model.predict([Xp, Xf], batch_size=BATCH, verbose=0)
        yl = Yv[..., 0]
        pl = Yv[..., 1]
        p_load = pr["load"][..., 0]
        p_q = pr["price"]                                          # (n,24,3)
        # invert
        y_load = sl.inverse_transform(yl.reshape(-1, 1)).reshape(yl.shape)
        y_load = np.maximum(y_load, 0)
        p_load_r = sl.inverse_transform(p_load.reshape(-1, 1)).reshape(p_load.shape)
        y_price = np.expm1(sy.inverse_transform(pl.reshape(-1, 1)).reshape(pl.shape))
        p_q_r = np.expm1(sy.inverse_transform(p_q.reshape(-1, 3)).reshape(p_q.shape))
        mae = float(np.mean(np.abs(y_load - p_load_r)))
        rmse = float(np.sqrt(np.mean((y_load - p_load_r) ** 2)))
        mape = float(np.mean(np.abs(y_load - p_load_r) / y_load) * 100)
        peak = np.zeros(HORIZON, dtype=bool)
        peak[17 - 1:20] = True
        peak_mae = float(np.mean(np.abs(y_load[:, peak] - p_load_r[:, peak])))
        r2 = float(r2_score(y_load.ravel(), p_load_r.ravel()))
        # price p50
        p50 = p_q_r[..., 1]
        pm = float(np.mean(np.abs(y_price - p50)))
        prm = float(np.sqrt(np.mean((y_price - p50) ** 2)))
        cov = float(np.mean((y_price >= p_q_r[..., 0]) & (y_price <= p_q_r[..., 2])))
        res = {"load_MAE_MW": round(mae, 1), "load_RMSE_MW": round(rmse, 1),
               "load_MAPE_pct": round(mape, 2), "load_R2": round(r2, 4),
               "load_peakMAE_MW": round(peak_mae, 1),
               "price_p50_MAE_usd": round(pm, 2), "price_p50_RMSE_usd": round(prm, 2),
               "price_p10p90_coverage": round(cov, 4)}
        np.savez(RUN / f"preds_{tag}.npz",
                 y_load=y_load, p_load=p_load_r, y_price=y_price, p_q=p_q_r)
        print(f"[{tag}] {json.dumps(res)}", flush=True)
        return res

    res = {"epochs_done": int(epochs_done), "config": {
        "encoder": "GRU192", "lookback": LOOKBACK, "horizon": HORIZON,
        "batch": BATCH, "epoch_cap": EPOCHS, "patience": PATIENCE,
        "past_cols": PAST_COLS, "fut_cols": FUT_COLS},
        "windows": {"train": int(len(Xp_tr)), "val": int(len(Xp_va)), "test": int(len(Xp_te))},
        "val": evaluate(Xp_va, Xf_va, Y_va, "val"),
        "test": evaluate(Xp_te, Xf_te, Y_te, "test"),
        "minutes": round((time.time() - t0) / 60, 1)}
    (RUN / "metrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nTRAINING DONE: {epochs_done} epochs in {res['minutes']} min | best weights -> {CKPT}")
    print("metrics ->", RUN / "metrics.json")


if __name__ == "__main__":
    main()
