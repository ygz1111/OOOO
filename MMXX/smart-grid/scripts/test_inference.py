# -*- coding: utf-8 -*-
"""
smart-grid / scripts/test_inference.py
========================================
End-to-end inference smoke test for the two trained models:
  tf_v2  (load + price quantiles, 168h -> 24h)
  pv_v1  (normalized PV, 96h -> 24h)
Reconstructs inputs exactly as training did, predicts one "now" origin,
and compares with the actual values for those 24 hours.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.preprocessing import StandardScaler

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"


def build_tf2():
    PAST = ["RT_Demand", "DA_Demand", "RT_LMP", "DA_LMP", "Dry_Bulb", "Dew_Point",
            "hdd65", "cdd65", "temp_mem", "clock_hour_sin", "clock_hour_cos",
            "dow_sin", "dow_cos", "is_holiday", "is_dst"]
    FUT = ["DA_Demand", "DA_LMP", "Dry_Bulb", "Dew_Point", "hdd65", "cdd65",
           "clock_hour_sin", "clock_hour_cos", "dow_sin", "dow_cos",
           "is_holiday", "is_dst", "rt_yest"]
    LB, HZ = 168, 24
    df = pd.read_parquet(PROC / "ca_features.parquet").sort_values("seq").reset_index(drop=True)
    df["rt_yest"] = df["RT_Demand"].shift(24)
    df["price_log"] = np.log1p(np.maximum(df["RT_LMP"], 0.0))
    tr = df[df["split"] == "train"]
    sp = StandardScaler().fit(tr[PAST]); sf = StandardScaler().fit(tr[FUT])
    sl = StandardScaler().fit(tr[["RT_Demand"]]); sy = StandardScaler().fit(tr[["price_log"]])
    past_in = tf.keras.Input((LB, len(PAST))); fut_in = tf.keras.Input((HZ, len(FUT)))
    x = tf.keras.layers.GRU(192, return_sequences=False, dropout=0.15)(past_in)
    ctx = tf.keras.layers.RepeatVector(HZ)(x)
    dec = tf.keras.layers.Concatenate()([ctx, fut_in])
    dec = tf.keras.layers.Dense(128, activation="swish")(dec)
    dec = tf.keras.layers.Dropout(0.15)(dec)
    dec = tf.keras.layers.Dense(96, activation="swish")(dec)
    load = tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(1), name="load")(dec)
    price = tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(3), name="price")(dec)
    model = tf.keras.Model(inputs=[past_in, fut_in], outputs={"load": load, "price": price})
    model.load_weights(str(ROOT / "models" / "tf_v2_best.weights.h5"))
    return model, df, sp, sf, sl, sy, PAST, FUT, LB, HZ


def build_pv():
    PAST = ["ghi_mean", "cloud_mean", "temp_mean", "coszen", "sun_up", "pv_n_ISONE",
            "db_ca", "dp_ca", "hour_sin", "hour_cos", "dow_sin", "dow_cos"]
    FUT = ["ghi_mean", "cloud_mean", "temp_mean", "coszen", "sun_up", "hour_sin", "hour_cos"]
    LB, HZ = 96, 24
    df = pd.read_parquet(PROC / "pv_features.parquet").sort_values("ts_start").reset_index(drop=True)
    zt = [f"temp_{z}" for z in ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]]
    df["temp_mean"] = df[zt].mean(axis=1)
    hr = pd.to_datetime(df["ts_start"]).dt
    df["hour_sin"] = np.sin(2 * np.pi * hr.hour / 24); df["hour_cos"] = np.cos(2 * np.pi * hr.hour / 24)
    df["dow_sin"] = np.sin(2 * np.pi * hr.dayofweek / 7); df["dow_cos"] = np.cos(2 * np.pi * hr.dayofweek / 7)
    tr = df[df["split"] == "train"]
    sp = StandardScaler().fit(tr[PAST]); sf = StandardScaler().fit(tr[FUT])
    pv = df["pv_n_ISONE"].astype("float64")
    mu, sd = float(pv[df["split"] == "train"].mean()), float(pv[df["split"] == "train"].std())
    past_in = tf.keras.Input((LB, len(PAST))); fut_in = tf.keras.Input((HZ, len(FUT)))
    enc = tf.keras.layers.GRU(128, return_sequences=False, dropout=0.15)(past_in)
    cat = tf.keras.layers.Concatenate()([tf.keras.layers.RepeatVector(HZ)(enc), fut_in])
    cat = tf.keras.layers.Dense(96, activation="swish")(cat)
    cat = tf.keras.layers.Dropout(0.15)(cat)
    cat = tf.keras.layers.Dense(64, activation="swish")(cat)
    out = tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(1))(cat)
    model = tf.keras.Model(inputs=[past_in, fut_in], outputs=out)
    model.load_weights(str(ROOT / "models" / "pv_v1_best.weights.h5"))
    return model, df, sp, sf, mu, sd, PAST, FUT, LB, HZ


def main():
    print("=" * 30, "1) LOAD + PRICE MODEL (tf_v2)", "=" * 30, flush=True)
    model, df, sp, sf, sl, sy, PAST, FUT, LB, HZ = build_tf2()
    tsl = pd.to_datetime(df["ts_local"])
    origin = pd.Timestamp("2026-07-15 00:00:00")           # pretend "now"
    pos = int(np.flatnonzero(tsl == origin)[0])
    print("origin:", origin, "| model inputs: past", LB, "h, future", HZ, "h")
    # construct past/future windows
    idx = np.arange(pos - LB + 1, pos + 1)
    fdx = np.arange(pos + 1, pos + HZ + 1)
    P = sp.transform(df.loc[idx, PAST]).astype("float32")[None]
    F = sf.transform(df.loc[fdx, FUT]).astype("float32")[None]
    pr = model.predict([P, F], verbose=0)
    load_pred = sl.inverse_transform(pr["load"][0]).ravel()
    q_raw = pr["price"][0]
    q = np.expm1(sy.inverse_transform(q_raw))
    tgt_ts = tsl.values[fdx]
    y_load = df.loc[fdx, "RT_Demand"].values.astype("float64")
    y_price = df.loc[fdx, "RT_LMP"].values.astype("float64")
    assert np.isfinite(load_pred).all() and np.isfinite(q).all()
    rows = []
    for i in range(HZ):
        rows.append({"time": str(pd.Timestamp(tgt_ts[i])),
                     "load_pred_MW": round(float(load_pred[i]), 1),
                     "load_actual_MW": round(float(y_load[i]), 1),
                     "price_p10": round(float(q[i, 0]), 2),
                     "price_p50": round(float(q[i, 1]), 2),
                     "price_p90": round(float(q[i, 2]), 2),
                     "price_actual": round(float(y_price[i]), 2)})
    print("load 24h forecast vs actual (sample):")
    for r in rows[:6]:
        print(" ", r)
    mae_l = float(np.mean(np.abs(load_pred - y_load)))
    print(f"this-day load MAE: {mae_l:.1f} MW | load range pred [{load_pred.min():.0f},{load_pred.max():.0f}] "
          f"actual [{y_load.min():.0f},{y_load.max():.0f}]")
    print("price p50 24h vs actual (first 6):", [(round(q[i, 1], 1), round(float(y_price[i]), 1)) for i in range(6)])

    print()
    print("=" * 30, "2) PV MODEL (pv_v1)", "=" * 30, flush=True)
    m2, df2, sp2, sf2, mu, sd, PAST2, FUT2, LB2, HZ2 = build_pv()
    ts2 = pd.to_datetime(df2["ts_start"])
    origin2 = pd.Timestamp("2026-04-15 00:00:00")
    pos2 = int(np.flatnonzero(ts2 == origin2)[0])
    idx2 = np.arange(pos2 - LB2 + 1, pos2 + 1)
    fdx2 = np.arange(pos2 + 1, pos2 + HZ2 + 1)
    P2 = sp2.transform(df2.loc[idx2, PAST2]).astype("float32")[None]
    F2 = sf2.transform(df2.loc[fdx2, FUT2]).astype("float32")[None]
    pr2 = m2.predict([P2, F2], verbose=0)[0, :, 0] * sd + mu
    pr2 = np.clip(pr2, 0, 1)
    y2 = df2.loc[fdx2, "pv_n_ISONE"].values.astype("float64")
    assert np.isfinite(pr2).all()
    print("origin:", origin2)
    print("pv 24h forecast vs actual (sample):")
    for i in range(0, HZ2, 3):
        print(f"  t+{i + 1:2d}h {pd.Timestamp(ts2.values[fdx2[i]]).strftime('%m-%d %H:%M')} "
              f"pred={pr2[i]:.3f} actual={y2[i]:.3f}")
    day = y2 > 0.002
    mae2 = float(np.mean(np.abs(pr2[day] - y2[day]))) if day.any() else float("nan")
    print(f"this-day daytime PV MAE: {mae2:.4f} p.u. | pred range [{pr2.min():.3f},{pr2.max():.3f}] "
          f"actual [{y2.min():.3f},{y2.max():.3f}]")

    # ---- 3) whole-test-set parity check ---------------------------------
    print()
    print("=" * 30, "3) FULL-TEST-SET PARITY CHECK", "=" * 30)
    split = df["split"].values
    idx_all = np.arange(LB, len(df) - HZ)
    idx_all = idx_all[(split[idx_all] == "test") & (split[idx_all + HZ - 1] == "test")]
    back = np.arange(-(LB - 1), 1); fwd = np.arange(1, HZ + 1)
    P3 = sp.transform(df[PAST]).astype("float32")
    F3 = sf.transform(df[FUT]).astype("float32")
    Xp = P3[idx_all[:, None] + back[None, :]]
    Xf = F3[idx_all[:, None] + fwd[None, :]]
    pr3 = model.predict([Xp, Xf], batch_size=512, verbose=0)
    lp = sl.inverse_transform(pr3["load"][..., 0].reshape(-1, 1)).reshape(pr3["load"][..., 0].shape)
    yt = df["RT_Demand"].to_numpy()[idx_all[:, None] + fwd[None, :]]
    mae_all = float(np.mean(np.abs(lp - yt)))
    rmse_all = float(np.sqrt(np.mean((lp - yt) ** 2)))
    print(f"full-test inference: load MAE={mae_all:.1f} MW RMSE={rmse_all:.1f} MW "
          f"(metrics.json says MAE 331.0 / RMSE 454.3)")
    print("parity OK" if abs(mae_all - 331.0) < 15 else "parity MISMATCH - investigate")

    split2 = df2["split"].values
    idx2all = np.arange(LB2, len(df2) - HZ2)
    idx2all = idx2all[(split2[idx2all] == "test") & (split2[idx2all + HZ2 - 1] == "test")]
    back2 = np.arange(-(LB2 - 1), 1); fwd2 = np.arange(1, HZ2 + 1)
    P2a = np.nan_to_num(sp2.transform(df2[PAST2])).astype("float32")
    F2a = np.nan_to_num(sf2.transform(df2[FUT2])).astype("float32")
    Xp2 = P2a[idx2all[:, None] + back2[None, :]]
    Xf2 = F2a[idx2all[:, None] + fwd2[None, :]]
    pr2a = m2.predict([Xp2, Xf2], batch_size=512, verbose=0)[..., 0] * sd + mu
    yt2 = df2["pv_n_ISONE"].to_numpy()[idx2all[:, None] + fwd2[None, :]]
    daym = yt2 > 0.002
    mae2_all = float(np.mean(np.abs(pr2a[daym] - yt2[daym])))
    print(f"full-test PV daytime MAE={mae2_all:.4f} p.u. (metrics.json says 0.0390)")
    print("PV parity OK" if abs(mae2_all - 0.0390) < 0.004 else "PV parity MISMATCH - investigate")
    print()
    print("RESULT: both models loaded weights and produced finite 24h forecasts OK")


if __name__ == "__main__":
    main()
