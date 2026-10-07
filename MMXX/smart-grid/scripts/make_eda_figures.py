# -*- coding: utf-8 -*-
"""
smart-grid / scripts/make_eda_figures.py
========================================
Generate thesis-ready EDA figures from processed data (>=16 charts).
Figures -> figures/thesis/figNN_*.png  (English labels, clean thesis style)
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
FIG = ROOT / "figures" / "thesis"
FIG.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"figure.dpi": 150, "savefig.dpi": 150, "font.size": 9,
                     "axes.titlesize": 11, "axes.labelsize": 9.5, "legend.fontsize": 8,
                     "axes.grid": True, "grid.alpha": 0.3})
C = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f"]

df = pd.read_parquet(PROC / "ca_features.parquet").sort_values("seq").reset_index(drop=True)
ts = pd.to_datetime(df["ts_local"])
zone = pd.read_parquet(PROC / "zone_hourly.parquet")
wet = pd.read_parquet(PROC / "zone_weather_wide.parquet")
ZONES = ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]

made = []
rt = df["RT_Demand"]
p_rt = df["RT_LMP"]
p_da = df["DA_LMP"]


def save(fig, name):
    p = FIG / name
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    made.append(str(p.name))
    print("saved", p.name)


# fig01 overview
fig, ax = plt.subplots(figsize=(11, 3.6))
ax.plot(ts, rt, lw=0.25, color=C[0], label="hourly RT demand")
daily = rt.groupby(ts.dt.date).mean()
ax.plot(pd.to_datetime(daily.index), daily.values, lw=1.1, color="#d62728", label="daily mean")
ax.set_xlabel("Date"); ax.set_ylabel("RT demand (MW)")
ax.set_title("ISO-NE control-area real-time demand, hourly 2024-01 - 2026-07")
ax.legend(loc="upper left", ncol=2)
save(fig, "fig01_rt_overview.png")

# fig02 monthly box
fig, ax = plt.subplots(figsize=(10, 3.6))
d2 = pd.DataFrame({"rt": rt, "ym": df["date"].dt.to_period("M").astype(str)})
d2.boxplot(column="rt", by="ym", ax=ax, showfliers=False, rot=90, fontsize=6.5)
ax.set_title("RT demand by month"); ax.set_xlabel(""); ax.set_ylabel("MW"); fig.suptitle("")
plt.setp(ax.get_xticklabels(), rotation=90, fontsize=6.5)
save(fig, "fig02_rt_by_month_box.png")

# fig03 hourly profile by day type
fig, ax = plt.subplots(figsize=(9, 3.6))
g = df.groupby(["dow", "clock_hour"])["RT_Demand"].mean().unstack(0)
wd = g[[0, 1, 2, 3, 4]].mean(axis=1)
we = g[[5, 6]].mean(axis=1)
hol = df[df["is_holiday"] == 1].groupby("clock_hour")["RT_Demand"].mean()
ax.plot(range(24), wd, label="weekday", color=C[0])
ax.plot(range(24), we, label="weekend", color=C[1])
ax.plot(hol.index, hol.values, label="holiday", color=C[3], lw=2, ls="--")
ax.set_xlabel("Hour of day (local)"); ax.set_ylabel("Mean RT demand (MW)"); ax.legend()
ax.set_title("Average daily load profile by day type (2024-2026)")
ax.set_xticks(range(0, 24, 2))
save(fig, "fig03_daily_profile_daytype.png")

# fig04 load vs temperature
fig, ax = plt.subplots(figsize=(8, 4.2))
db = df["Dry_Bulb"]
sc = ax.scatter(db, rt, s=2, c=df["month"], cmap="coolwarm", alpha=0.35)
ax.set_xlabel("CA weighted dry-bulb temperature (degF)")
ax.set_ylabel("RT demand (MW)")
ax.set_title("Load vs temperature (U-shape; colored by month)")
cb = fig.colorbar(sc, ax=ax, label="month"); cb.ax.invert_yaxis()
x = np.linspace(db.min(), db.max(), 100)
ax.plot(x, np.polyval(np.polyfit(db, rt, 2), x), color="black", lw=2, label="quadratic fit")
ax.legend()
save(fig, "fig04_load_vs_temperature.png")

# fig05 hourly x dow heatmap
fig, ax = plt.subplots(figsize=(8, 3.8))
hm = g.T  # dow rows, hour cols -> transpose to hour x dow
im = ax.imshow(hm.T.values, aspect="auto", cmap="viridis")
ax.set_yticks(range(7), labels=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
ax.set_xlabel("Hour of day"); ax.set_ylabel("Day of week")
ax.set_title("Mean RT demand heatmap: hour-of-day x day-of-week")
fig.colorbar(im, ax=ax, label="MW")
save(fig, "fig05_heatmap_hour_dow.png")

# fig06 price overview
fig, ax = plt.subplots(figsize=(11, 3.6))
ax.plot(ts, p_rt, lw=0.2, color=C[0], label="RT LMP")
ax.plot(ts, p_da, lw=0.2, color=C[1], alpha=0.6, label="DA LMP")
daily_p = pd.DataFrame({"rt": p_rt, "da": p_da, "d": ts.dt.date}).groupby("d").median()
ax.plot(pd.to_datetime(daily_p.index), daily_p["rt"], lw=1.0, color="#d62728", label="RT daily median")
ax.set_xlabel("Date"); ax.set_ylabel("LMP ($/MWh)")
ax.set_title("Trading-hub day-ahead and real-time prices (hourly)")
ax.legend(loc="upper left", ncol=3)
ax.set_ylim(-50, 500)
save(fig, "fig06_price_overview.png")

# fig07 price hourly profile
fig, ax = plt.subplots(figsize=(9, 3.6))
gp = df.groupby(["dow", "clock_hour"])["RT_LMP"].median().unstack(0)
ax.plot(range(24), gp[[0, 1, 2, 3, 4]].mean(axis=1), label="weekday median")
ax.plot(range(24), gp[[5, 6]].mean(axis=1), label="weekend median")
ax.set_xlabel("Hour of day"); ax.set_ylabel("Median RT LMP ($/MWh)"); ax.legend()
ax.set_title("Real-time price profile by day type")
ax.set_xticks(range(0, 24, 2))
save(fig, "fig07_price_profile.png")

# fig08 price distribution
fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
for ax, s, nm in ((axes[0], p_rt, "RT LMP"), (axes[1], p_da, "DA LMP")):
    ax.hist(np.clip(s, 0, 300), bins=100, color=C[0], alpha=0.8)
    ax.axvline(100, color="red", ls="--", lw=1, label="100 $/MWh")
    ax.set_xlabel("$ / MWh"); ax.set_ylabel("hours"); ax.set_title(f"{nm} distribution")
    ax.legend()
save(fig, "fig08_price_hist.png")

# fig09 DA vs RT demand
fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), gridspec_kw={"width_ratios": [1.1, 1]})
axes[0].scatter(df["DA_Demand"], rt, s=1.5, alpha=0.3)
lim = [rt.min() * 0.9, rt.max() * 1.05]
axes[0].plot(lim, lim, "r--", lw=1)
axes[0].set_xlabel("DA cleared demand (MW)"); axes[0].set_ylabel("RT demand (MW)")
axes[0].set_title("DA vs RT demand")
diff = (df["DA_Demand"] - rt)
axes[1].hist(diff, bins=80, color=C[1])
axes[1].set_xlabel("DA - RT (MW)"); axes[1].set_title("Clearing-vs-realised spread")
save(fig, "fig09_da_rt_demand.png")

# fig10 zone profiles
fig, axes = plt.subplots(2, 4, figsize=(11, 5.2), sharex=True, sharey=True)
for i, z in enumerate(ZONES):
    ax = axes.flat[i]
    zd = zone[zone["zone"] == z].copy()
    zd["dow"] = pd.to_datetime(zd["ts_local"]).dt.dayofweek
    gp = zd.groupby(["dow", "clock_hour"])["RT_Demand"].mean().unstack(0)
    ax.plot(range(24), gp[[0, 1, 2, 3, 4]].mean(axis=1), label="WD", lw=1.2)
    ax.plot(range(24), gp[[5, 6]].mean(axis=1), label="WE", lw=1.2)
    ax.set_title(z, fontsize=9)
    if i in (4, 5, 6, 7):
        ax.set_xlabel("hour")
    if i % 4 == 0:
        ax.set_ylabel("MW")
fig.suptitle("Zone-level mean load profiles")
axes.flat[0].legend(fontsize=7)
fig.tight_layout()
save(fig, "fig10_zone_profiles.png")

# fig11 zone shares
fig, ax = plt.subplots(figsize=(8, 3.4))
sh = zone.groupby("zone")["RT_Demand"].mean().loc[ZONES]
ax.bar(sh.index, sh.values, color=C[:8])
ax.set_ylabel("Mean RT demand (MW)"); ax.set_title("Mean load level by zone (2024-2026)")
for i, v in enumerate(sh.values):
    ax.text(i, v + 40, f"{v:.0f}", ha="center", fontsize=8)
save(fig, "fig11_zone_levels.png")

# fig12 station weather monthly heatmap
fig, ax = plt.subplots(figsize=(8, 4.0))
wcols = [f"Dry_Bulb_{z}" for z in ZONES]
mm = wet.copy()
mm["ym"] = pd.to_datetime(wet["ts_local"]).dt.to_period("M")
tab = mm.groupby("ym")[wcols].mean().T
im = ax.imshow(tab.values, aspect="auto", cmap="RdYlBu_r", vmin=20, vmax=80)
ax.set_yticks(range(8), labels=ZONES)
ax.set_xticks(range(0, len(tab), 3), [str(x) for x in tab.index[::3]], rotation=45, fontsize=7)
ax.set_title("Monthly mean dry-bulb temperature by zone station (degF)")
fig.colorbar(im, ax=ax, label="degF")
save(fig, "fig12_station_weather.png")

# fig13 autocorrelation of load
fig, ax = plt.subplots(figsize=(8, 3.6))
lagmax = 7 * 24
r = pd.Series(rt)
ac = np.array([r.autocorr(lag) for lag in range(0, lagmax + 1, 6)])
ax.plot(np.arange(0, lagmax + 1, 6) / 24, ac, marker="o", ms=2.5)
ax.axhline(0, color="k", lw=0.8)
ax.set_xlabel("Lag (days)"); ax.set_ylabel("Autocorrelation")
ax.set_title("Autocorrelation of hourly RT demand (peaks at 1 & 7 days)")
save(fig, "fig13_acf_load.png")

# fig14 holiday effect
fig, ax = plt.subplots(figsize=(9, 3.6))
hol_name = df[df["holiday_name"] != ""]
for name in ["Christmas", "Independence Day", "Thanksgiving", "New Year"]:
    s = hol_name[hol_name["holiday_name"] == name].groupby("clock_hour")["RT_Demand"].mean()
    if len(s):
        ax.plot(s.index, s.values, label=name, lw=1.8)
ax.plot(range(24), wd, label="normal weekday", color="k", lw=1.2, ls="--")
ax.set_xlabel("Hour of day"); ax.set_ylabel("RT demand (MW)"); ax.legend(ncol=2)
ax.set_title("Load profile on major holidays vs normal weekday")
ax.set_xticks(range(0, 24, 2))
save(fig, "fig14_holiday_effect.png")

# fig15 train/val/test
fig, ax = plt.subplots(figsize=(11, 3.6))
col = {"train": "#c6dbef", "val": "#9ecae1", "test": "#fdbe85"}
dts = pd.to_datetime(ts.dt.normalize().values)
ax.plot(ts, rt, lw=0.25, color=C[0])
for part in ("train", "val", "test"):
    seg = df[df["split"] == part]
    if len(seg):
        t0 = pd.to_datetime(seg["ts_local"]).min()
        t1 = pd.to_datetime(seg["ts_local"]).max()
        ax.axvspan(t0, t1, color=col[part], alpha=0.5, label=f"{part} ({len(seg)})")
ax.legend(loc="upper left", ncol=3)
ax.set_xlabel("Date"); ax.set_ylabel("RT demand (MW)")
ax.set_title("Dataset split: train / validation (2026-06) / test (2026-07)")
save(fig, "fig15_split_timeline.png")

# fig16 seasonal daily profiles
fig, ax = plt.subplots(figsize=(9, 3.8))
mmap = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
        6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}
dd = df.copy()
dd["season"] = dd["date"].dt.month.map(mmap)
for i, (sn, colr) in enumerate([("DJF", "#1f77b4"), ("MAM", "#2ca02c"), ("JJA", "#d62728"), ("SON", "#ff7f0e")]):
    s = dd[dd["season"] == sn].groupby("clock_hour")["RT_Demand"].mean()
    ax.plot(range(24), s.values, label=sn, color=colr, lw=1.8)
ax.set_xlabel("Hour of day"); ax.set_ylabel("Mean RT demand (MW)"); ax.legend()
ax.set_title("Mean daily load curve by meteorological season")
ax.set_xticks(range(0, 24, 2))
save(fig, "fig16_seasonal_profiles.png")

print(f"\nTOTAL EDA figures: {len(made)}")
