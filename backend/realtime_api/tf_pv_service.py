# -*- coding: utf-8 -*-
"""
TF pv_v1 光伏推理服务
=====================

把 MMXX 训练的 pv_v1 模型 (GRU128, 96h -> 24h, ISO-NE BTM 光伏 p.u.) 接入后端:
  * 离线资产 (prepare_tf_assets.py 生成):
      models/tf_assets/pv_v1/{pv_v1_best.weights.h5, scalers.json, pv_tail.parquet}
  * 预测锚点固定为数据尾部 (演示口径): 输入=锚点前 96h 特征, 输出=锚点后 24h
    归一化光伏出力 p.u. -> MW (乘以资产中的容量基准 capacity_mw)。
  * 与 MMXX train_pv.py 解码一致: p_u = clip(out*std+mean, 0, 1)
  * 输出统一光伏预测结构 (hourly_pv_mw/timestamps/total_mwh/peak_mw/
    capacity_factor/model_info/ensemble_weights/...)。

作者: 毕业设计项目 (接入 MMXX 训练产物)
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf

from realtime_api.pv_capacity import btm_pv_capacity_array

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_ASSETS = _BACKEND_DIR / "models" / "tf_assets" / "pv_v1"

# MMXX runs/pv_v1/metrics.json 实测指标 (展示用)
TRAIN_METRICS = {
    "val_MAE_pu": 0.01375,
    "val_RMSE_pu": 0.03156,
    "test_MAE_pu": 0.01850,
    "test_RMSE_pu": 0.03876,
    "test_daytime_MAE_pu": 0.03975,
    "naive24_daytime_MAE_pu": 0.10909,
}


class FrozenScaler:
    def __init__(self, d: dict):
        self.cols = list(d["cols"])
        self.mean = np.asarray(d["mean"], dtype="float64")
        self.scale = np.asarray(d["scale"], dtype="float64")

    def transform(self, x: np.ndarray) -> np.ndarray:
        return (np.asarray(x, dtype="float64") - self.mean) / self.scale


class TFPVService:
    """pv_v1 光伏预测服务；生产输入必须通过 ``predict_features``。"""

    MODEL_NAME = "pv_v1"
    MODEL_LABEL = "TensorFlow 光伏预测模型（PV v1 · GRU-128）"
    NUM_PARAMS = 73857
    LOOKBACK = 96
    HORIZON = 24

    def __init__(self, assets_dir: Path = None):
        self.assets_dir = Path(os.getenv("TF_PV_ASSETS_DIR", str(assets_dir or _DEFAULT_ASSETS)))
        self._model: tf.keras.Model | None = None
        self._sp = self._sf = None
        self._y_mean = 0.0
        self._y_std = 1.0
        self._capacity_mw: float | None = None
        self._frame: pd.DataFrame | None = None
        self._origin_ts_start: pd.Timestamp | None = None
        self._loaded = False
        self._inference_count = 0
        self._total_inference_time_ms = 0.0

    @property
    def is_ready(self) -> bool:
        return self._loaded

    def _need(self, name: str) -> Path:
        p = self.assets_dir / name
        if not p.exists():
            raise FileNotFoundError(f"TF pv_v1 资产缺失: {p}")
        return p

    def load_models(self) -> None:
        from models.tensorflow_load import tf_pv_models as M

        t0 = time.perf_counter()
        meta = json.loads(self._need("scalers.json").read_text(encoding="utf-8"))
        self._sp = FrozenScaler(meta["scaler"]["sp"])
        self._sf = FrozenScaler(meta["scaler"]["sf"])
        self._y_mean = float(meta["y"]["mean"])
        self._y_std = float(meta["y"]["std"])
        self._capacity_mw = meta.get("capacity_mw")

        if self._sp.cols != M.PAST_COLS:
            raise ValueError("TF PV 过去特征顺序与模型契约不一致")
        if self._sf.cols != M.FUT_COLS:
            raise ValueError("TF PV 未来特征顺序与模型契约不一致")

        self._model = M.load_trained_model(str(self._need("pv_v1_best.weights.h5")))

        tail = pd.read_parquet(self._need("pv_tail.parquet"))
        tail["ts_start"] = pd.to_datetime(tail["ts_start"])
        tail = tail.sort_values("ts_start").reset_index(drop=True)
        self._frame = tail

        meta_root = _BACKEND_DIR / "models" / "tf_assets" / "meta.json"
        origin = None
        if meta_root.exists():
            m = json.loads(meta_root.read_text(encoding="utf-8"))
            if "pv_v1" in m and m["pv_v1"].get("origin_ts_start"):
                origin = pd.Timestamp(m["pv_v1"]["origin_ts_start"])
        if origin is None:
            origin = tail["ts_start"].iloc[len(tail) - 24]
        if origin not in set(tail["ts_start"]):
            cand = tail[tail["ts_start"] <= origin]["ts_start"]
            origin = cand.iloc[-1] if len(cand) else tail["ts_start"].iloc[-24]
        self._origin_ts_start = origin
        self._loaded = True
        logger.info(
            f"[tf_pv] 资产加载完成: 耗时 {time.perf_counter() - t0:.1f}s | "
            f"锚点(origin ts_start)={origin} | y_mean={self._y_mean:.4f} y_std={self._y_std:.4f} | "
            f"capacity_fallback_mw={self._capacity_mw} | 尾部行数={len(tail)}"
        )

    # ------------------------------------------------------------------
    # TensorFlow 光伏推理
    # ------------------------------------------------------------------
    @staticmethod
    def _feature_matrix(frame: pd.DataFrame, columns: list[str], rows: int, label: str) -> np.ndarray:
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise ValueError(f"{label}缺少训练特征: {missing}")
        if len(frame) != rows:
            raise ValueError(f"{label}行数必须为 {rows}，实际为 {len(frame)}")
        matrix = frame[columns].apply(pd.to_numeric, errors="coerce").to_numpy("float64")
        if not np.isfinite(matrix).all():
            bad = [columns[i] for i in np.flatnonzero(~np.isfinite(matrix).all(axis=0))]
            raise ValueError(f"{label}包含 NaN/Inf 或非数值字段: {bad}")
        return matrix

    @staticmethod
    def _timestamps(frame: pd.DataFrame, rows: int, label: str) -> list[pd.Timestamp]:
        time_col = "ts_start" if "ts_start" in frame.columns else "timestamp"
        if time_col not in frame.columns:
            raise ValueError(f"{label}必须包含 timestamp 或 ts_start")
        timestamps = list(pd.to_datetime(frame[time_col], errors="coerce"))
        if len(timestamps) != rows or any(pd.isna(value) for value in timestamps):
            raise ValueError(f"{label}时间戳无法解析或数量不正确")
        index = pd.DatetimeIndex(timestamps)
        if index.has_duplicates or not index.is_monotonic_increasing:
            raise ValueError(f"{label}时间戳必须严格升序且不重复")
        return timestamps

    def _predict_matrices(
        self,
        past: np.ndarray,
        future: np.ndarray,
        future_timestamps: list[pd.Timestamp],
        *,
        origin: pd.Timestamp,
        data_source: str,
    ) -> dict:
        from models.tensorflow_load import tf_pv_models as M

        t0 = time.perf_counter()
        P = np.nan_to_num(self._sp.transform(past)).astype("float32")[None]
        F = np.nan_to_num(self._sf.transform(future)).astype("float32")[None]
        if P.shape != (1, M.LOOKBACK, len(M.PAST_COLS)):
            raise ValueError(f"TF PV 过去输入 Shape 错误: {P.shape}")
        if F.shape != (1, M.HORIZON, len(M.FUT_COLS)):
            raise ValueError(f"TF PV 未来输入 Shape 错误: {F.shape}")

        raw = np.asarray(self._model.predict([P, F], verbose=0), dtype="float64")
        if raw.shape != (1, M.HORIZON, 1):
            raise RuntimeError(f"TF PV 输出 Shape 错误: {raw.shape}")
        if not np.isfinite(raw).all():
            raise RuntimeError("TF PV 输出包含 NaN/Inf")
        out = raw[0, :, 0]
        p_u = np.clip(out * self._y_std + self._y_mean, 0.0, 1.0)
        # 神经网络回归在夜间可能产生极小正残差。新权重使用修正后的太阳几何，
        # 因此用 sun_up 与 Open-Meteo GHI 双重确认白昼，夜间强制归零。
        ghi_index = M.FUT_COLS.index("ghi_mean")
        sun_up_index = M.FUT_COLS.index("sun_up")
        daylight = (future[:, ghi_index] > 1.0) & (future[:, sun_up_index] > 0.5)
        p_u = np.where(daylight, p_u, 0.0)
        fallback_capacity = float(self._capacity_mw) if self._capacity_mw else 1.0
        hourly_capacity = btm_pv_capacity_array(
            future_timestamps, fallback_mw=fallback_capacity
        )
        mw = p_u * hourly_capacity

        timestamps = [str(pd.Timestamp(value)) for value in future_timestamps]
        total_mwh = float(mw.sum())
        peak_mw = float(mw.max())
        capacity = float(hourly_capacity.mean())
        total_capacity_mwh = float(hourly_capacity.sum())
        capacity_factor = total_mwh / total_capacity_mwh if total_capacity_mwh > 0 else 0.0

        infer_ms = (time.perf_counter() - t0) * 1000
        self._inference_count += 1
        self._total_inference_time_ms += infer_ms
        return {
            "status": "success",
            "model_type": "tf_pv_v1",
            "hourly_pv_mw": [round(float(value), 2) for value in mw],
            "hourly_pv_kw": [round(float(value) * 1000, 1) for value in mw],
            "hourly_pu": [round(float(value), 4) for value in p_u],
            "timestamps": timestamps,
            "total_mwh": round(total_mwh, 2),
            "peak_mw": round(peak_mw, 2),
            "capacity_factor": round(capacity_factor, 4),
            "model_info": self.get_model_info(),
            "ensemble_weights": {"pv_v1": 1.0},
            "inference_time_ms": round(infer_ms, 1),
            "device": "tensorflow",
            "feature_count": len(M.PAST_COLS),
            "lookback": M.LOOKBACK,
            "horizon": M.HORIZON,
            "origin": str(origin),
            "data_source": data_source,
            "capacity_mw": round(capacity, 1) if self._capacity_mw else None,
            "hourly_capacity_mw": [round(float(value), 2) for value in hourly_capacity],
            "capacity_basis": "ISO-NE 2026 CELT date-aligned BTM PV AC nameplate",
        }

    def predict_features(self, past_features, future_features) -> dict:
        """使用真实在线特征推理；绝不对缺失训练字段静默补零。"""
        if not self._loaded:
            raise RuntimeError("TF pv_v1 模型未加载, 请先 load_models()")
        from models.tensorflow_load import tf_pv_models as M

        past_frame = pd.DataFrame(past_features).copy()
        future_frame = pd.DataFrame(future_features).copy()
        past_ts = self._timestamps(past_frame, M.LOOKBACK, "TF PV 历史输入")
        future_ts = self._timestamps(future_frame, M.HORIZON, "TF PV 未来输入")
        if future_ts[0] <= past_ts[-1]:
            raise ValueError("TF PV 未来输入必须晚于历史窗口末端")
        past = self._feature_matrix(past_frame, M.PAST_COLS, M.LOOKBACK, "TF PV 历史输入")
        future = self._feature_matrix(future_frame, M.FUT_COLS, M.HORIZON, "TF PV 未来输入")
        return self._predict_matrices(
            past,
            future,
            future_ts,
            origin=past_ts[-1],
            data_source="live_features",
        )

    def predict(self, origin_ts_start: str | None = None) -> dict:
        """使用冻结 Tail 资产执行验收预测，不代表当前实时预测。"""
        if not self._loaded:
            raise RuntimeError("TF pv_v1 模型未加载, 请先 load_models()")
        from models.tensorflow_load import tf_pv_models as M

        frame = self._frame
        if origin_ts_start is not None:
            origin = pd.Timestamp(origin_ts_start)
            if origin not in set(frame["ts_start"]):
                raise ValueError(f"锚点 {origin} 不在尾部特征内")
        else:
            origin = self._origin_ts_start
        pos = int(np.flatnonzero(frame["ts_start"] == origin)[0])
        if pos < M.LOOKBACK or pos + M.HORIZON >= len(frame):
            raise ValueError(f"锚点 {origin} 距尾部不足, 无法预测")

        past = frame.loc[pos - M.LOOKBACK + 1: pos, M.PAST_COLS].to_numpy("float64")
        fut = frame.loc[pos + 1: pos + M.HORIZON, M.FUT_COLS].to_numpy("float64")
        fut_ts = [pd.Timestamp(value) for value in
                  frame["ts_start"].iloc[pos + 1: pos + 1 + M.HORIZON].values]
        return self._predict_matrices(
            past,
            fut,
            fut_ts,
            origin=origin,
            data_source="frozen_tail_demo",
        )

    def get_model_info(self) -> dict:
        return {
            self.MODEL_NAME: {
                "weight": 1.0,
                "num_params": self.NUM_PARAMS,
                "loaded": self._loaded,
                "task": "未来24小时光伏发电预测",
                "architecture": "GRU-128",
                "config": {"encoder": "GRU128", "lookback": self.LOOKBACK, "horizon": self.HORIZON,
                           "target": "pv_n_ISONE (p.u.)",
                           "capacity_strategy": "ISO-NE 2026 CELT date-aligned",
                           "capacity_fallback_mw": self._capacity_mw},
                "label": self.MODEL_LABEL,
                "training_metrics": TRAIN_METRICS,
            }
        }

    def get_status(self) -> dict:
        avg = (self._total_inference_time_ms / self._inference_count
               if self._inference_count else 0.0)
        fallback_capacity = float(self._capacity_mw) if self._capacity_mw else 1.0
        current_capacity = float(btm_pv_capacity_array(
            [pd.Timestamp.now(tz="America/New_York")],
            fallback_mw=fallback_capacity,
        )[0])
        return {
            "loaded": self._loaded,
            "model": self.MODEL_NAME,
            "model_label": self.MODEL_LABEL,
            "framework": "tensorflow",
            "total_inferences": self._inference_count,
            "average_inference_time_ms": round(avg, 2),
            "origin_ts_start": str(self._origin_ts_start) if self._origin_ts_start else None,
            "capacity_mw": round(current_capacity, 1),
            "capacity_fallback_mw": self._capacity_mw,
            "capacity_strategy": "ISO-NE 2026 CELT date-aligned",
            "assets_dir": str(self.assets_dir),
            "supported_input_modes": ["live_features", "frozen_tail_demo"],
        }

    def release(self) -> None:
        self._loaded = False
        self._model = None
        logger.info("[tf_pv] 模型资源已释放")
