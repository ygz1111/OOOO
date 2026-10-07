# -*- coding: utf-8 -*-
"""Production inference service for the TensorFlow pv_v2 model."""
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
_BACKEND = Path(__file__).resolve().parents[1]
_DEFAULT_ASSETS = _BACKEND / "models" / "tf_assets" / "pv_v2"


class FrozenScaler:
    def __init__(self, payload: dict):
        self.cols = list(payload["cols"])
        self.mean = np.asarray(payload["mean"], dtype="float64")
        self.scale = np.asarray(payload["scale"], dtype="float64")

    def transform(self, values) -> np.ndarray:
        return (np.asarray(values, dtype="float64") - self.mean) / self.scale


class TFPVV2Service:
    MODEL_NAME = "pv_v2"
    MODEL_LABEL = "TensorFlow 光伏预测模型（PV v2 · TCN-GRU-Attention）"
    LOOKBACK = 96
    HORIZON = 24

    def __init__(self, assets_dir: Path | None = None):
        self.assets_dir = Path(os.getenv("TF_PV_ASSETS_DIR", str(assets_dir or _DEFAULT_ASSETS)))
        self._model: tf.keras.Model | None = None
        self._past_scaler: FrozenScaler | None = None
        self._future_scaler: FrozenScaler | None = None
        self._target_scale_mw = 1.0
        self._metadata: dict = {}
        self._frame: pd.DataFrame | None = None
        self._origin: pd.Timestamp | None = None
        self._loaded = False
        self._inference_count = 0
        self._total_inference_time_ms = 0.0

    @property
    def is_ready(self) -> bool:
        return self._loaded

    def _need(self, name: str) -> Path:
        path = self.assets_dir / name
        if not path.exists():
            raise FileNotFoundError(f"TensorFlow pv_v2 资产缺失: {path}")
        return path

    def load_models(self) -> None:
        from models.tensorflow_load import tf_pv_v2_models as definition

        started = time.perf_counter()
        self._metadata = json.loads(self._need("metadata.json").read_text(encoding="utf-8"))
        self._past_scaler = FrozenScaler(self._metadata["scalers"]["past"])
        self._future_scaler = FrozenScaler(self._metadata["scalers"]["future"])
        self._target_scale_mw = float(self._metadata["target_scale_mw"])
        if self._past_scaler.cols != definition.PAST_COLS:
            raise ValueError("pv_v2 过去特征顺序与训练资产不一致")
        if self._future_scaler.cols != definition.FUT_COLS:
            raise ValueError("pv_v2 未来特征顺序与训练资产不一致")
        self._model = definition.load_trained_model(str(self._need("pv_v2_best.weights.h5")))
        if self._model.count_params() != int(self._metadata["parameters"]):
            raise ValueError("pv_v2 参数量与训练元数据不一致")

        tail = pd.read_parquet(self._need("pv_tail.parquet"))
        tail["ts_start"] = pd.to_datetime(tail["ts_start"])
        self._frame = tail.sort_values("ts_start").reset_index(drop=True)
        self._origin = self._frame["ts_start"].iloc[-self.HORIZON - 1]
        self._loaded = True
        logger.info(
            "[tf_pv_v2] 加载完成: %.2fs | 参数=%s | 尾部锚点=%s",
            time.perf_counter() - started, self._model.count_params(), self._origin,
        )

    @staticmethod
    def _timestamps(frame: pd.DataFrame, expected: int, label: str) -> list[pd.Timestamp]:
        column = "ts_start" if "ts_start" in frame.columns else "timestamp"
        if column not in frame.columns:
            raise ValueError(f"{label}缺少时间戳")
        values = list(pd.to_datetime(frame[column], errors="coerce"))
        index = pd.DatetimeIndex(values)
        if len(index) != expected or index.hasnans or index.has_duplicates or not index.is_monotonic_increasing:
            raise ValueError(f"{label}时间戳必须为 {expected} 个严格递增且不重复的小时")
        return values

    @staticmethod
    def _matrix(frame: pd.DataFrame, columns: list[str], expected: int, label: str) -> np.ndarray:
        missing = sorted(set(columns) - set(frame.columns))
        if missing:
            raise ValueError(f"{label}缺少 pv_v2 训练特征: {missing}")
        if len(frame) != expected:
            raise ValueError(f"{label}行数必须为 {expected}，实际为 {len(frame)}")
        values = frame[columns].apply(pd.to_numeric, errors="coerce").to_numpy("float64")
        if not np.isfinite(values).all():
            raise ValueError(f"{label}包含 NaN/Inf")
        return values

    def _predict(self, past: np.ndarray, future: np.ndarray,
                 timestamps: list[pd.Timestamp], origin: pd.Timestamp,
                 data_source: str) -> dict:
        from models.tensorflow_load import tf_pv_v2_models as definition

        started = time.perf_counter()
        x_past = self._past_scaler.transform(past).astype("float32")[None]
        x_future = self._future_scaler.transform(future).astype("float32")[None]
        if x_past.shape != (1, definition.LOOKBACK, len(definition.PAST_COLS)):
            raise ValueError(f"pv_v2 过去输入 Shape 错误: {x_past.shape}")
        if x_future.shape != (1, definition.HORIZON, len(definition.FUT_COLS)):
            raise ValueError(f"pv_v2 未来输入 Shape 错误: {x_future.shape}")
        raw_ratio = np.asarray(self._model.predict([x_past, x_future], verbose=0))[0, :, 0]
        if raw_ratio.shape != (definition.HORIZON,) or not np.isfinite(raw_ratio).all():
            raise RuntimeError("pv_v2 输出 Shape 错误或包含 NaN/Inf")
        mw = np.maximum(raw_ratio * self._target_scale_mw, 0.0)
        sun_index = definition.FUT_COLS.index("sun_up")
        mw = np.where(future[:, sun_index] > 0.5, mw, 0.0)

        capacities = btm_pv_capacity_array(timestamps, fallback_mw=5145.798)
        elapsed = (time.perf_counter() - started) * 1000
        self._inference_count += 1
        self._total_inference_time_ms += elapsed
        total_mwh = float(mw.sum())
        return {
            "status": "success",
            "model_type": "tf_pv_v2",
            "hourly_pv_mw": [round(float(value), 2) for value in mw],
            "hourly_pv_kw": [round(float(value) * 1000, 1) for value in mw],
            "hourly_pu": [round(float(value / capacity), 4) for value, capacity in zip(mw, capacities)],
            "timestamps": [str(pd.Timestamp(value)) for value in timestamps],
            "total_mwh": round(total_mwh, 2),
            "peak_mw": round(float(mw.max()), 2),
            "capacity_factor": round(float(total_mwh / capacities.sum()), 4),
            "model_info": self.get_model_info(),
            "ensemble_weights": {self.MODEL_NAME: 1.0},
            "inference_time_ms": round(elapsed, 1),
            "device": "tensorflow",
            "feature_count": len(definition.PAST_COLS),
            "lookback": definition.LOOKBACK,
            "horizon": definition.HORIZON,
            "origin": str(origin),
            "data_source": data_source,
            "capacity_mw": round(float(capacities.mean()), 1),
            "hourly_capacity_mw": [round(float(value), 2) for value in capacities],
            "capacity_basis": "display/reference only; pv_v2 predicts MW directly",
        }

    def predict_features(self, past_features, future_features) -> dict:
        if not self._loaded:
            raise RuntimeError("TensorFlow pv_v2 尚未加载")
        from models.tensorflow_load import tf_pv_v2_models as definition

        past_frame = pd.DataFrame(past_features).copy()
        future_frame = pd.DataFrame(future_features).copy()
        past_ts = self._timestamps(past_frame, definition.LOOKBACK, "pv_v2 历史输入")
        future_ts = self._timestamps(future_frame, definition.HORIZON, "pv_v2 未来输入")
        if future_ts[0] <= past_ts[-1]:
            raise ValueError("pv_v2 未来输入必须晚于历史窗口")
        return self._predict(
            self._matrix(past_frame, definition.PAST_COLS, definition.LOOKBACK, "pv_v2 历史输入"),
            self._matrix(future_frame, definition.FUT_COLS, definition.HORIZON, "pv_v2 未来输入"),
            future_ts, pd.Timestamp(past_ts[-1]), "live_features",
        )

    def predict(self, origin_ts_start: str | None = None) -> dict:
        """Frozen-tail acceptance prediction used only when live sources are unavailable."""
        if not self._loaded:
            raise RuntimeError("TensorFlow pv_v2 尚未加载")
        from models.tensorflow_load import tf_pv_v2_models as definition

        frame = self._frame
        origin = pd.Timestamp(origin_ts_start) if origin_ts_start else self._origin
        positions = np.flatnonzero(frame["ts_start"].to_numpy() == origin.to_datetime64())
        if not len(positions):
            raise ValueError(f"pv_v2 尾部资产不存在锚点 {origin}")
        position = int(positions[0])
        if position < definition.LOOKBACK - 1 or position + definition.HORIZON >= len(frame):
            raise ValueError("pv_v2 尾部资产不足以覆盖所选锚点")
        past = frame.iloc[position - definition.LOOKBACK + 1: position + 1]
        future = frame.iloc[position + 1: position + 1 + definition.HORIZON]
        return self._predict(
            self._matrix(past, definition.PAST_COLS, definition.LOOKBACK, "pv_v2 尾部历史"),
            self._matrix(future, definition.FUT_COLS, definition.HORIZON, "pv_v2 尾部未来"),
            list(pd.to_datetime(future["ts_start"])), origin, "frozen_tail_demo",
        )

    def get_model_info(self) -> dict:
        metrics = self._metadata.get("metrics", {}).get("test", {})
        return {
            self.MODEL_NAME: {
                "weight": 1.0,
                "num_params": int(self._metadata.get("parameters", 0)),
                "loaded": self._loaded,
                "task": "未来24小时光伏发电预测",
                "architecture": "TCN-GRU-Attention",
                "config": {
                    "lookback": self.LOOKBACK, "horizon": self.HORIZON,
                    "target": "ISO-NE estimated BTM PV MW",
                    "output_scaling": "train-only fixed scale; direct MW inversion",
                },
                "label": self.MODEL_LABEL,
                "training_metrics": metrics,
            }
        }

    def get_status(self) -> dict:
        average = self._total_inference_time_ms / max(self._inference_count, 1)
        return {
            "loaded": self._loaded,
            "model": self.MODEL_NAME,
            "model_label": self.MODEL_LABEL,
            "framework": "tensorflow",
            "total_inferences": self._inference_count,
            "average_inference_time_ms": round(average, 2),
            "origin_ts_start": str(self._origin) if self._origin is not None else None,
            "assets_dir": str(self.assets_dir),
            "supported_input_modes": ["live_features", "frozen_tail_demo"],
        }

    def release(self) -> None:
        self._loaded = False
        self._model = None


__all__ = ["TFPVV2Service"]
