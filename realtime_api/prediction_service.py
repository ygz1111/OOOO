"""
智能电网负荷预测系统 - 模型推理服务

功能:
  1. 加载4个PyTorch模型 (.pth 文件)
     - EnhancedLSTM (权重 35%)
     - BiGRU (权重 30%)
     - DeepTCN (权重 15%)
     - SpatialTemporalTransformer (权重 20%)
  2. 批量推理4个模型，加权平均集成
  3. 输出逆归一化的预测结果 (MW)
  4. 支持GPU和CPU推理
  5. 单次推理 < 1秒，支持并发
  6. 详细的性能监控和错误处理

模型输入: (batch, 168, 38) 归一化特征序列
模型输出: (batch, 24) 归一化预测 → 逆归一化 → MW

依赖:
  pip install torch numpy pandas

作者: 毕业设计项目
"""

import os
import time
import logging
import threading
from typing import Dict, Optional, Any, Tuple, List, Union
from dataclasses import dataclass, field
from collections import OrderedDict

import numpy as np
import torch
import torch.nn as nn

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "outputs")
PROCESSED_DIR = os.path.join(PROJECT_ROOT, "processed")

# 添加模型路径
import sys
sys.path.insert(0, PROJECT_ROOT)

# 导入模型类
from models.four_models import EnhancedLSTM, SpatialTemporalTransformer, DeepTCN, BiGRU

# 导入归一化适配器
from realtime_api.normalization_adapter import NormalizationAdapter

# ============================================================================
# 日志配置
# ============================================================================
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )


# ============================================================================
# 异常定义
# ============================================================================

class ModelInferenceError(Exception):
    """模型推理异常"""
    pass


class ModelLoadError(ModelInferenceError):
    """模型加载异常"""
    pass


# ============================================================================
# 数据类
# ============================================================================

@dataclass
class ModelInfo:
    """模型信息"""
    name: str
    file_path: str
    weight: float
    num_params: int = 0
    loaded: bool = False
    device: str = "cpu"


@dataclass
class InferenceResult:
    """推理结果"""
    # 集成预测 (MW)
    ensemble_prediction: np.ndarray
    # 各模型单独预测 (MW)
    individual_predictions: Dict[str, np.ndarray] = field(default_factory=dict)
    # 归一化空间预测
    normalized_ensemble: np.ndarray = None
    normalized_individual: Dict[str, np.ndarray] = field(default_factory=dict)
    # 性能信息
    inference_time_ms: float = 0.0
    model_times_ms: Dict[str, float] = field(default_factory=dict)
    device: str = "cpu"
    input_shape: Tuple[int, ...] = ()
    output_shape: Tuple[int, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """转为字典（numpy转为list）"""
        return {
            'ensemble_prediction': self.ensemble_prediction.tolist(),
            'individual_predictions': {
                k: v.tolist() for k, v in self.individual_predictions.items()
            },
            'inference_time_ms': round(self.inference_time_ms, 2),
            'model_times_ms': {k: round(v, 2) for k, v in self.model_times_ms.items()},
            'device': self.device,
            'input_shape': list(self.input_shape),
            'output_shape': list(self.output_shape),
        }


# ============================================================================
# 模型配置（与训练阶段 models/four_models.py 中的 create_four_models() 一致）
# ============================================================================

MODEL_CONFIGS = OrderedDict([
    ("EnhancedLSTM", {
        "class": EnhancedLSTM,
        "file": "enhancedlstm_best_model.pth",
        "weight": 0.35,
        "params": {
            "input_size": 38,
            "hidden_size": 128,
            "num_layers": 3,
            "output_size": 24,
            "dropout": 0.3,
            "l2_reg": 1e-4,
        }
    }),
    ("BiGRU", {
        "class": BiGRU,
        "file": "bigru_best_model.pth",
        "weight": 0.30,
        "params": {
            "input_size": 38,
            "hidden_size": 128,
            "num_layers": 3,
            "output_size": 24,
            "dropout": 0.3,
            "l2_reg": 1e-4,
        }
    }),
    ("DeepTCN", {
        "class": DeepTCN,
        "file": "deeptcn_best_model.pth",
        "weight": 0.15,
        "params": {
            "input_size": 38,
            "num_channels": [64, 128, 64, 32],
            "kernel_size": 3,
            "output_size": 24,
            "dropout": 0.3,
            "l2_reg": 1e-4,
        }
    }),
    ("SpatialTransformer", {
        "class": SpatialTemporalTransformer,
        "file": "spatialtransformer_best_model.pth",
        "weight": 0.20,
        "params": {
            "input_size": 38,
            "d_model": 128,
            "nhead": 8,
            "num_layers": 4,
            "d_ff": 512,
            "output_size": 24,
            "dropout": 0.3,
            "l2_reg": 1e-4,
        }
    }),
])


# ============================================================================
# 主推理服务类
# ============================================================================

class ModelInferenceService:
    """
    深度学习模型推理服务

    管理4个PyTorch模型的加载、推理和集成预测。

    核心功能:
      - load_models(): 加载4个模型权重
      - predict(): 单次推理（集成预测）
      - predict_batch(): 批量推理
      - get_model_info(): 获取模型信息

    性能特征:
      - 单次推理 < 1秒 (CPU)
      - 线程安全（支持并发调用）
      - 自动设备选择 (GPU优先)
      - 内存优化 (eval模式 + no_grad)

    Attributes:
        models: 已加载的模型字典
        device: 推理设备 (cpu/cuda)
        ensemble_weights: 集成权重
        normalizer: 归一化适配器（用于逆归一化）
    """

    def __init__(
        self,
        models_dir: Optional[str] = None,
        device: Optional[str] = None,
        use_normalizer: bool = True,
        scalers_path: Optional[str] = None,
    ):
        """
        初始化推理服务

        Args:
            models_dir: 模型文件目录 (默认 outputs/)
            device: 推理设备 ('cpu' or 'cuda'，默认自动选择)
            use_normalizer: 是否加载归一化适配器
            scalers_path: Scaler文件路径
        """
        self.models_dir = models_dir or OUTPUTS_DIR

        # 设备选择
        if device is None:
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        else:
            self.device = torch.device(device)

        # 模型存储
        self.models: Dict[str, nn.Module] = {}
        self.model_infos: Dict[str, ModelInfo] = {}

        # 集成权重
        self.ensemble_weights = {
            name: config["weight"]
            for name, config in MODEL_CONFIGS.items()
        }

        # 归一化适配器
        self.normalizer: Optional[NormalizationAdapter] = None
        if use_normalizer:
            try:
                self.normalizer = NormalizationAdapter(scalers_path=scalers_path)
            except Exception as e:
                logger.warning(f"归一化适配器加载失败: {e}，预测结果将不逆归一化")

        # 线程锁（保证并发安全）
        self._lock = threading.Lock()

        # 推理统计
        self._inference_count = 0
        self._total_inference_time = 0.0

        logger.info(f"ModelInferenceService 初始化")
        logger.info(f"  设备: {self.device}")
        logger.info(f"  模型目录: {self.models_dir}")
        logger.info(f"  集成权重: {self.ensemble_weights}")

    # ========================================================================
    # 模型加载
    # ========================================================================

    def load_models(self) -> None:
        """
        加载全部4个模型

        Raises:
            ModelLoadError: 模型加载失败
        """
        logger.info("=" * 60)
        logger.info("开始加载模型")
        logger.info("=" * 60)

        loaded_count = 0

        for model_name, config in MODEL_CONFIGS.items():
            try:
                model = self._load_single_model(
                    model_name=model_name,
                    model_class=config["class"],
                    file_name=config["file"],
                    params=config["params"],
                    weight=config["weight"],
                )
                self.models[model_name] = model
                loaded_count += 1

            except Exception as e:
                logger.error(f"❌ 模型 {model_name} 加载失败: {e}")
                self.model_infos[model_name] = ModelInfo(
                    name=model_name,
                    file_path=os.path.join(self.models_dir, config["file"]),
                    weight=config["weight"],
                    loaded=False,
                )

        if loaded_count == 0:
            raise ModelLoadError("所有模型加载失败，无法进行推理")

        logger.info(f"\n✅ 模型加载完成: {loaded_count}/{len(MODEL_CONFIGS)}")

        # 如果部分模型加载失败，重新分配权重
        if loaded_count < len(MODEL_CONFIGS):
            self._redistribute_weights()
            logger.warning(f"⚠️ 部分模型未加载，已重新分配权重: {self.ensemble_weights}")

        # 设备信息
        if self.device.type == 'cuda':
            logger.info(f"🚀 GPU: {torch.cuda.get_device_name(0)}")
            mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
            logger.info(f"💽 GPU显存: {mem:.1f}GB")

    def _load_single_model(
        self,
        model_name: str,
        model_class: type,
        file_name: str,
        params: dict,
        weight: float,
    ) -> nn.Module:
        """
        加载单个模型

        Args:
            model_name: 模型名称
            model_class: 模型类
            file_name: 权重文件名
            params: 模型构造参数
            weight: 集成权重

        Returns:
            加载好的模型 (eval模式)

        Raises:
            ModelLoadError: 加载失败
        """
        file_path = os.path.join(self.models_dir, file_name)

        if not os.path.exists(file_path):
            raise ModelLoadError(f"权重文件不存在: {file_path}")

        logger.info(f"  加载 {model_name} ← {file_name}")

        # 1. 创建模型实例
        try:
            model = model_class(**params)
        except Exception as e:
            raise ModelLoadError(f"模型实例化失败: {e}")

        # 2. 加载权重
        try:
            checkpoint = torch.load(
                file_path,
                map_location=self.device,
                weights_only=False,
            )
        except Exception as e:
            raise ModelLoadError(f"权重文件加载失败: {e}")

        # 3. 提取 state_dict
        if isinstance(checkpoint, dict) and 'model_state_dict' in checkpoint:
            state_dict = checkpoint['model_state_dict']
        elif isinstance(checkpoint, dict) and 'state_dict' in checkpoint:
            state_dict = checkpoint['state_dict']
        else:
            state_dict = checkpoint

        # 4. 加载 state_dict
        try:
            model.load_state_dict(state_dict, strict=True)
        except RuntimeError as e:
            logger.warning(f"  strict加载失败，尝试非strict模式: {e}")
            model.load_state_dict(state_dict, strict=False)

        # 5. 移动到设备，设为eval模式
        model = model.to(self.device)
        model.eval()

        # 6. 记录信息
        num_params = sum(p.numel() for p in model.parameters())
        self.model_infos[model_name] = ModelInfo(
            name=model_name,
            file_path=file_path,
            weight=weight,
            num_params=num_params,
            loaded=True,
            device=str(self.device),
        )

        logger.info(f"  ✅ {model_name}: {num_params:,} 参数, 权重={weight:.0%}")

        return model

    def _redistribute_weights(self) -> None:
        """重新分配权重（当部分模型加载失败时）"""
        loaded_names = list(self.models.keys())
        if not loaded_names:
            return

        # 按原始权重比例重新分配
        total_weight = sum(MODEL_CONFIGS[n]["weight"] for n in loaded_names)
        for name in loaded_names:
            original_weight = MODEL_CONFIGS[name]["weight"]
            self.ensemble_weights[name] = original_weight / total_weight

    # ========================================================================
    # 推理
    # ========================================================================

    def predict(
        self,
        X: Union[np.ndarray, torch.Tensor],
        inverse_transform: bool = True,
    ) -> InferenceResult:
        """
        执行集成预测

        Args:
            X: 归一化特征序列，shape (batch, 168, 38) 或 (168, 38)
            inverse_transform: 是否逆归一化为真实MW值

        Returns:
            InferenceResult: 包含集成预测和各模型单独预测

        Example:
            >>> service = ModelInferenceService()
            >>> service.load_models()
            >>> result = service.predict(X)
            >>> print(result.ensemble_prediction)  # (batch, 24) MW
        """
        if not self.models:
            raise ModelInferenceError("没有已加载的模型，请先调用 load_models()")

        # 1. 预处理输入
        X_tensor = self._prepare_input(X)

        # 2. 批量推理
        with self._lock:
            result = self._run_inference(X_tensor, inverse_transform)

        # 3. 更新统计
        self._inference_count += 1
        self._total_inference_time += result.inference_time_ms

        return result

    def _prepare_input(self, X: Union[np.ndarray, torch.Tensor]) -> torch.Tensor:
        """
        预处理输入数据

        - numpy → tensor
        - 确保维度 (batch, seq_len, features)
        - 移动到设备
        - 数值检查
        """
        if isinstance(X, np.ndarray):
            X_tensor = torch.from_numpy(X).float()
        elif isinstance(X, torch.Tensor):
            X_tensor = X.float()
        else:
            raise ModelInferenceError(
                f"不支持的输入类型: {type(X)}，期望 numpy.ndarray 或 torch.Tensor"
            )

        # 确保至少3维 (batch, seq, features)
        if X_tensor.ndim == 2:
            X_tensor = X_tensor.unsqueeze(0)  # (seq, features) → (1, seq, features)
        elif X_tensor.ndim != 3:
            raise ModelInferenceError(
                f"输入维度错误: {X_tensor.ndim}D，期望 2D 或 3D"
            )

        # 检查特征数
        if X_tensor.shape[-1] != 38:
            raise ModelInferenceError(
                f"特征数错误: {X_tensor.shape[-1]}，期望 38"
            )

        # 数值检查
        if torch.isnan(X_tensor).any():
            logger.warning("输入包含NaN，替换为0")
            X_tensor = torch.nan_to_num(X_tensor, nan=0.0)

        if torch.isinf(X_tensor).any():
            logger.warning("输入包含Inf，替换为0")
            X_tensor = torch.nan_to_num(X_tensor, posinf=1.0, neginf=0.0)

        # 移动到设备
        X_tensor = X_tensor.to(self.device)

        return X_tensor

    def _run_inference(
        self,
        X: torch.Tensor,
        inverse_transform: bool,
    ) -> InferenceResult:
        """
        执行推理核心逻辑

        Args:
            X: 预处理后的输入 tensor
            inverse_transform: 是否逆归一化

        Returns:
            InferenceResult
        """
        batch_size = X.shape[0]
        total_start = time.perf_counter()

        normalized_predictions = {}
        model_times = {}

        # 逐模型推理
        for model_name, model in self.models.items():
            model_start = time.perf_counter()

            try:
                with torch.no_grad():
                    pred = model(X)

                # 检查输出
                if torch.isnan(pred).any():
                    logger.warning(f"  {model_name} 输出包含NaN，替换为0")
                    pred = torch.nan_to_num(pred, nan=0.0)

                if torch.isinf(pred).any():
                    logger.warning(f"  {model_name} 输出包含Inf，替换为0")
                    pred = torch.nan_to_num(pred, posinf=0.5, neginf=0.0)

                normalized_predictions[model_name] = pred.cpu().numpy()
                model_times[model_name] = (time.perf_counter() - model_start) * 1000

                logger.debug(
                    f"  {model_name}: {model_times[model_name]:.1f}ms, "
                    f"output={pred.shape}"
                )

            except Exception as e:
                logger.error(f"  ❌ {model_name} 推理失败: {e}")
                # 使用其他模型的平均值作为替代
                if normalized_predictions:
                    avg_pred = np.mean(
                        list(normalized_predictions.values()), axis=0
                    )
                    normalized_predictions[model_name] = avg_pred
                    model_times[model_name] = 0.0
                else:
                    raise ModelInferenceError(f"{model_name} 推理失败且无替代: {e}")

        # 加权集成
        ensemble_normalized = np.zeros_like(
            list(normalized_predictions.values())[0]
        )
        for model_name, pred in normalized_predictions.items():
            weight = self.ensemble_weights[model_name]
            ensemble_normalized += weight * pred

        total_time = (time.perf_counter() - total_start) * 1000

        # 逆归一化
        if inverse_transform and self.normalizer is not None:
            ensemble_real = self.normalizer.inverse_transform_target(ensemble_normalized)
            individual_real = {}
            for name, pred in normalized_predictions.items():
                individual_real[name] = self.normalizer.inverse_transform_target(pred)
        else:
            ensemble_real = ensemble_normalized
            individual_real = normalized_predictions

        result = InferenceResult(
            ensemble_prediction=ensemble_real,
            individual_predictions=individual_real,
            normalized_ensemble=ensemble_normalized,
            normalized_individual=normalized_predictions,
            inference_time_ms=total_time,
            model_times_ms=model_times,
            device=str(self.device),
            input_shape=tuple(X.shape),
            output_shape=ensemble_real.shape,
        )

        logger.info(
            f"  推理完成: {total_time:.1f}ms, "
            f"batch={batch_size}, "
            f"output={ensemble_real.shape}"
        )

        return result

    # ========================================================================
    # 便捷方法
    # ========================================================================

    def predict_single(
        self,
        X: Union[np.ndarray, torch.Tensor],
    ) -> np.ndarray:
        """
        单次预测，只返回集成预测结果

        Args:
            X: 输入序列 (168, 38) 或 (1, 168, 38)

        Returns:
            np.ndarray: 24小时预测 (24,) 或 (batch, 24)
        """
        result = self.predict(X, inverse_transform=True)
        if result.ensemble_prediction.shape[0] == 1:
            return result.ensemble_prediction[0]  # (24,)
        return result.ensemble_prediction

    def predict_batch(
        self,
        X: Union[np.ndarray, torch.Tensor],
    ) -> InferenceResult:
        """
        批量预测

        Args:
            X: 批量输入 (batch, 168, 38)

        Returns:
            InferenceResult
        """
        return self.predict(X, inverse_transform=True)

    # ========================================================================
    # 信息和监控
    # ========================================================================

    def get_model_info(self) -> Dict[str, Any]:
        """获取所有模型信息"""
        return {
            name: {
                'name': info.name,
                'file_path': info.file_path,
                'weight': info.weight,
                'num_params': info.num_params,
                'loaded': info.loaded,
                'device': info.device,
            }
            for name, info in self.model_infos.items()
        }

    def get_performance_stats(self) -> Dict[str, Any]:
        """获取推理性能统计"""
        avg_time = (
            self._total_inference_time / self._inference_count
            if self._inference_count > 0 else 0.0
        )
        return {
            'total_inferences': self._inference_count,
            'total_time_ms': round(self._total_inference_time, 2),
            'average_time_ms': round(avg_time, 2),
            'device': str(self.device),
            'models_loaded': len(self.models),
            'ensemble_weights': self.ensemble_weights,
        }

    def is_ready(self) -> bool:
        """检查服务是否就绪"""
        return len(self.models) > 0

    # ========================================================================
    # 资源管理
    # ========================================================================

    def release(self) -> None:
        """释放模型资源"""
        self.models.clear()
        if self.device.type == 'cuda':
            torch.cuda.empty_cache()
        logger.info("模型资源已释放")


# ============================================================================
# 使用示例
# ============================================================================

def demo():
    """演示模型推理服务"""
    print("=" * 60)
    print("模型推理服务演示")
    print("=" * 60)

    # 1. 创建服务并加载模型
    print("\n[1] 加载模型...")
    service = ModelInferenceService()
    service.load_models()

    # 2. 构造模拟输入
    print("\n[2] 构造模拟输入...")
    np.random.seed(42)
    X = np.random.uniform(0, 1, size=(1, 168, 38)).astype(np.float32)
    print(f"  输入形状: {X.shape}")

    # 3. 推理
    print("\n[3] 执行推理...")
    result = service.predict(X)

    print(f"\n  集成预测 (MW): {result.ensemble_prediction[0][:6].round(1)}...")
    print(f"  推理耗时: {result.inference_time_ms:.1f}ms")
    print(f"  设备: {result.device}")

    print("\n  各模型预测:")
    for name, pred in result.individual_predictions.items():
        print(f"    {name}: {pred[0][:4].round(1)}...")

    # 4. 性能统计
    print("\n[4] 性能统计:")
    stats = service.get_performance_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # 5. 模型信息
    print("\n[5] 模型信息:")
    info = service.get_model_info()
    for name, data in info.items():
        print(f"  {name}: {data['num_params']:,} params, weight={data['weight']:.0%}")

    return service, result


if __name__ == "__main__":
    demo()
