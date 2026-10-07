# -*- coding: utf-8 -*-
"""
TF v2 负荷+电价推理服务
=======================

把 MMXX 训练的 tf_v2 模型 (GRU192, 168h -> 24h) 接入后端:
  * 离线资产 (prepare_tf_assets.py 生成):
      models/tf_assets/tf_v2/{tf_v2_best.weights.h5, scalers.json, ca_tail.parquet}
  * 预测锚点固定为数据尾部 (演示口径): 输入窗口=锚点前 168h 特征,
    输出=锚点后 24h 的负荷 (MW) 与电价分位 p10/p50/p90 (USD/MWh)。
  * 归一化/反归一化与 MMXX train_tf.py 完全一致:
      load = sl.inverse(out_load); price = expm1(sy.inverse(out_price))
  * 生产环境只加载 TensorFlow 资产；资产缺失或加载失败时明确报错。

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

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_ASSETS = _BACKEND_DIR / "models" / "tf_assets" / "tf_v2"


# ---------------------------------------------------------------------------
# 轻量 StandardScaler (与 sklearn 拟合结果一致, 只做正向/逆向变换)
# ---------------------------------------------------------------------------
class FrozenScaler:
    def __init__(self, d: dict):
        self.cols = list(d["cols"])
        self.mean = np.asarray(d["mean"], dtype="float64")
        self.scale = np.asarray(d["scale"], dtype="float64")

    def transform(self, x: np.ndarray) -> np.ndarray:
        return (np.asarray(x, dtype="float64") - self.mean) / self.scale

    def inverse_transform(self, x: np.ndarray) -> np.ndarray:
        return np.asarray(x, dtype="float64") * self.scale + self.mean


class TFLoadPriceService:
    """tf_v2 负荷 + 电价分位预测服务。

    ``predict()`` 只用于冻结样本验收；生产调用应使用
    ``predict_features()`` 并提供与训练完全一致的 168/24 小时特征。
    """

    # 名称/常量 (供前端与日志)
    MODEL_NAME = "tf_v2_gru192"
    MODEL_LABEL = "TF v2 GRU-192 (负荷+电价分位)"
    NUM_PARAMS = 159524

    def __init__(self, assets_dir: Path = None):
        self.assets_dir = Path(os.getenv("TF_V2_ASSETS_DIR", str(assets_dir or _DEFAULT_ASSETS)))
        self._model: tf.keras.Model | None = None
        self._sp = self._sf = self._sl = self._sy = None
        self._frame: pd.DataFrame | None = None
        self._origin_ts_local: pd.Timestamp | None = None
        self._loaded = False
        self._inference_count = 0
        self._total_inference_time_ms = 0.0

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    @property
    def is_ready(self) -> bool:
        return self._loaded

    def _need(self, name: str) -> Path:
        p = self.assets_dir / name
        if not p.exists():
            raise FileNotFoundError(f"TF v2 资产缺失: {p}")
        return p

    def load_models(self) -> None:
        from models.tensorflow_load import tf_v2_models

        t0 = time.perf_counter()
        meta = json.loads(self._need("scalers.json").read_text(encoding="utf-8"))
        self._sp = FrozenScaler(meta["scaler"]["sp"])
        self._sf = FrozenScaler(meta["scaler"]["sf"])
        self._sl = FrozenScaler(meta["scaler"]["sl"])
        self._sy = FrozenScaler(meta["scaler"]["sy"])

        if self._sp.cols != tf_v2_models.PAST_COLS:
            raise ValueError("TF v2 过去特征顺序与模型契约不一致")
        if self._sf.cols != tf_v2_models.FUT_COLS:
            raise ValueError("TF v2 未来特征顺序与模型契约不一致")

        self._model = tf_v2_models.load_trained_model(str(self._need("tf_v2_best.weights.h5")))

        tail = pd.read_parquet(self._need("ca_tail.parquet"))
        tail["ts_local"] = pd.to_datetime(tail["ts_local"])
        tail = tail.sort_values("ts_local").reset_index(drop=True)
        self._frame = tail

        # 锚点优先取 meta.json, 缺省用尾部倒数第 24 行
        meta_root = _BACKEND_DIR / "models" / "tf_assets" / "meta.json"
        origin = None
        if meta_root.exists():
            m = json.loads(meta_root.read_text(encoding="utf-8"))
            if "tf_v2" in m and m["tf_v2"].get("origin_ts_local"):
                origin = pd.Timestamp(m["tf_v2"]["origin_ts_local"])
        if origin is None:
            origin = tail["ts_local"].iloc[len(tail) - 24]
        if origin not in set(tail["ts_local"]):
            # 容错: 取最接近的不晚于锚点
            cand = tail[tail["ts_local"] <= origin]["ts_local"]
            origin = cand.iloc[-1] if len(cand) else tail["ts_local"].iloc[-24]
        self._origin_ts_local = origin
        self._loaded = True
        logger.info(
            f"[tf_v2] 资产加载完成: 权重/scalers/尾部特征 耗时 {time.perf_counter() - t0:.1f}s | "
            f"锚点(origin ts_local)={origin} | 尾部行数={len(tail)}"
        )

    # ------------------------------------------------------------------
    # 推理
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
        time_col = "ts_local" if "ts_local" in frame.columns else "timestamp"
        if time_col not in frame.columns:
            raise ValueError(f"{label}必须包含 timestamp 或 ts_local")
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
        anchor_load: float | None = None,
        history_actual: list[dict] | None = None,
    ) -> dict:
        from models.tensorflow_load import tf_v2_models as M

        P = self._sp.transform(past).astype("float32")[None]
        F = self._sf.transform(future).astype("float32")[None]
        if P.shape != (1, M.LOOKBACK, len(M.PAST_COLS)):
            raise ValueError(f"TF v2 过去输入 Shape 错误: {P.shape}")
        if F.shape != (1, M.HORIZON, len(M.FUT_COLS)):
            raise ValueError(f"TF v2 未来输入 Shape 错误: {F.shape}")

        t0 = time.perf_counter()
        prediction = self._model.predict([P, F], verbose=0)
        load_raw = np.asarray(prediction["load"], dtype="float64")
        price_raw = np.asarray(prediction["price"], dtype="float64")
        if load_raw.shape != (1, M.HORIZON, 1) or price_raw.shape != (1, M.HORIZON, 3):
            raise RuntimeError(
                f"TF v2 输出 Shape 错误: load={load_raw.shape}, price={price_raw.shape}"
            )
        if not np.isfinite(load_raw).all() or not np.isfinite(price_raw).all():
            raise RuntimeError("TF v2 输出包含 NaN/Inf")

        load_mw = self._sl.inverse_transform(load_raw.reshape(-1, 1)).reshape(M.HORIZON)
        quantiles = np.expm1(
            self._sy.inverse_transform(price_raw.reshape(-1, 3)).reshape(M.HORIZON, 3)
        )
        quantiles = np.maximum(quantiles, 0.0)

        hourly = []
        for hour, timestamp in enumerate(future_timestamps):
            hourly.append({
                "hour": hour,
                "timestamp": str(pd.Timestamp(timestamp)),
                "load_forecast_mw": round(float(load_mw[hour]), 1),
                "price_p10": round(float(quantiles[hour, 0]), 2),
                "price_p50": round(float(quantiles[hour, 1]), 2),
                "price_p90": round(float(quantiles[hour, 2]), 2),
                "price_unit": "USD/MWh",
            })

        infer_ms = (time.perf_counter() - t0) * 1000
        self._inference_count += 1
        self._total_inference_time_ms += infer_ms
        return {
            "status": "success",
            "model": self.MODEL_NAME,
            "hourly": hourly,
            "timestamps": [item["timestamp"] for item in hourly],
            "model_info": self.get_model_info(),
            "ensemble_weights": {"tf_v2": 1.0},
            "inference_time_ms": round(infer_ms, 1),
            "origin": str(origin),
            "anchor_actual_load_mw": round(anchor_load, 1) if anchor_load is not None else None,
            "anchor_history_actual": history_actual or [],
            "data_source": data_source,
            "unit": {"load": "MW", "price": "USD/MWh"},
        }

    def predict_features(self, past_features, future_features) -> dict:
        """使用真实在线特征推理；缺列、补零和 Shape 不匹配都会明确失败。"""
        if not self._loaded:
            raise RuntimeError("TF v2 模型未加载, 请先 load_models()")
        from models.tensorflow_load import tf_v2_models as M

        past_frame = pd.DataFrame(past_features).copy()
        future_frame = pd.DataFrame(future_features).copy()
        past_ts = self._timestamps(past_frame, M.LOOKBACK, "TF v2 历史输入")
        future_ts = self._timestamps(future_frame, M.HORIZON, "TF v2 未来输入")
        if future_ts[0] <= past_ts[-1]:
            raise ValueError("TF v2 未来输入必须晚于历史窗口末端")
        past = self._feature_matrix(past_frame, M.PAST_COLS, M.LOOKBACK, "TF v2 历史输入")
        future = self._feature_matrix(future_frame, M.FUT_COLS, M.HORIZON, "TF v2 未来输入")
        history_actual = [
            {"target_time": str(ts), "actual_load_mw": round(float(value), 1)}
            for ts, value in zip(past_ts[-24:], past_frame["RT_Demand"].iloc[-24:])
        ]
        return self._predict_matrices(
            past,
            future,
            future_ts,
            origin=past_ts[-1],
            data_source="live_features",
            anchor_load=float(past_frame["RT_Demand"].iloc[-1]),
            history_actual=history_actual,
        )

    def predict(self, origin_ts_local: str | None = None) -> dict:
        """使用冻结 Tail 资产执行 24h 验收预测，不代表当前实时预测。

        Returns: dict {hourly: [...], timestamps, model_info, ensemble_weights,
                       inference_time_ms, origin, data_source}
        """
        if not self._loaded:
            raise RuntimeError("TF v2 模型未加载, 请先 load_models()")
        from models.tensorflow_load import tf_v2_models as M

        frame = self._frame
        if origin_ts_local is not None:
            origin = pd.Timestamp(origin_ts_local)
            if origin not in set(frame["ts_local"]):
                raise ValueError(f"锚点 {origin} 不在尾部特征内")
        else:
            origin = self._origin_ts_local
        pos = int(np.flatnonzero(frame["ts_local"] == origin)[0])
        if pos < M.LOOKBACK or pos + M.HORIZON >= len(frame):
            raise ValueError(
                f"锚点 {origin} 距尾部不足 (pos={pos}, n={len(frame)}), 无法预测")

        past = frame.loc[pos - M.LOOKBACK + 1: pos, M.PAST_COLS].to_numpy("float64")  # (168,15)
        fut = frame.loc[pos + 1: pos + M.HORIZON, M.FUT_COLS].to_numpy("float64")      # (24,13)
        if past.shape[0] < M.LOOKBACK or fut.shape[0] < M.HORIZON:
            raise ValueError("特征行不足")
        fut_ts = [pd.Timestamp(value) for value in
                  frame["ts_local"].iloc[pos + 1: pos + 1 + M.HORIZON].values]

        # 锚点实际值与锚点前 24h 历史实际 (供总览/回显)
        anchor_load = float(frame.loc[pos, "RT_Demand"]) if "RT_Demand" in frame.columns else None
        history_actual = []
        h0 = max(0, pos - 24)
        for j in range(h0, pos):
            history_actual.append({
                "target_time": str(pd.Timestamp(frame["ts_local"].iloc[j])),
                "actual_load_mw": round(float(frame["RT_Demand"].iloc[j]), 1),
            })

        return self._predict_matrices(
            past,
            fut,
            fut_ts,
            origin=origin,
            data_source="frozen_tail_demo",
            anchor_load=anchor_load,
            history_actual=history_actual,
        )

    def price_backtest(self, selected_date: str | None = None) -> dict:
        """在冻结的真实 ISO-NE 特征表上回放一天电价预测并给出真实值对比。

        该方法不访问在线接口、不写数据库，也不训练模型。它严格使用同一份
        168h 历史窗口、24h 已知未来特征和已冻结的 scaler，目标真实值为
        ``RT_LMP``（ISO-NE 实时 LMP，USD/MWh）。

        ``selected_date`` 使用 ET 的自然日；缺省时只返回可用日期范围，便于
        前端初始化日期选择器。
        """
        if not self._loaded or self._frame is None:
            raise RuntimeError("TF v2 模型未加载, 无法执行电价历史回测")

        from models.tensorflow_load import tf_v2_models as M

        frame = self._frame
        if "RT_LMP" not in frame.columns:
            raise ValueError("冻结特征表缺少 RT_LMP，无法与真实电价比较")

        # 与 predict() 的边界一致：窗口须包含完整 168h 历史与后续 24h 真实值。
        first_pos = M.LOOKBACK
        last_pos = len(frame) - M.HORIZON - 1
        if last_pos < first_pos:
            raise RuntimeError("冻结特征表行数不足，无法构造电价回测窗口")

        candidate = frame.iloc[first_pos:last_pos + 1].copy()
        candidate["__date"] = pd.to_datetime(candidate["ts_local"]).dt.strftime("%Y-%m-%d")
        # 日回测固定在该日 00:00 作为预测锚点，输出该日后续完整 24 小时。
        midnight = candidate[pd.to_datetime(candidate["ts_local"]).dt.hour == 0]
        available_dates = sorted(midnight["__date"].unique().tolist())
        if not available_dates:
            raise RuntimeError("冻结特征表中没有可用的整日电价回测窗口")

        date_range = {"earliest": available_dates[0], "latest": available_dates[-1]}
        if selected_date is None:
            return {"available_date_range": date_range, "date": None, "points": [], "metrics": None}

        requested = pd.Timestamp(selected_date).strftime("%Y-%m-%d")
        selected = midnight[midnight["__date"] == requested]
        if selected.empty:
            raise ValueError(
                f"回测日期 {requested} 不可用；可选范围为 "
                f"{date_range['earliest']} 至 {date_range['latest']}"
            )

        origin = pd.Timestamp(selected.iloc[0]["ts_local"])
        positions = np.flatnonzero(frame["ts_local"] == origin)
        if len(positions) != 1:
            raise RuntimeError(f"回测锚点 {origin} 在冻结特征表中不唯一")
        pos = int(positions[0])

        past_frame = frame.iloc[pos - M.LOOKBACK + 1:pos + 1]
        future_frame = frame.iloc[pos + 1:pos + M.HORIZON + 1]
        past = self._feature_matrix(past_frame, M.PAST_COLS, M.LOOKBACK, "电价回测历史输入")
        future = self._feature_matrix(future_frame, M.FUT_COLS, M.HORIZON, "电价回测未来输入")
        future_ts = self._timestamps(future_frame, M.HORIZON, "电价回测目标时间")
        prediction = self._predict_matrices(
            past,
            future,
            future_ts,
            origin=origin,
            data_source="frozen_historical_backtest",
            anchor_load=float(frame.iloc[pos]["RT_Demand"]),
        )

        actuals = pd.to_numeric(future_frame["RT_LMP"], errors="coerce").to_numpy("float64")
        if not np.isfinite(actuals).all():
            raise ValueError(f"回测日期 {requested} 的真实 RT_LMP 存在缺失值")

        points = []
        p50_values = []
        errors = []
        covered = []
        for item, actual in zip(prediction["hourly"], actuals):
            p10, p50, p90 = item["price_p10"], item["price_p50"], item["price_p90"]
            error = float(p50) - float(actual)  # 正值=预测偏高
            p50_values.append(float(p50))
            errors.append(error)
            covered.append(float(p10) <= float(actual) <= float(p90))
            points.append({
                **item,
                "price_actual": round(float(actual), 2),
                "error_p50": round(error, 2),
            })

        error_array = np.asarray(errors, dtype="float64")
        actual_array = np.asarray(actuals, dtype="float64")
        valid_for_mape = np.abs(actual_array) >= 1.0
        metrics = {
            "count": len(points),
            "mae_usd": round(float(np.mean(np.abs(error_array))), 2),
            "rmse_usd": round(float(np.sqrt(np.mean(error_array ** 2))), 2),
            # LMP 可能接近 0 或为负；只对 |actual| >= $1/MWh 的点计算 MAPE。
            "mape_pct": round(
                float(np.mean(np.abs(error_array[valid_for_mape] / actual_array[valid_for_mape])) * 100), 2
            ) if np.any(valid_for_mape) else None,
            "median_ae_usd": round(float(np.median(np.abs(error_array))), 2),
            "bias_usd": round(float(np.mean(error_array)), 2),
            "p10_p90_coverage": round(float(np.mean(covered) * 100), 1),
        }
        return {
            "available_date_range": date_range,
            "date": requested,
            "origin": str(origin),
            "model": self.MODEL_NAME,
            "data_source": prediction["data_source"],
            "inference_time_ms": prediction["inference_time_ms"],
            "points": points,
            "metrics": metrics,
            "metric_note": "误差 = P50 预测 − 真实 RT_LMP；MAPE 仅统计 |真实电价| ≥ $1/MWh 的小时。",
        }

    # ------------------------------------------------------------------
    # 状态 / 信息
    # ------------------------------------------------------------------
    def get_model_info(self) -> dict:
        return {
            self.MODEL_NAME: {
                "weight": 1.0,
                "num_params": self.NUM_PARAMS,
                "loaded": self._loaded,
                "config": {"encoder": "GRU192", "lookback": 168, "horizon": 24},
                "label": self.MODEL_LABEL,
            }
        }

    def calculate_demo_feature_sensitivity(self) -> list[dict]:
        """对冻结验收窗口计算 TensorFlow v2 分组遮蔽敏感度。"""
        if not self._loaded:
            raise RuntimeError("TF v2 模型未加载")
        from models.tensorflow_load import tf_v2_models as M

        frame = self._frame
        origin = self._origin_ts_local
        pos = int(np.flatnonzero(frame["ts_local"] == origin)[0])
        past = frame.loc[pos - M.LOOKBACK + 1:pos, M.PAST_COLS].to_numpy("float64")
        future = frame.loc[pos + 1:pos + M.HORIZON, M.FUT_COLS].to_numpy("float64")
        base_p = self._sp.transform(past).astype("float32")[None]
        base_f = self._sf.transform(future).astype("float32")[None]

        def load_curve(p_values, f_values):
            raw = np.asarray(self._model.predict([p_values, f_values], verbose=0)["load"])
            return self._sl.inverse_transform(raw.reshape(-1, 1)).reshape(M.HORIZON)

        baseline = load_curve(base_p, base_f)
        groups = {
            "负荷与需求": {"past": ["RT_Demand", "DA_Demand"], "future": ["DA_Demand", "rt_yest"]},
            "电价": {"past": ["RT_LMP", "DA_LMP"], "future": ["DA_LMP"]},
            "气象": {
                "past": ["Dry_Bulb", "Dew_Point", "hdd65", "cdd65", "temp_mem"],
                "future": ["Dry_Bulb", "Dew_Point", "hdd65", "cdd65"],
            },
            "时间与日历": {
                "past": ["clock_hour_sin", "clock_hour_cos", "dow_sin", "dow_cos", "is_holiday", "is_dst"],
                "future": ["clock_hour_sin", "clock_hour_cos", "dow_sin", "dow_cos", "is_holiday", "is_dst"],
            },
        }
        impacts = []
        for label, columns in groups.items():
            altered_p = base_p.copy()
            altered_f = base_f.copy()
            for column in columns["past"]:
                altered_p[0, :, M.PAST_COLS.index(column)] = 0.0
            for column in columns["future"]:
                altered_f[0, :, M.FUT_COLS.index(column)] = 0.0
            delta = load_curve(altered_p, altered_f) - baseline
            impacts.append({
                "feature_group": label,
                "mean_absolute_impact_mw": round(float(np.mean(np.abs(delta))), 2),
                "peak_impact_mw": round(float(np.max(np.abs(delta))), 2),
                "directional_change_mw": round(float(np.mean(delta)), 2),
                "feature_count": len(set(columns["past"] + columns["future"])),
            })
        return sorted(impacts, key=lambda item: item["mean_absolute_impact_mw"], reverse=True)

    def get_status(self) -> dict:
        avg = (self._total_inference_time_ms / self._inference_count
               if self._inference_count else 0.0)
        return {
            "loaded": self._loaded,
            "model": self.MODEL_NAME,
            "model_label": self.MODEL_LABEL,
            "framework": "tensorflow",
            "total_inferences": self._inference_count,
            "average_inference_time_ms": round(avg, 2),
            "origin_ts_local": str(self._origin_ts_local) if self._origin_ts_local else None,
            "assets_dir": str(self.assets_dir),
            "supported_input_modes": ["live_features", "frozen_tail_demo"],
        }

    def release(self) -> None:
        self._loaded = False
        self._model = None
        logger.info("[tf_v2] 模型资源已释放")
