# -*- coding: utf-8 -*-
"""
智能电网负荷预测系统 - TensorFlow/Keras 模型推理服务

功能:
  1. 加载 4 个 TensorFlow/Keras 模型 (.keras 文件)
     - EnhancedLSTM (默认权重 24.12%)
     - BiGRU (默认权重 18.75%)
     - DeepTCN (默认权重 17.57%)
     - SpatialTransformer (默认权重 39.56%)
  2. 批量推理 4 个模型，按指定/训练权重加权平均集成
  3. 通过 target_scaler 进行逆归一化，输出工程单位 (MW) 预测结果
  4. 支持单样本 (168, 38) 与批量 (batch, 168, 38) 推理
  5. 性能监控、耗时追踪与健康检查

模型输入: (batch, 168, 38) 归一化特征序列
模型输出: (batch, 24) 归一化预测 → 逆归一化 → MW

说明:
  本文件为独立的 TensorFlow 四模型实验推理模块，不接入当前生产链。
  当需要切换生产后端时，可由上层根据环境变量或配置无缝调度。
"""

import os
import time
import logging
import pickle
import threading
from typing import Dict, Optional, Any, Tuple, List, Union
from dataclasses import dataclass, field
from collections import OrderedDict

import numpy as np
import tensorflow as tf

# 项目路径定义
TF_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.dirname(TF_DIR)
BACKEND_DIR = os.path.dirname(MODELS_DIR)
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
PROCESSED_DIR = os.path.join(PROJECT_ROOT, "processed")

# 自定义层注册引用
from models.tensorflow_load.tf_layers import (
    PositionalEncodingLayer,
    TransformerEncoderBlock,
    GRUAttentionLayer,
    TCNResidualBlock,
)
from models.tensorflow_load.tf_four_models import (
    _last_timestep,
    _scale_01,
    _expand_channel_weights,
    _time_mean,
    LOOKBACK,
    INPUT_DIM,
    OUTPUT_DIM,
)

logger = logging.getLogger(__name__)

CUSTOM_OBJECTS = {
    "PositionalEncodingLayer": PositionalEncodingLayer,
    "TransformerEncoderBlock": TransformerEncoderBlock,
    "GRUAttentionLayer": GRUAttentionLayer,
    "TCNResidualBlock": TCNResidualBlock,
    "_last_timestep": _last_timestep,
    "_scale_01": _scale_01,
    "_expand_channel_weights": _expand_channel_weights,
    "_time_mean": _time_mean,
}

# 原生产集成权重基线
DEFAULT_ENSEMBLE_WEIGHTS = {
    "EnhancedLSTM": 0.2412,
    "BiGRU": 0.1875,
    "DeepTCN": 0.1757,
    "SpatialTransformer": 0.3956,
}


class TFModelInferenceError(Exception):
    """TensorFlow 模型推理异常"""
    pass


class TFModelLoadError(TFModelInferenceError):
    """TensorFlow 模型加载异常"""
    pass


@dataclass
class TFModelInfo:
    """TF 单模型元信息"""
    name: str
    file_path: str
    weight: float
    num_params: int = 0
    loaded: bool = False


@dataclass
class TFInferenceResult:
    """TF 推理输出结果数据类"""
    ensemble_prediction: np.ndarray  # MW
    individual_predictions: Dict[str, np.ndarray] = field(default_factory=dict)  # MW
    normalized_ensemble: Optional[np.ndarray] = None
    normalized_individual: Dict[str, np.ndarray] = field(default_factory=dict)
    inference_time_ms: float = 0.0
    model_times_ms: Dict[str, float] = field(default_factory=dict)
    framework: str = "tensorflow"
    input_shape: Tuple[int, ...] = ()
    output_shape: Tuple[int, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """序列化为标准 JSON 兼容字典"""
        return {
            "framework": self.framework,
            "ensemble_prediction": self.ensemble_prediction.tolist(),
            "individual_predictions": {
                k: v.tolist() for k, v in self.individual_predictions.items()
            },
            "inference_time_ms": round(self.inference_time_ms, 2),
            "model_times_ms": {k: round(v, 2) for k, v in self.model_times_ms.items()},
            "input_shape": list(self.input_shape),
            "output_shape": list(self.output_shape),
        }


class TFPredictionService:
    """TensorFlow 4模型集成负荷预测服务"""

    def __init__(
        self,
        artifacts_dir: Optional[str] = None,
        scalers_path: Optional[str] = None,
        custom_weights: Optional[Dict[str, float]] = None,
    ):
        self.artifacts_dir = artifacts_dir or os.path.join(TF_DIR, "artifacts", "tf_orig")
        self.scalers_path = scalers_path or os.path.join(PROCESSED_DIR, "step5_scalers.pkl")
        self.weights = dict(custom_weights or DEFAULT_ENSEMBLE_WEIGHTS)

        self.models: Dict[str, tf.keras.Model] = {}
        self.model_infos: Dict[str, TFModelInfo] = {}
        self.target_scaler = None
        self._lock = threading.Lock()
        self._initialized = False

    def load_scalers(self) -> None:
        """加载目标反归一化 Scaler"""
        if not os.path.exists(self.scalers_path):
            raise TFModelLoadError(f"Scaler 文件未找到: {self.scalers_path}")
        try:
            with open(self.scalers_path, "rb") as f:
                scalers = pickle.load(f)
            self.target_scaler = scalers.get("target_scaler")
            if self.target_scaler is None:
                raise ValueError("未在 scalers 字典中找到 'target_scaler'")
            logger.info(f"[TFPredictionService] 成功加载 target_scaler: {self.scalers_path}")
        except Exception as e:
            raise TFModelLoadError(f"读取 Scaler 失败: {e}") from e

    def load_models(self) -> None:
        """加载所有 4 个 .keras 权重模型"""
        with self._lock:
            self.load_scalers()
            model_names = ["EnhancedLSTM", "SpatialTransformer", "DeepTCN", "BiGRU"]
            loaded_count = 0

            for name in model_names:
                # 寻找可能的模型文件路径格式：
                # 1. artifacts/{name}/best_{name}.keras
                # 2. artifacts/{name}.keras
                # 3. artifacts/best_{name}.keras
                candidates = [
                    os.path.join(self.artifacts_dir, name, f"best_{name}.keras"),
                    os.path.join(self.artifacts_dir, f"{name}.keras"),
                    os.path.join(self.artifacts_dir, f"best_{name}.keras"),
                    os.path.join(self.artifacts_dir, name, "ckpt_best.keras"),
                ]
                model_path = None
                for c in candidates:
                    if os.path.exists(c):
                        model_path = c
                        break

                if not model_path:
                    logger.warning(f"[TFPredictionService] 未找到模型 {name} 的 .keras 权重，搜索路径: {candidates}")
                    self.model_infos[name] = TFModelInfo(
                        name=name,
                        file_path="",
                        weight=self.weights.get(name, 0.0),
                        loaded=False
                    )
                    continue

                try:
                    logger.info(f"[TFPredictionService] 正在加载 {name} ← {model_path}")
                    model = tf.keras.models.load_model(
                        model_path,
                        custom_objects=CUSTOM_OBJECTS,
                        compile=False,
                    )
                    n_params = sum(int(np.prod(w.shape)) for w in model.trainable_weights)
                    self.models[name] = model
                    self.model_infos[name] = TFModelInfo(
                        name=name,
                        file_path=model_path,
                        weight=self.weights.get(name, 0.0),
                        num_params=n_params,
                        loaded=True,
                    )
                    loaded_count += 1
                except Exception as e:
                    logger.error(f"[TFPredictionService] 加载模型 {name} 失败: {e}")
                    self.model_infos[name] = TFModelInfo(
                        name=name,
                        file_path=model_path,
                        weight=self.weights.get(name, 0.0),
                        loaded=False,
                    )

            if loaded_count == 0:
                raise TFModelLoadError(f"在 {self.artifacts_dir} 未成功加载任何 TF 模型")
            self._initialized = True
            logger.info(f"[TFPredictionService] TF 模型加载完成: {loaded_count}/{len(model_names)} 成功")

    def _normalize_weights(self) -> Dict[str, float]:
        """将可用模型的权重归一化，使其和为 1.0"""
        active_weights = {
            name: self.weights.get(name, 0.0)
            for name in self.models.keys()
        }
        total = sum(active_weights.values())
        if total <= 1e-6:
            # 平均分配
            n = max(len(active_weights), 1)
            return {name: 1.0 / n for name in active_weights}
        return {name: w / total for name, w in active_weights.items()}

    def predict(self, sequence: np.ndarray) -> TFInferenceResult:
        """单样本预测，输入 (168, 38) 或 (1, 168, 38)"""
        if sequence.ndim == 2:
            sequence = np.expand_dims(sequence, axis=0)
        return self.predict_batch(sequence)

    def predict_batch(self, sequences: np.ndarray) -> TFInferenceResult:
        """
        批量预测
        :param sequences: shape (batch_size, 168, 38)
        :return: TFInferenceResult
        """
        if not self._initialized or not self.models:
            self.load_models()

        if sequences.ndim != 3:
            raise TFModelInferenceError(f"输入必须为 3 维 (batch, 168, 38)，当前输入维度: {sequences.ndim}")
        batch_size, lookback, input_dim = sequences.shape
        if lookback != LOOKBACK or input_dim != INPUT_DIM:
            raise TFModelInferenceError(
                f"输入形状 ({lookback}, {input_dim}) 不符合期望 ({LOOKBACK}, {INPUT_DIM})"
            )

        t_total_start = time.perf_counter()
        norm_individual = {}
        model_times_ms = {}
        x_tensor = tf.convert_to_tensor(sequences, dtype=tf.float32)

        for name, model in self.models.items():
            t0 = time.perf_counter()
            # 推理模式调用
            pred_t = model(x_tensor, training=False)
            pred_arr = pred_t.numpy()
            model_times_ms[name] = (time.perf_counter() - t0) * 1000.0
            norm_individual[name] = pred_arr

        norm_weights = self._normalize_weights()
        norm_ensemble = np.zeros((batch_size, OUTPUT_DIM), dtype=np.float32)
        for name, pred in norm_individual.items():
            norm_ensemble += norm_weights[name] * pred

        # 逆归一化到真实 MW
        mw_individual = {}
        for name, pred in norm_individual.items():
            mw_pred = self.target_scaler.inverse_transform(pred.reshape(-1, 1)).reshape(pred.shape)
            mw_individual[name] = mw_pred

        mw_ensemble = self.target_scaler.inverse_transform(
            norm_ensemble.reshape(-1, 1)
        ).reshape(norm_ensemble.shape)

        total_time_ms = (time.perf_counter() - t_total_start) * 1000.0

        return TFInferenceResult(
            ensemble_prediction=mw_ensemble,
            individual_predictions=mw_individual,
            normalized_ensemble=norm_ensemble,
            normalized_individual=norm_individual,
            inference_time_ms=total_time_ms,
            model_times_ms=model_times_ms,
            framework="tensorflow",
            input_shape=sequences.shape,
            output_shape=mw_ensemble.shape,
        )

    def get_model_status(self) -> Dict[str, Any]:
        """获取模型状态信息"""
        return {
            "initialized": self._initialized,
            "artifacts_dir": self.artifacts_dir,
            "scalers_path": self.scalers_path,
            "models": {k: vars(v) for k, v in self.model_infos.items()},
            "weights": self._normalize_weights(),
        }

    def health_check(self) -> Dict[str, Any]:
        """服务健康检查"""
        ok = self._initialized and len(self.models) > 0 and self.target_scaler is not None
        return {
            "status": "healthy" if ok else "unhealthy",
            "models_loaded": len(self.models),
            "initialized": self._initialized,
        }
