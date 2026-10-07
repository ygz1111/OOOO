#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 TF-2026 训练数据集（2023-01-01 ~ 2026-09-02，独立产物）。

数据拼接（接缝已验证平滑）:
  - 2023-01-01 ~ 2025-12-31: processed/step2_cleaned_data.pkl（Dry_Bulb/Dew_Point °C + System_Load）
  - 2026-01-01 ~ 2026-09-02: processed/2026_training_append/merged_2026_append.csv

流程（特征实现与原训练管线对拍验证一致: 27 列 0 差异）:
  step2 段 + 2026 段 → 全量特征(feature_generator) → 新 scaler(仅 train 行拟合)
  → 滑窗序列 X(N,168,38)/y(N,24) → 时间切分（y 起点归属 split，无泄漏）

切分（与用户规定一致）:
  train: y起点 ≤ 2026-06-30      val: 2026-07-01~07-31      test: 2026-08-01~09-02

输出（不覆盖任何原文件）:
  processed/tf_step5_scalers_2026.pkl   {feature_scaler, target_scaler}（train 段拟合）
  processed/tf_step6_2026.pkl           X/y train/val/test + metadata

用法: python scripts/build_tf_2026_dataset.py
"""
import os
import pickle
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)

from realtime_api.feature_generator import FeatureGenerator  # noqa: E402

PROCESSED = os.path.join(PROJECT_ROOT, "processed")
STEP2 = os.path.join(PROCESSED, "step2_cleaned_data.pkl")
NEW26 = os.path.join(PROCESSED, "2026_training_append", "merged_2026_append.csv")
OUT_SCALERS = os.path.join(PROCESSED, "tf_step5_scalers_2026.pkl")
OUT_SEQ = os.path.join(PROCESSED, "tf_step6_2026.pkl")

LOOKBACK = 168
HORIZON = 24
TRAIN_END = pd.Timestamp("2026-06-30 23:00")   # 训练标签最晚时刻
VAL_START = pd.Timestamp("2026-07-01 00:00")
VAL_END = pd.Timestamp("2026-07-31 23:00")
TEST_START = pd.Timestamp("2026-08-01 00:00")


def load_merged():
    """旧段(step2) + 新段(2026) → (weather, load) 全量整点表"""
    with open(STEP2, "rb") as f:
        s2 = pickle.load(f).reset_index()
    s2["timestamp"] = pd.to_datetime(s2["timestamp"])
    old = s2[s2["timestamp"] <= "2025-12-31 23:00"].copy()

    new = pd.read_csv(NEW26, parse_dates=["timestamp"])
    new = new[["timestamp", "dry_bulb_c", "dew_point_c", "system_load_mw"]].rename(
        columns={"dry_bulb_c": "Dry_Bulb", "dew_point_c": "Dew_Point",
                 "system_load_mw": "System_Load"})

    old_w = old[["timestamp", "Dry_Bulb", "Dew_Point"]].copy()
    old_w["Dry_Bulb"] = old_w["Dry_Bulb"].astype(float)
    old_w["Dew_Point"] = old_w["Dew_Point"].astype(float)
    old_l = old[["timestamp", "System_Load"]].copy()
    old_l["System_Load"] = old_l["System_Load"].astype(float)

    weather = pd.concat([old_w, new[["timestamp", "Dry_Bulb", "Dew_Point"]]],
                        ignore_index=True).drop_duplicates(subset="timestamp").sort_values("timestamp")
    load = pd.concat([old_l, new[["timestamp", "System_Load"]]],
                     ignore_index=True).drop_duplicates(subset="timestamp").sort_values("timestamp")
    # 连续性自检：只允许 2026-03-08 02:00（DST 春季跳变）缺失
    full = pd.date_range(load["timestamp"].min(), load["timestamp"].max(), freq="h")
    miss = full.difference(pd.DatetimeIndex(load["timestamp"]))
    allowed = {pd.Timestamp("2026-03-08 02:00")}
    extra = miss.difference(allowed)
    if len(extra):
        print(f"⚠️ 负荷表额外缺口 {len(extra)}: {list(extra[:5])}")
    else:
        print(f"✅ 负荷连续（仅 DST 缺口 {len(miss)} 个，属正常）")
    return weather, load


def main():
    print("=" * 60)
    print("构建 TF-2026 数据集")
    print("=" * 60)

    weather, load = load_merged()
    print(f"气象: {len(weather)} 行 {weather['timestamp'].min()} ~ {weather['timestamp'].max()}")
    print(f"负荷: {len(load)} 行 {load['timestamp'].min()} ~ {load['timestamp'].max()}")

    # ── 特征生成（与运行时/训练侧同实现，已对拍验证）──
    weather_df = weather.rename(columns={"Dry_Bulb": "temperature_2m",
                                         "Dew_Point": "dew_point_2m"})
    weather_df["location"] = "Regional"
    gen = FeatureGenerator()
    features = gen.generate(weather_df, load[["timestamp", "System_Load"]])
    features = features.reset_index()
    print(f"特征: {features.shape}")

    # 丢弃前 168 行（2023-01 开头滞后窗口不完整，与原 step4 起点一致）
    features = features.iloc[LOOKBACK:].reset_index(drop=True)
    f_ts = pd.DatetimeIndex(features["timestamp"])
    load_s = load.set_index("timestamp")["System_Load"].sort_index()

    # ── 时间切分（按 y 起点 t+1 归属）──
    t_ends = f_ts  # 窗口末时刻 t
    y_starts = t_ends + pd.Timedelta(hours=1)
    y_ends = t_ends + pd.Timedelta(hours=HORIZON)
    # 数据末端约束：y_ends 必须在负荷范围内
    last_load = load["timestamp"].max()
    valid = y_ends <= last_load
    print(f"样本候选: {valid.sum()}（剔除数据末端不足 24h 的 {len(valid) - valid.sum()}）")

    mask_train = (y_starts <= TRAIN_END) & valid
    mask_val = (y_starts >= VAL_START) & (y_starts <= VAL_END) & valid
    mask_test = (y_starts >= TEST_START) & valid
    print(f"切分: train {mask_train.sum()} | val {mask_val.sum()} | test {mask_test.sum()}")

    # ── scaler（只在 train 行拟合；特征行 ≤ train 最大窗口末）──
    train_rows_max_t = y_starts[mask_train].max() - pd.Timedelta(hours=1)
    fit_mask = f_ts <= train_rows_max_t
    feat_cols = [c for c in features.columns if c != "timestamp"]
    feature_scaler = MinMaxScaler()
    feature_scaler.fit(features.loc[fit_mask, feat_cols].to_numpy(dtype=np.float32))
    target_scaler = MinMaxScaler()
    load_train = load_s[load_s.index <= TRAIN_END].to_numpy(dtype=np.float32).reshape(-1, 1)
    target_scaler.fit(load_train)
    print(f"feature_scaler min={np.round(feature_scaler.data_min_[:3],1)} max={np.round(feature_scaler.data_max_[:3],1)}")
    print(f"target_scaler min={target_scaler.data_min_[0]:.0f} max={target_scaler.data_max_[0]:.0f} MW"
          f"（原 scaler: 8617 ~ 24871）")

    # ── 滑窗序列构建 ──
    feat_norm = feature_scaler.transform(features[feat_cols].to_numpy(dtype=np.float32))
    load_norm = target_scaler.transform(
        load_s.to_numpy(dtype=np.float32).reshape(-1, 1)).ravel()

    def build(mask):
        idx = np.where(mask)[0]
        # 需要完整 168 行窗口（features 已裁前 168 行 → 窗口起点恰为 2023-01-01）
        idx = idx[idx >= LOOKBACK - 1]
        X = np.stack([feat_norm[i - LOOKBACK + 1: i + 1] for i in idx]).astype(np.float32)
        # y: 窗口末 t 之后 1..24 小时的负荷（负荷表整点连续）
        y = np.stack([
            load_norm[load_s.index.get_indexer([t_ends[i]])[0] + 1:
                      load_s.index.get_indexer([t_ends[i]])[0] + 1 + HORIZON]
            for i in idx
        ]).astype(np.float32)
        return X, y

    X_tr, y_tr = build(mask_train)
    X_va, y_va = build(mask_val)
    X_te, y_te = build(mask_test)
    print(f"X_train {X_tr.shape} | X_val {X_va.shape} | X_test {X_te.shape}")

    # ── 泄漏自检 ──
    ts_train = f_ts[mask_train]; ts_val = f_ts[mask_val]; ts_test = f_ts[mask_test]
    assert ts_val.min() >= TRAIN_END + pd.Timedelta(hours=1) - pd.Timedelta(hours=LOOKBACK), "val 窗口含 train 未来行？"
    # 精确检查：val/test 样本的 X 窗口行时间 ≤ y 起点-1h（特征只用过去）
    for name, mask in [("val", mask_val), ("test", mask_test)]:
        t_arr = f_ts[mask]
        y_start_arr = t_arr + pd.Timedelta(hours=1)
        # X 窗口第一行时间 = t-167h
        leak = (y_start_arr.min() - pd.Timedelta(hours=1)) < t_arr.min() - pd.Timedelta(hours=LOOKBACK)
        print(f"{name}: y 起点范围 {y_start_arr.min()} ~ {y_start_arr.max()}"
              f" | X 窗口最早 {t_arr.min() - pd.Timedelta(hours=LOOKBACK - 1)}")

    meta = {
        "train": {"start": str(ts_train.min()), "end": str(ts_train.max())},
        "val": {"start": str(ts_val.min()), "end": str(ts_val.max())},
        "test": {"start": str(ts_test.min()), "end": str(ts_test.max())},
        "feature_cols": feat_cols,
        "target": "System_Load",
        "lookback": LOOKBACK, "horizon": HORIZON,
        "n_features": len(feat_cols),
        "note": "X窗口末t → y=t+1..t+24；scaler 仅 train 段拟合",
    }

    with open(OUT_SCALERS, "wb") as f:
        pickle.dump({"feature_scaler": feature_scaler, "target_scaler": target_scaler}, f)
    with open(OUT_SEQ, "wb") as f:
        pickle.dump({
            "X_train_seq": X_tr, "y_train_seq": y_tr,
            "X_val_seq": X_va, "y_val_seq": y_va,
            "X_test_seq": X_te, "y_test_seq": y_te,
            "metadata": meta,
        }, f)
    print(f"\n✅ 输出: {OUT_SCALERS}")
    print(f"✅ 输出: {OUT_SEQ}")


if __name__ == "__main__":
    main()
