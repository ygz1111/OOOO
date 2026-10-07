# -*- coding: utf-8 -*-
"""
smart-grid / scripts/make_pv_figures.py
========================================
Thesis figures for the PV forecasting work.
Part A (data, no model):  pv01..pv10 from data/processed/pv_features.parquet
Part B (model results):   pv11..pv17 from runs/pv_v1 (rebuild windows, predict)
Output -> figures/pv/ (+ FIGURES_INDEX)
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
RUN = ROOT / "runs" / "pv_v1"
CKPT = ROOT / "models" / "pv_v1_best.weights.h5"
FIG = ROOT / "figures" / "pv"
FIG.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"figure.dpi": 150, "savefig.dpi": 150, "font.size": 9,
                     "axes.titlesize": 11, "axes.labelsize": 9.5, "legend.fontsize": 8,
                     "axes.grid": True, "grid.alpha": 0.3})
C = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
made = []


def save(fig, name):
    fig.savefig(FIG / name, bbox_inches="tight")
    plt.close(fig)
    made.append(name)
    print("saved", name)


df = pd.read_parquet(PROC / "pv_features.parquet").sort_values("ts_start").reset_index(drop=True)
ts = pd.to_datetime(df["ts_start"])
zt = [f"temp_{z}" for z in ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]]
df["temp_mean"] = df[zt].mean(axis=1)
pv_n = df["pv_n_ISONE"]
pv_mw = df["pv_mw_ISONE"]
ghi = df["ghi_mean"]

# ============================ PART A: EDA ================================
# pv01 overview
fig, ax = plt.subplots(figsize=(11, 3.6))
ax.plot(ts, pv_n, lw=0.2, color=C[0])
daily = pv_n.groupby(ts.dt.date).mean()
ax.plot(pd.to_datetime(daily.index), daily.values, lw=1.0, color=C[3], label="daily mean")
ax.set_xlabel("Date"); ax.set_ylabel("Normalized PV output (p.u.)")
ax.set_title("ISO-NE behind-the-meter PV (normalized per MW), hourly 2017-2026")
ax.legend()
save(fig, "pv01_overview.png")

# pv02 monthly box
fig, ax = plt.subplots(figsize=(10, 3.6))
dd = pd.DataFrame({"pv": pv_n, "ym": ts.dt.to_period("M").astype(str)})
dd.boxplot(column="pv", by="ym", ax=ax, showfliers=False, rot=90, fontsize=6)
plt.setp(ax.get_xticklabels(), rotation=90, fontsize=6)
ax.set_title("Normalized PV by month"); ax.set_xlabel(""); ax.set_ylabel("p.u.")
fig.suptitle("")
save(fig, "pv02_monthly_box.png")

# pv03 seasonal daily curves
fig, ax = plt.subplots(figsize=(9, 3.8))
mp = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
      6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}
dd2 = pd.DataFrame({"pv": pv_n, "h": ts.dt.hour, "sn": ts.dt.month.map(mp)})
for i, sn in enumerate(["DJF", "MAM", "JJA", "SON"]):
    s = dd2[dd2["sn"] == sn].groupby("h")["pv"].mean()
    ax.plot(s.index, s.values, label=sn, color=C[i], lw=1.8)
ax.set_xlabel("Hour of day"); ax.set_ylabel("Mean normalized PV (p.u.)"); ax.legend()
ax.set_title("Mean daily PV curve by season")
save(fig, "pv03_seasonal_curve.png")

# pv04 PV vs radiation
fig, ax = plt.subplots(figsize=(7.5, 4.5))
m = pv_n > 0.002
ax.scatter(ghi[m], pv_n[m], s=1.5, alpha=0.2, color=C[0])
ax.set_xlabel("ERA5 GHI (W/m2)"); ax.set_ylabel("Normalized PV (p.u.)")
ax.set_title("PV output vs solar radiation (daytime hours)")
save(fig, "pv04_pv_vs_radiation.png")

# pv05 PV vs cloud
fig, ax = plt.subplots(figsize=(7.5, 4.5))
m = ghi > 10
ax.scatter(df["cloud_mean"][m], pv_n[m], s=1.5, alpha=0.2, color=C[1])
ax.set_xlabel("Mean cloud cover (%)"); ax.set_ylabel("Normalized PV (p.u.)")
ax.set_title("PV vs cloud cover (irradiated hours)")
save(fig, "pv05_pv_vs_cloud.png")

# pv06 solar elevation effect: coszen binned mean (clear-ish days by cloud<30)
fig, ax = plt.subplots(figsize=(7.5, 4.2))
cl = df["cloud_mean"] < 30
cs = df["coszen"]
b = pd.qcut(cs[cl], 12, duplicates="drop")
g = pv_n[cl].groupby(b, observed=False).mean()
ax.plot([iv.mid for iv in g.index.categories], g.values, "o-")
ax.set_xlabel("cos(zenith) bin"); ax.set_ylabel("Mean normalized PV (p.u.)")
ax.set_title("Clear-sky response: PV vs solar elevation")
save(fig, "pv06_coszen_response.png")

# pv07 zone profiles summer
fig, ax = plt.subplots(figsize=(9, 4))
zm = df[ts.dt.month.isin([6, 7, 8])]
for z in ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]:
    s = zm.groupby(ts.dt.hour)[f"pv_n_{z}"].mean()
    ax.plot(s.index, s.values, label=z)
ax.set_xlabel("Hour of day"); ax.set_ylabel("Mean normalized PV (p.u.)")
ax.set_title("Summer daily PV profile by zone"); ax.legend(ncol=4, fontsize=7)
save(fig, "pv07_zone_summer.png")

# pv08 annual growth (MW) vs stable normalized
fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
a1 = pv_mw[ts.dt.month.isin([6, 7])].groupby(ts.dt.year).median()
a2 = pv_n[ts.dt.month.isin([6, 7])].groupby(ts.dt.year).median()
axes[0].plot(a1.index, a1.values, "o-"); axes[0].set_title("July median PV (MW) growth")
axes[1].plot(a2.index, a2.values, "o-", color=C[1]); axes[1].set_title("July median normalized PV")
for a in axes:
    a.set_xlabel("Year"); a.set_ylabel("p.u./MW")
save(fig, "pv08_capacity_growth.png")

# pv09 heatmap month x hour
fig, ax = plt.subplots(figsize=(9, 4))
piv = pd.DataFrame({"pv": pv_n, "h": ts.dt.hour, "m": ts.dt.month}).groupby(["m", "h"])["pv"].mean().unstack()
im = ax.imshow(piv.values, aspect="auto", cmap="viridis", origin="lower")
ax.set_yticks(range(12), labels=range(1, 13)); ax.set_xlabel("Hour of day"); ax.set_ylabel("Month")
ax.set_title("Mean normalized PV: month x hour")
fig.colorbar(im, ax=ax, label="p.u.")
save(fig, "pv09_heatmap_month_hour.png")

# pv10 winter vs summer day sample (normalized curves around solstices)
fig, ax = plt.subplots(figsize=(9, 3.6))
for day, lab in [("2024-06-21", "summer solstice"), ("2024-12-21", "winter solstice"),
                 ("2024-03-20", "spring equinox")]:
    d = ts.dt.date.astype(str)
    m = d == day
    if m.any():
        s = pv_n[m].reset_index(drop=True)
        ax.plot(range(len(s)), s.values, label=lab)
ax.set_xlabel("Hour"); ax.set_ylabel("Normalized PV"); ax.legend()
ax.set_title("PV curves on solstices / equinox")
save(fig, "pv10_solstice_days.png")

# ============================ PART B: model results =======================
PAST = ["ghi_mean", "cloud_mean", "temp_mean", "coszen", "sun_up", "pv_n_ISONE",
        "db_ca", "dp_ca", "hour_sin", "hour_cos", "dow_sin", "dow_cos"]
FUT = ["ghi_mean", "cloud_mean", "temp_mean", "coszen", "sun_up", "hour_sin", "hour_cos"]
LB, HZ = 96, 24

def preproc():
    df["hour"] = ts.dt.hour
    df["dow"] = ts.dt.dayofweek
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["dow_sin"] = np.sin(2 * np.pi * df["dow"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["dow"] / 7)
    sp = StandardScaler().fit(df[df["split"] == "train"][PAST])
    sf = StandardScaler().fit(df[df["split"] == "train"][FUT])
    return sp, sf

sp, sf = preproc()
P = sp.transform(df[PAST]).astype("float32")
F = sf.transform(df[FUT]).astype("float32")
yv = df["pv_n_ISONE"].astype("float32").values
ymean, ystd = float(yv[df["split"].values == "train"].mean()), float(yv[df["split"].values == "train"].std())
split = df["split"].values
back = np.arange(-(LB - 1), 1)
fwd = np.arange(1, HZ + 1)
n = len(df)
idx = np.arange(LB, n - HZ)
idx = idx[(split[idx] == "test") & (split[idx + HZ - 1] == "test")]
Xp = P[idx[:, None] + back[None, :]]
Xf = F[idx[:, None] + fwd[None, :]]
true = yv[idx[:, None] + fwd[None, :]]
t_start = ts.values[idx[:, None] + fwd[None, :]]

past_in = tf.keras.Input((LB, len(PAST)))
fut_in = tf.keras.Input((HZ, len(FUT)))
enc = tf.keras.layers.GRU(128, return_sequences=False, dropout=0.15)(past_in)
ctx = tf.keras.layers.RepeatVector(HZ)(enc)
cat = tf.keras.layers.Concatenate()([ctx, fut_in])
cat = tf.keras.layers.Dense(96, activation="swish")(cat)
cat = tf.keras.layers.Dropout(0.15)(cat)
cat = tf.keras.layers.Dense(64, activation="swish")(cat)
out = tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(1))(cat)
pm = tf.keras.Model(inputs=[past_in, fut_in], outputs=out)
pm.load_weights(str(CKPT))
pred = np.clip(pm.predict([Xp, Xf], batch_size=512, verbose=0)[..., 0] * ystd + ymean, 0, 1)

day = true > 0.002
err = np.abs(true - pred)

# pv11 loss curve
log = pd.read_csv(RUN / "train_log.csv")
fig, ax = plt.subplots(figsize=(9, 4))
ax.plot(log["epoch"] + 1, log["loss"], label="train")
ax.plot(log["epoch"] + 1, log["val_loss"], label="validation")
ax.set_xlabel("Epoch"); ax.set_ylabel("MAE (standardized)")
ax.set_title(f"PV training loss (epochs run: {len(log)})"); ax.legend()
save(fig, "pv11_loss_curves.png")

# pv12 test overlay (first step)
fig, ax = plt.subplots(figsize=(11, 3.6))
tt0 = pd.to_datetime(t_start[:, 0])
ax.plot(tt0, true[:, 0], lw=0.7, label="actual", color="black", alpha=0.7)
ax.plot(tt0, pred[:, 0], lw=0.7, label="predicted", color=C[0], alpha=0.8)
ax.set_xlabel("Date"); ax.set_ylabel("Normalized PV (p.u.)")
ax.set_title("Test period (2026-01..04): 24h-ahead step-1 forecast vs actual")
ax.legend()
save(fig, "pv12_test_overlay.png")

# pv13 two sample days (sunny vs cloudy) via target cloud mean of window
cm = F[idx[:, None] + fwd[None, :], 1]  # cloud_mean standardized col index 1 -> choose raw later
cloud_raw = df["cloud_mean"].values[idx[:, None] + fwd[None, :]]
mean_cloud = cloud_raw.mean(axis=1)
sunny = np.argmin(mean_cloud)
cloudy = np.argmax(mean_cloud)
for k, lab in [(sunny, "sunny day"), (cloudy, "cloudy day")]:
    fig, ax = plt.subplots(figsize=(8.5, 3.6))
    x = np.arange(1, HZ + 1)
    ax.plot(x, true[k], "o-", ms=3, label="actual", color="black")
    ax.plot(x, pred[k], "s--", ms=3, label="predicted", color=C[0])
    ax.set_xlabel("Forecast step (hour ahead)"); ax.set_ylabel("Normalized PV (p.u.)")
    ax.set_title(f"24h PV forecast - {lab} (test set, mean cloud {mean_cloud[k]:.0f}%)")
    ax.legend()
    save(fig, f"pv13_{lab.replace(' ', '_')}.png")

# pv14 scatter actual vs pred (daytime)
fig, ax = plt.subplots(figsize=(6.5, 6))
ax.scatter(true[day], pred[day], s=1.5, alpha=0.2, color=C[0])
lim = [0, 1]
ax.plot(lim, lim, "r--", lw=1)
ax.set_xlabel("Actual normalized PV"); ax.set_ylabel("Predicted (p.u.)")
r2 = 1 - np.sum((true[day] - pred[day]) ** 2) / np.sum((true[day] - true[day].mean()) ** 2)
ax.set_title(f"Predicted vs actual PV, daytime (test), R2={r2:.4f}")
save(fig, "pv14_scatter.png")

# pv15 error by step
fig, ax = plt.subplots(figsize=(9, 3.6))
for k in range(HZ):
    m = day[:, k]
    err_k = err[m, k]
    ax.bar(k + 1, float(err_k.mean()) if len(err_k) else 0)
ax.set_xlabel("Forecast step (1-24 h ahead)"); ax.set_ylabel("Daytime MAE (p.u.)")
ax.set_title("PV forecast daytime MAE by horizon (test)")
save(fig, "pv15_error_by_step.png")

# pv16 error by hour of day
hours = pd.DatetimeIndex(t_start.ravel()).hour.to_numpy().reshape(t_start.shape)
agg = {}
for h in range(24):
    m = day & (hours == h)
    if m.any():
        agg[h] = float(np.mean(np.abs(true[m] - pred[m])))
fig, ax = plt.subplots(figsize=(9, 3.6))
ax.bar(list(agg.keys()), list(agg.values()), color=C[2])
ax.set_xlabel("Hour of day (local)"); ax.set_ylabel("Daytime MAE (p.u.)")
ax.set_title("PV daytime MAE by target hour (test)")
save(fig, "pv16_error_by_hour.png")

# pv17 model vs naive24
naive = np.empty_like(pred)
for k in range(HZ):
    naive[:, k] = yv[idx + k + 1 - 24]
m_naive = np.abs(true[day] - naive[day]).mean()
m_model = float(np.abs(true[day] - pred[day]).mean())
fig, ax = plt.subplots(figsize=(6.5, 4))
ax.bar(["naive-24", "TF model"], [float(m_naive), m_model], color=[C[3], C[0]])
for i, v in enumerate([float(m_naive), m_model]):
    ax.text(i, v + 0.002, f"{v:.4f}", ha="center")
ax.set_ylabel("Daytime MAE (p.u.)")
ax.set_title("PV daytime MAE: model vs persistence (test)")
save(fig, "pv17_model_vs_naive.png")

# index
metrics = json.loads((RUN / "metrics.json").read_text())
idx_md = ["# 光伏预测论文图表索引（PV FIGURES）", "",
          "数据: ISO-NE BTM PV(2014-2026-04) + Open-Meteo ERA5 辐照/云量 + SMD 气象 | 81,768 行",
          "切分: 训练 2017→2025-10(77,424) | 验证 2025-11~12(1,464) | 测试 2026-01~04(2,880)",
          "模型: GRU-128(96h→24h), 100 epochs, 目标=归一化 PV(p.u.)",
          "", "## EDA (pv01-pv10)", ""]
for f, t in [("pv01_overview", "归一化光伏出力序列(2017-2026)与日均线"),
             ("pv02_monthly_box", "按月光伏出力分布箱线"),
             ("pv03_seasonal_curve", "四季平均日光伏曲线"),
             ("pv04_pv_vs_radiation", "光伏出力 vs 太阳辐照(GHI)散点"),
             ("pv05_pv_vs_cloud", "光伏出力 vs 云量散点"),
             ("pv06_coszen_response", "晴空响应：出力 vs 太阳高度"),
             ("pv07_zone_summer", "夏季八分区日光伏曲线"),
             ("pv08_capacity_growth", "MW 装机增长 vs 归一化出力稳定"),
             ("pv09_heatmap_month_hour", "月×时 出力热力图"),
             ("pv10_solstice_days", "二分二至日曲线对比")]:
    idx_md.append(f"- {f}.png - {t}")
idx_md += ["", "## 模型结果 (pv11-pv17, 测试集 2026-01..04)", ""]
idx_md += [f"- pv11_loss_curves.png - 训练/验证损失随轮次",
           "- pv12_test_overlay.png - 测试期第1步预测对照",
           "- pv13_sunny_day.png / pv13_cloudy_day.png - 晴/阴天 24h 预测对照",
           "- pv14_scatter.png - 预测-实际散点(白天)",
           "- pv15_error_by_step.png - 各步长白天 MAE",
           "- pv16_error_by_hour.png - 各钟点白天 MAE",
           "- pv17_model_vs_naive.png - 模型 vs naive-24 白天 MAE"]
idx_md += ["", "## 指标速查 (runs/pv_v1/metrics.json)", ""]
idx_md += [f"- 测试全时段 MAE {metrics['test']['MAE']} / RMSE {metrics['test']['RMSE']}",
           f"- 测试白天 MAE {metrics['test']['daytime_MAE']} (nMAE {metrics['test']['daytime_nMAE']})",
           f"- naive-24 白天 MAE(测试) {metrics['naive24_daytime_MAE']}",
           f"- 验证白天 MAE {metrics['val']['daytime_MAE']} | 训练轮数 {metrics['epochs_done']}"]
(FIG / "FIGURES_INDEX.md").write_text("\n".join(idx_md), encoding="utf-8")
print("\nTOTAL PV figures:", len(made), "+ index")
