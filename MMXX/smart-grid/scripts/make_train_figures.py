# -*- coding: utf-8 -*-
"""
smart-grid / scripts/make_train_figures.py
==========================================
Thesis figures from TF training outputs (runs/tf_v1) + EDA set already made.
Run AFTER scripts/train_tf.py finishes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / os.environ.get("FIG_TAG", "tf_v3")
FIG = ROOT / "figures" / "thesis"
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


def load_pred(tag):
    z = np.load(RUN / f"preds_{tag}.npz")
    return z["y_load"], z["p_load"], z["y_price"], z["p_q"]


# ---- recreate test origin metadata (same rule as train_tf.py) -------------
df = pd.read_parquet(ROOT / "data" / "processed" / "ca_features.parquet").sort_values("seq").reset_index(drop=True)
ts = pd.to_datetime(df["ts_local"])
HORIZON = 24
idx = np.arange(168 + 24, len(df) - HORIZON)
mask_t = (df["split"].values[idx] == "test") & (df["split"].values[idx + HORIZON - 1] == "test")
test_pos = idx[mask_t]
ts_np = ts.to_numpy()
tgt_ts = ts_np[test_pos[:, None] + np.arange(1, HORIZON + 1)[None, :]]      # (n,24) datetime64
loc_hour = (pd.DatetimeIndex(tgt_ts.ravel()).hour.to_numpy() - 1) % 24
loc_hour = loc_hour.reshape(tgt_ts.shape)

# ---- 1 loss curves ---------------------------------------------------------
log = pd.read_csv(RUN / "train_log.csv")
fig, ax = plt.subplots(figsize=(9, 4))
ax.plot(log["epoch"] + 1, log["loss"], label="train total", color=C[0])
ax.plot(log["epoch"] + 1, log["val_loss"], label="validation total", color=C[1])
ax.set_xlabel("Epoch"); ax.set_ylabel("Combined loss (load MAE + 0.6 x price pinball)")
ax.set_title("Training / validation loss (epochs actually run: %d)" % len(log))
ax.legend()
save(fig, "fig17_loss_curves.png")

# ---- load predictions ------------------------------------------------------
y_load, p_load, y_price, p_q = load_pred("test")
y_load_v, p_load_v, _, _ = load_pred("val")

def mae(a, b):
    return np.mean(np.abs(a - b))


# 2 whole-test overlay
fig, ax = plt.subplots(figsize=(11, 3.6))
ax.plot(tgt_ts[:, 0], y_load[:, 0] / 1000, lw=0.8, label="actual", color="black", alpha=0.7)
ax.plot(tgt_ts[:, 0], p_load[:, 0] / 1000, lw=0.8, label="predicted", color=C[0], alpha=0.8)
ax.set_xlabel("Date (24h-ahead origin of first step)"); ax.set_ylabel("RT demand (GW)")
ax.set_title("Test period (July 2026): 24h-ahead forecast vs actual, first step")
ax.legend()
save(fig, "fig18_test_overlay_step1.png")

# 3 example days (spike day 07-02, weekday 07-09, weekend 07-12)
def day_plot(D, fname, price=False):
    k = np.where(tgt_ts[:, 0] == pd.Timestamp(D))[0]
    if len(k) == 0:
        print("skip", D); return
    k = k[0]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    x = np.arange(24)
    ax.plot(x, y_load[k] / 1000, "o-", ms=3, label="actual", color="black")
    ax.plot(x, p_load[k] / 1000, "s--", ms=3, label="predicted", color=C[0])
    ax.set_xlabel("Hour of day"); ax.set_ylabel("RT demand (GW)")
    ax.set_title(f"24h-ahead load forecast on {D} (test set)")
    ax.legend()
    save(fig, fname)

day_plot("2026-07-02", "fig19_day_spike_20260702.png")
day_plot("2026-07-09", "fig20_day_weekday_20260709.png")
day_plot("2026-07-12", "fig21_day_weekend_20260712.png")

# 4 scatter actual vs predicted (all steps, test)
fig, ax = plt.subplots(figsize=(6.5, 6))
ax.scatter(y_load.ravel() / 1000, p_load.ravel() / 1000, s=1.2, alpha=0.25, color=C[0])
lim = [y_load.min() / 1000 * 0.95, y_load.max() / 1000 * 1.05]
ax.plot(lim, lim, "r--", lw=1)
ax.set_xlabel("Actual RT demand (GW)"); ax.set_ylabel("Predicted (GW)")
ax.set_title("Predicted vs actual load, all 24 steps, test set")
save(fig, "fig22_scatter_pred_actual.png")

# 5 error by forecast step
rmse_h = np.sqrt(np.mean((y_load - p_load) ** 2, axis=0))
mae_h = np.mean(np.abs(y_load - p_load), axis=0)
fig, ax = plt.subplots(figsize=(9, 3.6))
ax.bar(np.arange(1, 25) - 0.2, mae_h, width=0.4, label="MAE", color=C[0])
ax.bar(np.arange(1, 25) + 0.2, rmse_h, width=0.4, label="RMSE", color=C[2])
ax.set_xlabel("Forecast step (1-24 h ahead)"); ax.set_ylabel("Error (MW)")
ax.set_title("Load forecast error by horizon (test set)")
ax.legend()
save(fig, "fig23_error_by_horizon.png")

# 6 error by local hour
err = (y_load - p_load).ravel()
hh = loc_hour.ravel()
agg = pd.DataFrame({"err": np.abs(err), "h": hh}).groupby("h")["err"].mean()
fig, ax = plt.subplots(figsize=(9, 3.6))
ax.bar(agg.index, agg.values, color=C[1])
ax.set_xlabel("Local clock hour of the forecasted hour"); ax.set_ylabel("MAE (MW)")
ax.set_title("Load forecast MAE by target hour of day (test set)")
save(fig, "fig24_error_by_clock_hour.png")

# 7 residual histogram
fig, ax = plt.subplots(figsize=(7.5, 4))
ax.hist((y_load - p_load).ravel(), bins=90, color=C[0])
ax.axvline(0, color="red", lw=1)
ax.set_xlabel("Residual actual - predicted (MW)"); ax.set_ylabel("hours")
ax.set_title("Load residual distribution (test set)")
save(fig, "fig25_residual_hist.png")

# 8 price fan chart on spike day and a normal day
def price_fan(D, fname):
    k = np.where(tgt_ts[:, 0] == pd.Timestamp(D))[0]
    if len(k) == 0:
        print("skip price", D); return
    k = k[0]
    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(24)
    ax.plot(x, y_price[k], "ko-", ms=3, label="actual RT LMP", lw=1)
    ax.plot(x, p_q[k, :, 1], "s--", ms=3, label="p50 forecast", color=C[0])
    ax.fill_between(x, p_q[k, :, 0], p_q[k, :, 2], alpha=0.25, color=C[0], label="p10-p90 band")
    ax.set_xlabel("Hour of day"); ax.set_ylabel("$/MWh")
    ax.set_title(f"Probabilistic RT price forecast on {D} (test set)")
    ax.legend()
    save(fig, fname)

price_fan("2026-07-02", "fig26_price_fan_spike.png")
price_fan("2026-07-09", "fig27_price_fan_normal.png")

# 9 quantile calibration (test, pooled over horizons)
below10 = np.mean(y_price < p_q[..., 0])
between = np.mean((y_price >= p_q[..., 0]) & (y_price <= p_q[..., 2]))
above90 = np.mean(y_price > p_q[..., 2])
fig, ax = plt.subplots(figsize=(6.5, 4))
names = ["< p10", "p10-p90", "> p90"]
obs = [below10, between, above90]
nom = [0.1, 0.8, 0.1]
x = np.arange(3)
ax.bar(x - 0.2, nom, width=0.4, label="nominal", color="gray")
ax.bar(x + 0.2, obs, width=0.4, label="observed", color=C[0])
ax.set_xticks(x, names); ax.set_ylabel("Fraction of hours"); ax.legend()
ax.set_title("Price quantile calibration (test set)")
for i, v in enumerate(obs):
    ax.text(i + 0.2, v + 0.01, f"{v:.3f}", ha="center", fontsize=8)
save(fig, "fig28_price_calibration.png")

# 10 val vs test load MAE bar (DA baseline computed from data for the same partitions)
metrics = json.loads((RUN / "metrics.json").read_text(encoding="utf-8"))
def da_mae(part):
    m = df["split"] == part
    return float(np.mean(np.abs(df.loc[m, "DA_Demand"] - df.loc[m, "RT_Demand"])))
fig, ax = plt.subplots(figsize=(6.5, 4))
names = ["val", "test"]
maes = [metrics["val"]["load_MAE_MW"], metrics["test"]["load_MAE_MW"]]
da_bar = [da_mae("val"), da_mae("test")]
x = np.arange(2)
ax.bar(x - 0.2, maes, width=0.4, label="TF model MAE", color=C[0])
ax.bar(x + 0.2, da_bar, width=0.4, label="DA baseline MAE", color=C[3])
ax.set_xticks(x, names); ax.set_ylabel("MAE (MW)")
ax.set_title("Model vs DA baseline on validation / test")
ax.legend()
for i, (a, b) in enumerate(zip(maes, da_bar)):
    ax.text(i - 0.2, a + 8, f"{a:.0f}", ha="center"); ax.text(i + 0.2, b + 8, f"{b:.0f}", ha="center")
save(fig, "fig29_model_vs_baseline.png")

print(f"\nTOTAL training-result figures: {len(made)}")
