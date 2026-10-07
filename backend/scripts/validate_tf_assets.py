#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验生产 TensorFlow 负荷/价格与光伏资产，不训练、不改写任何资产。

默认执行静态校验（HDF5、Scaler、Parquet 与特征契约）。
安装好 TensorFlow 后使用 ``--runtime`` 额外完成模型加载和一次确定性推理。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import h5py
import numpy as np
import pandas as pd


BACKEND = Path(__file__).resolve().parents[1]
ASSETS = BACKEND / "models" / "tf_assets"

PV_ZONES = ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]
PV_WEATHER = (
    [f"ghi_{zone}" for zone in PV_ZONES]
    + [f"cloud_{zone}" for zone in PV_ZONES]
    + ["temp_mean", "dew_mean"]
)
PV_COMMON = PV_WEATHER + [
    "coszen", "sun_up", "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "doy_sin", "doy_cos", "trend_days",
]
PV_PAST = PV_COMMON + ["pv_mw_ISONE"]
PV_FUTURE = PV_COMMON

SPLIT_LOAD_PAST = [
    "RT_Demand", "DA_Demand", "RT_LMP", "DA_LMP", "Dry_Bulb", "Dew_Point",
    "hdd65", "cdd65", "temp_mem", "clock_hour_sin", "clock_hour_cos", "dow_sin",
    "dow_cos", "month_sin", "month_cos", "is_holiday", "is_dst", "rt_lag24",
    "rt_lag168", "rt_prev24_mean", "rt_prev168_mean",
]
SPLIT_PRICE_PAST = SPLIT_LOAD_PAST + [
    "rtlmp_lag1", "rtlmp_lag24", "rtlmp_lag168", "rtlmp_prev24_mean", "da_lmp_lag24",
]
SPLIT_FUTURE = [
    "DA_Demand", "DA_LMP", "Dry_Bulb", "Dew_Point", "hdd65", "cdd65", "temp_mem",
    "clock_hour_sin", "clock_hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
    "is_holiday", "holiday_shoulder", "is_dst", "rt_yest",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_h5(path: Path) -> None:
    require(path.is_file() and path.stat().st_size > 0, f"权重缺失或为空: {path}")
    with h5py.File(path, "r") as handle:
        require("layers" in handle and "vars" in handle, f"不是 Keras 3 weights.h5: {path}")
        datasets: list[tuple[str, tuple[int, ...]]] = []

        def collect(name, obj):
            if isinstance(obj, h5py.Dataset):
                datasets.append((name, tuple(obj.shape)))

        handle.visititems(collect)
        require(datasets, f"HDF5 中没有权重张量: {path}")
        require(all(np.prod(shape) > 0 for _, shape in datasets), f"存在空权重张量: {path}")
    print(f"[PASS] HDF5 {path.name}: {len(datasets)} tensors")


def check_scaler(path: Path, past_cols: list[str], future_cols: list[str]) -> dict:
    meta = json.loads(path.read_text(encoding="utf-8"))
    require(meta["past_cols"] == past_cols, f"过去特征顺序不一致: {path}")
    require(meta["fut_cols"] == future_cols, f"未来特征顺序不一致: {path}")
    for key in ("sp", "sf"):
        scaler = meta["scaler"][key]
        expected = past_cols if key == "sp" else future_cols
        require(scaler["cols"] == expected, f"{key} 列顺序不一致: {path}")
        require(len(scaler["mean"]) == len(expected), f"{key} mean Shape 错误")
        require(len(scaler["scale"]) == len(expected), f"{key} scale Shape 错误")
        require(np.isfinite(scaler["mean"]).all(), f"{key} mean 含非有限值")
        require(np.isfinite(scaler["scale"]).all(), f"{key} scale 含非有限值")
        require((np.asarray(scaler["scale"]) > 0).all(), f"{key} scale 必须大于0")
    print(f"[PASS] Scaler {path.parent.name}: past={len(past_cols)} future={len(future_cols)}")
    return meta


def check_tail(path: Path, time_col: str, past_cols: list[str], future_cols: list[str],
               lookback: int, horizon: int, finite_tail_only: bool = False) -> None:
    frame = pd.read_parquet(path)
    required = [time_col] + list(dict.fromkeys(past_cols + future_cols))
    missing = [col for col in required if col not in frame.columns]
    require(not missing, f"{path.name} 缺列: {missing}")
    require(len(frame) >= lookback + horizon + 1, f"{path.name} 行数不足")
    timestamps = pd.to_datetime(frame[time_col])
    require(timestamps.notna().all(), f"{path.name} 时间戳解析失败")
    require(timestamps.is_monotonic_increasing, f"{path.name} 时间戳未升序")
    values_frame = frame.tail(lookback + horizon + 1) if finite_tail_only else frame
    values = values_frame[list(dict.fromkeys(past_cols + future_cols))].to_numpy("float64")
    require(np.isfinite(values).all(), f"{path.name} 特征含 NaN/Inf")
    print(f"[PASS] Tail {path.name}: rows={len(frame)} range={timestamps.iloc[0]}..{timestamps.iloc[-1]}")


def runtime_check() -> None:
    sys.path.insert(0, str(BACKEND))
    from realtime_api.tf_split_service import TFSplitService
    from realtime_api.tf_pv_v2_service import TFPVV2Service

    # 生产配置当前启用的是两个独立网络（负荷、价格），不能用旧 tf_v2
    # 联合模型代替运行时验收，否则可能出现“脚本通过、生产模型加载失败”。
    load_service = TFSplitService()
    load_service.load_models()
    model_info = load_service.get_model_info()
    require(
        set(model_info) == {"tf_load_split_v1", "tf_price_split_v1"},
        "运行时未加载独立负荷与独立电价两个生产模型",
    )
    require(all(item.get("loaded") for item in model_info.values()), "独立模型未全部就绪")
    first = load_service.predict()
    second = load_service.predict()
    require(len(first["hourly"]) == 24, "负荷价格输出不是24小时")
    require(first["hourly"] == second["hourly"], "相同输入的推理结果不确定")
    load_values = np.asarray([x["load_forecast_mw"] for x in first["hourly"]])
    price_values = np.asarray([[x["price_p10"], x["price_p50"], x["price_p90"]]
                               for x in first["hourly"]])
    require(np.isfinite(load_values).all() and np.isfinite(price_values).all(), "负荷/价格含NaN/Inf")
    require((price_values[:, 0] <= price_values[:, 1]).all(), "价格 P10>P50")
    require((price_values[:, 1] <= price_values[:, 2]).all(), "价格 P50>P90")
    print(
        "[PASS] TF Split runtime: load=(1,24,1), price=(1,24,3), "
        f"models=2/2, origin={first['origin']}"
    )

    pv_service = TFPVV2Service()
    pv_service.load_models()
    first_pv = pv_service.predict()
    second_pv = pv_service.predict()
    require(len(first_pv["hourly_pv_mw"]) == 24, "PV输出不是24小时")
    require(first_pv["hourly_pv_mw"] == second_pv["hourly_pv_mw"], "PV推理结果不确定")
    pv_values = np.asarray(first_pv["hourly_pu"])
    require(np.isfinite(pv_values).all(), "PV输出含NaN/Inf")
    require((pv_values >= 0).all(), "PV输出出现负值")
    print(f"[PASS] PV runtime: output=(1,24,1), origin={first_pv['origin']}")


def check_split_assets() -> None:
    root = ASSETS / "tf_split_v1"
    check_h5(root / "load_best.weights.h5")
    check_h5(root / "price_best.weights.h5")
    for name, past in (("load_scalers.json", SPLIT_LOAD_PAST), ("price_scalers.json", SPLIT_PRICE_PAST)):
        meta = json.loads((root / name).read_text(encoding="utf-8"))
        require(meta["past_cols"] == past, f"新模型过去特征顺序不一致: {root / name}")
        require(meta["future_cols"] == SPLIT_FUTURE, f"新模型未来特征顺序不一致: {root / name}")
        for key in ("sp", "sf", "sy"):
            require(key + "_mean" in meta and key + "_scale" in meta,
                    f"新模型 scaler 缺少 {key}: {root / name}")
            mean = np.asarray(meta[key + "_mean"], dtype="float64")
            scale = np.asarray(meta[key + "_scale"], dtype="float64")
            require(np.isfinite(mean).all(), f"新模型 {key} mean 含非有限值")
            require(np.isfinite(scale).all(), f"新模型 {key} scale 含非有限值")
            require((scale > 0).all(), f"新模型 {key} scale 必须大于0")
        print(f"[PASS] Split scaler {name}: past={len(past)} future={len(SPLIT_FUTURE)}")
    # rt_yest is a deterministic runtime-derived feature (RT_Demand shifted 24h).
    check_tail(root / "ca_features.parquet", "ts_local", SPLIT_PRICE_PAST,
               [col for col in SPLIT_FUTURE if col != "rt_yest"], 168, 24,
               finite_tail_only=True)


def check_pv_v2_assets() -> None:
    root = ASSETS / "pv_v2"
    check_h5(root / "pv_v2_best.weights.h5")
    meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    require(meta["past_features"] == PV_PAST, "pv_v2 过去特征顺序不一致")
    require(meta["future_features"] == PV_FUTURE, "pv_v2 未来特征顺序不一致")
    require(float(meta["target_scale_mw"]) > 0, "pv_v2 target scale 无效")
    for key, expected in (("past", PV_PAST), ("future", PV_FUTURE)):
        scaler = meta["scalers"][key]
        require(scaler["cols"] == expected, f"pv_v2 {key} scaler 列顺序不一致")
        require(len(scaler["mean"]) == len(expected), f"pv_v2 {key} mean Shape 错误")
        require(len(scaler["scale"]) == len(expected), f"pv_v2 {key} scale Shape 错误")
        require(np.isfinite(scaler["mean"]).all(), f"pv_v2 {key} mean 含非有限值")
        require((np.asarray(scaler["scale"]) > 0).all(), f"pv_v2 {key} scale 必须大于0")
    print(f"[PASS] pv_v2 metadata: past={len(PV_PAST)} future={len(PV_FUTURE)}")
    check_tail(root / "pv_tail.parquet", "ts_start", PV_PAST, PV_FUTURE, 96, 24)


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 TensorFlow 生产模型资产")
    parser.add_argument("--runtime", action="store_true", help="加载 TensorFlow 并执行确定性推理")
    args = parser.parse_args()

    # 只校验当前生产配置实际加载的三个模型资产：独立负荷、独立电价和
    # pv_v2。归档的 tf_v2 联合模型与 pv_v1 不应成为项目启动的硬依赖。
    check_pv_v2_assets()
    check_split_assets()

    if args.runtime:
        runtime_check()
    else:
        print("[INFO] 静态资产校验完成；安装生产 TensorFlow 环境后追加 --runtime。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
