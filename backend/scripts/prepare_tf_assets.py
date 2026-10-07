# -*- coding: utf-8 -*-
"""
prepare_tf_assets.py — 把 MMXX 训练产物接入 backend 的“离线资产准备”
====================================================================

不做任何训练。只做三件事：
  1) 读取 MMXX 重建好的特征表 (ca_features.parquet / pv_features.parquet)，
     按训练脚本同款逻辑在 train 段 (ts_local < 2025-11-01) 拟合 StandardScaler，
     把 mean_/scale_ 冻结导出为 JSON（训练脚本从不落盘 scaler，这是接入前提）；
  2) 抽取“尾部特征行”存成 parquet（后端运行时历史窗口的数据源，锚定数据尾部演示预测）；
  3) 把两个 *.weights.h5 拷贝到 backend 资产目录（原文件保留在 MMXX 不动）。

依赖 MMXX stage 链输出：MMXX/smart-grid/data/processed/ca_features.parquet
  + pv_features.parquet（先跑 stage1_build_canonical.py / stage2_build_features.py /
  stage_pv_build.py）。输出：backend/models/tf_assets/...

用法: cd backend && python scripts/prepare_tf_assets.py
作者: 毕业设计项目
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.tensorflow_load import tf_v2_models, tf_pv_models  # noqa: E402

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parents[0]
MMXX_SG = ROOT / "MMXX" / "smart-grid"
PROC = MMXX_SG / "data" / "processed"
MMXX_MODELS = MMXX_SG / "models"
BTM_XLSX = MMXX_SG / "data" / "raw" / "btm_pv_data.xlsx"

DEST = BACKEND / "models" / "tf_assets"
DEST_TF2 = DEST / "tf_v2"
DEST_PV = DEST / "pv_v1"
SPLIT_BOUND = pd.Timestamp("2025-11-01")          # 训练段边界 (与 stage2 一致)

ZONES = ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]


def _to_dict(sc: StandardScaler, cols) -> dict:
    return {
        "cols": list(cols),
        "mean": [round(float(x), 12) for x in np.asarray(sc.mean_).ravel()],
        "scale": [round(float(x), 12) for x in np.asarray(sc.scale_).ravel()],
        "n_features_in": int(getattr(sc, "n_features_in_", len(cols))),
    }


# ---------------------------------------------------------------------------
# 1) tf_v2: 负荷 + 电价
# ---------------------------------------------------------------------------
def prepare_tf2() -> tuple[pd.DataFrame, str]:
    ca = pd.read_parquet(PROC / "ca_features.parquet").sort_values("seq").reset_index(drop=True)
    ca["rt_yest"] = ca["RT_Demand"].shift(24)
    ca["price_log"] = np.log1p(np.maximum(ca["RT_LMP"], 0.0))
    tr = ca[ca["split"] == "train"]
    sp = StandardScaler().fit(tr[tf_v2_models.PAST_COLS].dropna())
    sf = StandardScaler().fit(tr[tf_v2_models.FUT_COLS].dropna())
    sl = StandardScaler().fit(tr[["RT_Demand"]])
    sy = StandardScaler().fit(tr[["price_log"]])
    return ca, json.dumps({
        "version": 1,
        "model": "tf_v2",
        "note": "GRU192 负荷(RT_Demand)+电价分位(price_log=log1p(max(RT_LMP,0)))",
        "lookback": tf_v2_models.LOOKBACK,
        "horizon": tf_v2_models.HORIZON,
        "past_cols": tf_v2_models.PAST_COLS,
        "fut_cols": tf_v2_models.FUT_COLS,
        "scaler": {
            "sp": _to_dict(sp, tf_v2_models.PAST_COLS),
            "sf": _to_dict(sf, tf_v2_models.FUT_COLS),
            "sl": _to_dict(sl, ["RT_Demand"]),
            "sy": _to_dict(sy, ["price_log"]),
        },
        "decode_note": "load=sl.inverse; price=expm1(sy.inverse) 通道=p10/p50/p90",
    }, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------
# 2) pv_v1: 光伏 (p.u.)
# ---------------------------------------------------------------------------
def prepare_pv() -> tuple[pd.DataFrame, str]:
    pv = pd.read_parquet(PROC / "pv_features.parquet").sort_values("ts_start").reset_index(drop=True)
    pv["temp_mean"] = pv[[f"temp_{z}" for z in ZONES]].mean(axis=1)
    hr = pd.to_datetime(pv["ts_start"]).dt
    pv["hour_sin"] = np.sin(2 * np.pi * hr.hour / 24)
    pv["hour_cos"] = np.cos(2 * np.pi * hr.hour / 24)
    pv["dow_sin"] = np.sin(2 * np.pi * hr.dayofweek / 7)
    pv["dow_cos"] = np.cos(2 * np.pi * hr.dayofweek / 7)
    tr = pv[pv["split"] == "train"]
    sp = StandardScaler().fit(tr[tf_pv_models.PAST_COLS])
    sf = StandardScaler().fit(tr[tf_pv_models.FUT_COLS])
    y = pv["pv_n_ISONE"].astype("float64")
    ytr = y[pv["split"] == "train"]
    ymean, ystd = float(ytr.mean()), float(ytr.std())

    # 旧资产兼容后备值：pv_mw_ISONE / pv_n_ISONE 的近期比率。
    # 生产推理不再把它当作永久固定装机容量；2026+ 使用 ISO-NE CELT
    # 随日期变化的官方 BTM PV AC nameplate 容量。
    capacity_mw = None
    try:
        raw = pd.read_excel(BTM_XLSX, sheet_name="BTM PV")
        norm = pd.read_excel(BTM_XLSX, sheet_name="Normalized BTM PV")
        ratio = pd.to_numeric(raw["ISONE"], errors="coerce") / \
            pd.to_numeric(norm["ISONE"], errors="coerce").replace(0, np.nan)
        mask = (pd.to_numeric(norm["ISONE"], errors="coerce") > 0.2) & ratio.notna()
        # 取 2026 年(数据尾部)的中位数作为当前容量基准
        yr = pd.to_datetime(dict(year=raw["Year"], month=raw["Month"], day=raw["Day"]),
                            errors="coerce").dt.year
        tail_mask = mask & (yr == yr.max())
        capacity_mw = float(np.median(ratio[tail_mask])) if tail_mask.any() else \
            float(np.percentile(ratio[mask], 99))
        print(f"  [pv] 容量基准估计: {capacity_mw:.1f} MW (ratio pv_mw/pv_n)")
    except Exception as e:  # noqa: BLE001
        print(f"  [pv] 容量估计失败(将用 p.u. 输出): {e}")

    return pv, json.dumps({
        "version": 2,
        "model": "pv_v1",
        "note": "GRU128 归一化 ISO-NE BTM 光伏 pv_n_ISONE, 输出 p.u. 0..1",
        "solar_geometry": "noaa_local_v2",
        "lookback": tf_pv_models.LOOKBACK,
        "horizon": tf_pv_models.HORIZON,
        "past_cols": tf_pv_models.PAST_COLS,
        "fut_cols": tf_pv_models.FUT_COLS,
        "scaler": {
            "sp": _to_dict(sp, tf_pv_models.PAST_COLS),
            "sf": _to_dict(sf, tf_pv_models.FUT_COLS),
        },
        "y": {"mean": ymean, "std": ystd},
        "capacity_mw": capacity_mw,
        "capacity_strategy": "asset fallback; production uses ISO-NE 2026 CELT date-aligned capacity",
        "decode_note": (
            "p_u=clip(out*std+mean,0,1); production MW uses the "
            "timestamp-aligned ISO-NE CELT BTM PV capacity"
        ),
    }, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------
# 3) 统一锚点 (数据尾部, 小时起点语义 H0)
# ---------------------------------------------------------------------------
def pick_anchor(ca, pv) -> pd.Timestamp:
    pv_last = pd.Timestamp(pv["ts_start"].max())            # 小时起点标签
    ca_last = pd.Timestamp(ca["ts_local"].max())            # 小时结束标签
    # ca 需覆盖到 H0+25(小时结束); pv 需覆盖到 H0+24(小时起点)
    # H0 上限 = min(pv_last-24h, ca_last-25h)
    h0_max = min(pv_last - pd.Timedelta(hours=24),
                 ca_last - pd.Timedelta(hours=25))
    h0 = h0_max.floor("h")
    print(f"  [anchor] ca_last={ca_last} pv_last={pv_last} -> origin H0={h0}")
    return h0


def main() -> None:
    print("=" * 70)
    print("prepare_tf_assets: 冻结 scaler + 尾部特征 + 拷贝权重 (不训练)")
    print("=" * 70)
    DEST_TF2.mkdir(parents=True, exist_ok=True)
    DEST_PV.mkdir(parents=True, exist_ok=True)

    # 权重拷贝 (原文件保留)
    for name, src, dst in [
        ("tf_v2", MMXX_MODELS / "tf_v2_best.weights.h5", DEST_TF2 / "tf_v2_best.weights.h5"),
        ("pv_v1", MMXX_MODELS / "pv_v1_best.weights.h5", DEST_PV / "pv_v1_best.weights.h5"),
    ]:
        if not src.exists():
            raise SystemExit(f"缺少权重: {src}")
        shutil.copy2(src, dst)
        print(f"  [copy] {name}: {src.name} -> {dst}")

    print("[1/3] tf_v2 scaler ...")
    ca, tf2_json = prepare_tf2()
    print("[2/3] pv_v1 scaler ...")
    pv, pv_json = prepare_pv()
    h0 = pick_anchor(ca, pv)

    # 尾部特征行: 需覆盖 168(96) 历史 + 24 未来 + 余量; 用锚点前 240 行起存
    ca["ts_local_dt"] = pd.to_datetime(ca["ts_local"])
    pv["ts_start_dt"] = pd.to_datetime(pv["ts_start"])

    ca_origin = h0 + pd.Timedelta(hours=1)          # tf_v2 origin 行 (小时结束标签)
    ca_rows = ca[ca["ts_local_dt"] >= (ca_origin - pd.Timedelta(hours=240))].copy()
    _tf2_cols = tf_v2_models.PAST_COLS + [c for c in tf_v2_models.FUT_COLS
                                          if c not in tf_v2_models.PAST_COLS]
    ca_rows = ca_rows[["ts_local_dt", "split"] + _tf2_cols]
    ca_rows = ca_rows.rename(columns={"ts_local_dt": "ts_local"})
    ca_rows.to_parquet(DEST_TF2 / "ca_tail.parquet", index=False)

    pv_origin = h0                               # pv origin 行 (小时起点标签)
    pv_rows = pv[pv["ts_start_dt"] >= (pv_origin - pd.Timedelta(hours=200))].copy()
    _pv_cols = tf_pv_models.PAST_COLS + [c for c in tf_pv_models.FUT_COLS
                                         if c not in tf_pv_models.PAST_COLS]
    keep_cols = ["ts_start_dt", "split"] + _pv_cols
    pv_rows = pv_rows[keep_cols].rename(columns={"ts_start_dt": "ts_start"})
    pv_rows.to_parquet(DEST_PV / "pv_tail.parquet", index=False)

    meta = {
        "tf_v2": {
            "weights": "models/tf_assets/tf_v2/tf_v2_best.weights.h5",
            "scalers_json": "models/tf_assets/tf_v2/scalers.json",
            "tail": "models/tf_assets/tf_v2/ca_tail.parquet",
            "origin_ts_local": str(ca_origin),
            "params": 159524,
        },
        "pv_v1": {
            "weights": "models/tf_assets/pv_v1/pv_v1_best.weights.h5",
            "scalers_json": "models/tf_assets/pv_v1/scalers.json",
            "tail": "models/tf_assets/pv_v1/pv_tail.parquet",
            "origin_ts_start": str(pv_origin),
            "params": 73857,
        },
    }

    # 写出 JSON
    (DEST_TF2 / "scalers.json").write_text(tf2_json, encoding="utf-8")
    (DEST_PV / "scalers.json").write_text(pv_json, encoding="utf-8")
    (DEST / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    print()
    print("输出资产:")
    for f in sorted(DEST.rglob("*")):
        if f.is_file():
            print(f"   {f.relative_to(ROOT)}  ({f.stat().st_size / 1024:.0f} KB)")
    print("scaler 冻结完成 (scaler 为确定性拟合, 一次性生成, 运行时直接读取)")


if __name__ == "__main__":
    main()
