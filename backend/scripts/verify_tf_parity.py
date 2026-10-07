# -*- coding: utf-8 -*-
"""
verify_tf_parity.py — 复现 MMXX test_inference 的全测试集奇偶校验 (子集)
========================================================================
用重建的 MMXX 特征表 + 本后端模型定义模块, 对测试集窗口子集重算指标,
与 MMXX runs/{tf_v2,pv_v1}/metrics.json 对比, 验证"图重建+scaler+解码"
与训练侧完全一致。只读, 不修改任何文件。

用法: cd backend && python scripts/verify_tf_parity.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from models.tensorflow_load import tf_v2_models, tf_pv_models  # noqa: E402

MMXX_PROC = BACKEND.parents[0] / "MMXX" / "smart-grid" / "data" / "processed"
N_WIN = int(os.environ.get("N_WIN", "400"))  # 校验窗口数 (默认400)


def check_tf2():
    df = pd.read_parquet(MMXX_PROC / "ca_features.parquet").sort_values("seq").reset_index(drop=True)
    df["rt_yest"] = df["RT_Demand"].shift(24)
    df["price_log"] = np.log1p(np.maximum(df["RT_LMP"], 0.0))
    tr = df[df["split"] == "train"]
    sp = StandardScaler().fit(tr[tf_v2_models.PAST_COLS].dropna())
    sf = StandardScaler().fit(tr[tf_v2_models.FUT_COLS].dropna())
    sl = StandardScaler().fit(tr[["RT_Demand"]])
    sy = StandardScaler().fit(tr[["price_log"]])
    P = sp.transform(df[tf_v2_models.PAST_COLS]).astype("float32")
    F = sf.transform(df[tf_v2_models.FUT_COLS]).astype("float32")
    split = df["split"].values
    n = len(df)
    idx = np.arange(tf_v2_models.LOOKBACK + 24, n - tf_v2_models.HORIZON)
    idx = idx[(split[idx] == "test") & (split[idx + 23] == "test")]
    rng = np.random.RandomState(0)
    idx = rng.choice(idx, size=min(N_WIN, len(idx)), replace=False)
    back = np.arange(-(tf_v2_models.LOOKBACK - 1), 1)
    fwd = np.arange(1, tf_v2_models.HORIZON + 1)
    Xp = P[idx[:, None] + back[None, :]]
    Xf = F[idx[:, None] + fwd[None, :]]
    model = tf_v2_models.load_trained_model(
        str(BACKEND / "models" / "tf_assets" / "tf_v2" / "tf_v2_best.weights.h5"))
    pr = model.predict([Xp, Xf], batch_size=512, verbose=0)
    lp = sl.inverse_transform(pr["load"][..., 0].reshape(-1, 1)).reshape(pr["load"][..., 0].shape)
    yt = df["RT_Demand"].to_numpy()[idx[:, None] + fwd[None, :]]
    q = np.expm1(sy.inverse_transform(pr["price"].reshape(-1, 3)).reshape(pr["price"].shape))
    # 真实值: 训练侧 Y = sy.transform(price_log), 因此逆解码必须作用于标准化后的目标
    plz = sy.transform(
        df["price_log"].to_numpy()[idx[:, None] + fwd[None, :]].reshape(-1, 1)).reshape(yt.shape)
    yp = np.expm1(sy.inverse_transform(plz.reshape(-1, 1)).reshape(yt.shape))
    mae = float(np.mean(np.abs(lp - yt)))
    rmse = float(np.sqrt(np.mean((lp - yt) ** 2)))
    pmae = float(np.mean(np.abs(q[..., 1] - yp)))
    print(f"[tf_v2 parity] n={len(idx)} load_MAE={mae:.1f} (metrics 331.0) "
          f"RMSE={rmse:.1f} (454.3) | price_p50_MAE={pmae:.2f} (19.21)")
    return mae


def check_pv():
    pv = pd.read_parquet(MMXX_PROC / "pv_features.parquet").sort_values("ts_start").reset_index(drop=True)
    zt = [f"temp_{z}" for z in tf_pv_models.ZONES]
    pv["temp_mean"] = pv[zt].mean(axis=1)
    hr = pd.to_datetime(pv["ts_start"]).dt
    pv["hour_sin"] = np.sin(2 * np.pi * hr.hour / 24)
    pv["hour_cos"] = np.cos(2 * np.pi * hr.hour / 24)
    pv["dow_sin"] = np.sin(2 * np.pi * hr.dayofweek / 7)
    pv["dow_cos"] = np.cos(2 * np.pi * hr.dayofweek / 7)
    tr = pv[pv["split"] == "train"]
    sp = StandardScaler().fit(tr[tf_pv_models.PAST_COLS])
    sf = StandardScaler().fit(tr[tf_pv_models.FUT_COLS])
    yraw = pv["pv_n_ISONE"].astype("float64").values
    ytr = yraw[pv["split"] == "train"]
    ymean, ystd = float(ytr.mean()), float(ytr.std())
    P = np.nan_to_num(sp.transform(pv[tf_pv_models.PAST_COLS])).astype("float32")
    F = np.nan_to_num(sf.transform(pv[tf_pv_models.FUT_COLS])).astype("float32")
    split = pv["split"].values
    n = len(pv)
    idx = np.arange(tf_pv_models.LOOKBACK, n - tf_pv_models.HORIZON)
    idx = idx[(split[idx] == "test") & (split[idx + 23] == "test")]
    rng = np.random.RandomState(0)
    idx = rng.choice(idx, size=min(N_WIN, len(idx)), replace=False)
    back = np.arange(-(tf_pv_models.LOOKBACK - 1), 1)
    fwd = np.arange(1, tf_pv_models.HORIZON + 1)
    Xp = P[idx[:, None] + back[None, :]]
    Xf = F[idx[:, None] + fwd[None, :]]
    model = tf_pv_models.load_trained_model(
        str(BACKEND / "models" / "tf_assets" / "pv_v1" / "pv_v1_best.weights.h5"))
    p = model.predict([Xp, Xf], batch_size=512, verbose=0)[..., 0]
    pred = np.clip(p * ystd + ymean, 0, 1)
    yt = yraw[idx[:, None] + fwd[None, :]]
    day = yt > 0.002
    mae = float(np.mean(np.abs(pred[day] - yt[day]))) if day.any() else float("nan")
    print(f"[pv_v1 parity] n={len(idx)} daytime_MAE={mae:.4f} p.u. (metrics 0.0390)")
    return mae


if __name__ == "__main__":
    print("=== parity vs MMXX metrics (subset) ===")
    m1 = check_tf2()
    m2 = check_pv()
    ok = abs(m1 - 331.0) < 60 and abs(m2 - 0.039) < 0.02
    print("PARITY_OK" if ok else "PARITY_MISMATCH")
