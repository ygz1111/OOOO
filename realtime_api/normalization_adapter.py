"""
智能电网负荷预测系统 - 数据归一化适配器

功能:
  1. 加载训练阶段的 MinMaxScaler 配置 (processed/step5_scalers.pkl)
  2. 对实时生成的 38 维特征进行归一化 (transform)
  3. 对模型预测结果进行逆归一化 (inverse_transform)
  4. 支持单样本和多批次处理
  5. 处理缺失值(NaN)、无穷大(Inf)、零范围特征等边界情况
  6. 数值稳定性处理（裁剪极端值、避免除零）
  7. 返回归一化前后的数据对比

关键原则:
  - 绝不使用实时数据重新 fit Scaler（避免数据泄露）
  - 仅使用训练阶段拟合的 data_min_ / data_max_ 进行 transform
  - 对超出训练范围的值进行裁剪（clip），保持数值稳定

依赖:
  pip install pandas numpy scikit-learn

作者: 毕业设计项目
"""

import os
import pickle
import logging
from typing import Dict, Optional, Any, Tuple, Union, List

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(PROJECT_ROOT, "processed")

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

class NormalizationError(Exception):
    """归一化异常"""
    pass


class ScalerLoadError(NormalizationError):
    """Scaler 加载异常"""
    pass


# ============================================================================
# 数据类定义
# ============================================================================

from dataclasses import dataclass, field

@dataclass
class NormalizationResult:
    """归一化结果（包含前后对比）"""
    original: np.ndarray           # 原始数据
    normalized: np.ndarray          # 归一化后数据
    n_samples: int = 0
    n_features: int = 0
    n_clipped: int = 0             # 被裁剪的值数量
    n_nan_filled: int = 0          # 被填充的NaN数量
    n_inf_replaced: int = 0        # 被替换的Inf数量
    clip_bounds: Tuple[float, float] = (-5.0, 5.0)  # 裁剪边界（归一化空间）
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转为字典"""
        return {
            'n_samples': self.n_samples,
            'n_features': self.n_features,
            'n_clipped': self.n_clipped,
            'n_nan_filled': self.n_nan_filled,
            'n_inf_replaced': self.n_inf_replaced,
            'clip_bounds': self.clip_bounds,
            'warnings': self.warnings,
            'original_range': [float(self.original.min()), float(self.original.max())],
            'normalized_range': [float(self.normalized.min()), float(self.normalized.max())],
        }


# ============================================================================
# 主归一化适配器类
# ============================================================================

class NormalizationAdapter:
    """
    数据归一化适配器

    使用训练阶段拟合的 MinMaxScaler 对实时特征进行归一化/逆归一化。

    核心功能:
      - transform_features(): 38维特征 → 归一化数组 [0, 1]
      - inverse_transform_target(): 归一化预测 → 真实负荷值 (MW)
      - transform_with_comparison(): 归一化并返回前后对比

    边界情况处理:
      1. NaN值: 用该特征的训练中位数填充
      2. Inf值: 替换为该特征的训练最大/最小值
      3. 零范围特征 (data_min_ == data_max_): 输出0
      4. 超出训练范围的值: transform后裁剪到 [-clip_limit, clip_limit]

    Attributes:
        feature_scaler: 训练阶段的特征 MinMaxScaler
        target_scaler: 训练阶段的目标 MinMaxScaler
        feature_cols: 38个特征列名
        clip_limit: 归一化空间中的裁剪边界
        feature_medians: 各特征训练中位数（用于NaN填充）
    """

    # 默认裁剪边界：归一化后的值裁剪到此范围
    # MinMaxScaler 正常输出 [0, 1]，但实时数据可能超出训练范围
    # 允许适度超出（如 -0.5 ~ 1.5），但裁剪极端值避免数值不稳定
    DEFAULT_CLIP_LIMIT = 5.0

    def __init__(
        self,
        scalers_path: Optional[str] = None,
        feature_cols: Optional[List[str]] = None,
        clip_limit: float = None,
    ):
        """
        初始化归一化适配器

        Args:
            scalers_path: Scaler 文件路径 (processed/step5_scalers.pkl)
            feature_cols: 38个特征列名（可选，用于验证）
            clip_limit: 归一化空间裁剪边界（默认5.0）

        Raises:
            ScalerLoadError: Scaler 文件加载失败
        """
        if scalers_path is None:
            scalers_path = os.path.join(PROCESSED_DIR, "step5_scalers.pkl")

        self.clip_limit = clip_limit or self.DEFAULT_CLIP_LIMIT

        # 加载 Scaler
        self._load_scalers(scalers_path)

        # 特征列名
        if feature_cols is None:
            # 尝试从 split_info 加载
            split_info_path = os.path.join(PROCESSED_DIR, "step5_split_info.pkl")
            if os.path.exists(split_info_path):
                with open(split_info_path, "rb") as f:
                    split_info = pickle.load(f)
                feature_cols = split_info.get("feature_cols", [])
        self.feature_cols = feature_cols

        # 预计算训练数据的中位数（用于NaN填充）
        # 从 data_min_ 和 data_max_ 估算（实际中位数不可知，用 (min+max)/2 近似）
        self._feature_fill_values = (
            self.feature_scaler.data_min_ + self.feature_scaler.data_max_
        ) / 2.0

        # 预计算零范围特征（data_min_ == data_max_）
        self._zero_range_mask = (
            self.feature_scaler.data_range_ == 0
        )
        self._zero_range_count = self._zero_range_mask.sum()

        logger.info(f"NormalizationAdapter 初始化完成")
        logger.info(f"  特征数: {self.feature_scaler.n_features_in_}")
        logger.info(f"  目标范围: [{self.target_scaler.data_min_[0]:.1f}, "
                     f"{self.target_scaler.data_max_[0]:.1f}]")
        logger.info(f"  零范围特征数: {self._zero_range_count}")
        logger.info(f"  裁剪边界: [{-self.clip_limit}, {self.clip_limit}]")

    # ========================================================================
    # Scaler 加载
    # ========================================================================

    def _load_scalers(self, scalers_path: str) -> None:
        """
        加载训练阶段的 MinMaxScaler

        Args:
            scalers_path: Scaler 文件路径

        Raises:
            ScalerLoadError: 文件不存在或格式错误
        """
        if not os.path.exists(scalers_path):
            raise ScalerLoadError(
                f"Scaler 文件不存在: {scalers_path}\n"
                f"请确保已运行数据处理管道 (src/data_splitter.py)"
            )

        try:
            with open(scalers_path, "rb") as f:
                scalers = pickle.load(f)

            self.feature_scaler = scalers.get("feature_scaler")
            self.target_scaler = scalers.get("target_scaler")

            if self.feature_scaler is None:
                raise ScalerLoadError("Scaler 文件中缺少 'feature_scaler'")
            if self.target_scaler is None:
                raise ScalerLoadError("Scaler 文件中缺少 'target_scaler'")

            # 验证 Scaler 已 fit
            if not hasattr(self.feature_scaler, 'data_min_') or \
               self.feature_scaler.data_min_ is None:
                raise ScalerLoadError("feature_scaler 未拟合 (data_min_ 为 None)")

            logger.info(f"  Scaler 加载成功: {scalers_path}")
            logger.info(f"  特征 data_min_[:5]: {self.feature_scaler.data_min_[:5]}")
            logger.info(f"  特征 data_max_[:5]: {self.feature_scaler.data_max_[:5]}")

        except ScalerLoadError:
            raise
        except Exception as e:
            raise ScalerLoadError(f"加载 Scaler 失败: {e}")

    # ========================================================================
    # 特征归一化（主入口）
    # ========================================================================

    def transform_features(
        self,
        features: Union[pd.DataFrame, np.ndarray],
        clip: bool = True,
    ) -> np.ndarray:
        """
        对 38 维特征进行归一化

        使用训练阶段的 MinMaxScaler.transform()，
        不重新 fit，避免数据泄露。

        Args:
            features: 38维特征，可以是 DataFrame 或 numpy 数组
            clip: 是否裁剪极端值到 [-clip_limit, clip_limit]

        Returns:
            np.ndarray: 归一化后的数组 (N, 38)，范围大致在 [0, 1]

        Example:
            >>> adapter = NormalizationAdapter()
            >>> normalized = adapter.transform_features(features_df)
            >>> print(normalized.shape)  # (N, 38)
        """
        result = self._transform_internal(features, clip=clip)
        return result.normalized

    def transform_with_comparison(
        self,
        features: Union[pd.DataFrame, np.ndarray],
        clip: bool = True,
    ) -> NormalizationResult:
        """
        归一化并返回前后对比

        Args:
            features: 38维特征
            clip: 是否裁剪极端值

        Returns:
            NormalizationResult: 包含原始数据、归一化数据和处理统计
        """
        return self._transform_internal(features, clip=clip)

    def _transform_internal(
        self,
        features: Union[pd.DataFrame, np.ndarray],
        clip: bool = True,
    ) -> NormalizationResult:
        """归一化内部实现"""
        # 1. 转为 numpy 数组
        original, feature_names = self._to_numpy(features)

        n_samples, n_features = original.shape
        result = NormalizationResult(
            original=original.copy(),
            normalized=np.zeros_like(original, dtype=np.float64),
            n_samples=n_samples,
            n_features=n_features,
        )

        # 2. 处理 NaN
        original, nan_count = self._handle_nan(original, result)

        # 3. 处理 Inf
        original, inf_count = self._handle_inf(original, result)

        # 4. MinMaxScaler transform
        try:
            normalized = self.feature_scaler.transform(original)
        except Exception as e:
            raise NormalizationError(f"Scaler transform 失败: {e}")

        # 5. 处理零范围特征
        if self._zero_range_count > 0:
            normalized[:, self._zero_range_mask] = 0.0
            result.warnings.append(
                f"检测到 {self._zero_range_count} 个零范围特征，已设为0"
            )

        # 6. 裁剪极端值
        if clip:
            clip_mask = (normalized < -self.clip_limit) | (normalized > self.clip_limit)
            clip_count = clip_mask.sum()
            if clip_count > 0:
                normalized = np.clip(normalized, -self.clip_limit, self.clip_limit)
                result.n_clipped = int(clip_count)
                result.warnings.append(
                    f"裁剪了 {clip_count} 个极端值到 [{-self.clip_limit}, {self.clip_limit}]"
                )

        result.normalized = normalized

        # 日志
        logger.info(f"  归一化完成: shape={normalized.shape}")
        logger.info(f"  原始范围: [{result.original.min():.4f}, {result.original.max():.4f}]")
        logger.info(f"  归一化范围: [{normalized.min():.4f}, {normalized.max():.4f}]")
        if result.n_nan_filled > 0:
            logger.info(f"  NaN填充: {result.n_nan_filled}")
        if result.n_inf_replaced > 0:
            logger.info(f"  Inf替换: {result.n_inf_replaced}")
        if result.n_clipped > 0:
            logger.info(f"  极端值裁剪: {result.n_clipped}")

        return result

    # ========================================================================
    # 目标逆归一化
    # ========================================================================

    def inverse_transform_target(
        self,
        normalized_predictions: np.ndarray,
    ) -> np.ndarray:
        """
        将模型预测的归一化值逆转换回真实负荷值 (MW)

        Args:
            normalized_predictions: 模型输出，shape (N, 24) 或 (N, 1)

        Returns:
            np.ndarray: 真实负荷值 (MW)，shape 与输入一致

        Example:
            >>> predictions = model(X)  # 模型输出归一化预测
            >>> real_load = adapter.inverse_transform_target(predictions)
            >>> print(f"预测负荷: {real_load[0]} MW")
        """
        if normalized_predictions is None or len(normalized_predictions) == 0:
            raise NormalizationError("输入预测数据为空")

        predictions = np.asarray(normalized_predictions, dtype=np.float64)

        # 处理 NaN
        nan_mask = np.isnan(predictions)
        if nan_mask.any():
            logger.warning(
                f"预测中含 {nan_mask.sum()} 个NaN，替换为0后逆归一化"
            )
            predictions[nan_mask] = 0.0

        # 处理 Inf
        inf_mask = np.isinf(predictions)
        if inf_mask.any():
            logger.warning(
                f"预测中含 {inf_mask.sum()} 个Inf，替换为0后逆归一化"
            )
            predictions[inf_mask] = 0.0

        # 逆归一化
        # target_scaler 的 data_min_ 和 data_max_ 是 [8617, 24871]
        # inverse_transform: real = normalized * (max - min) + min
        try:
            real_values = self.target_scaler.inverse_transform(predictions)
        except Exception as e:
            # 如果 shape 不匹配，尝试 reshape
            if predictions.ndim == 1:
                real_values = self.target_scaler.inverse_transform(
                    predictions.reshape(-1, 1)
                ).flatten()
            elif predictions.shape[1] != 1:
                # 多输出场景（24小时预测），逐列逆归一化
                # 使用 target_scaler 的单维度参数
                data_min = self.target_scaler.data_min_[0]
                data_max = self.target_scaler.data_max_[0]
                data_range = data_max - data_min
                real_values = predictions * data_range + data_min
            else:
                raise NormalizationError(f"逆归一化失败: {e}")

        # 确保非负（负荷不可能为负）
        negative_count = (real_values < 0).sum()
        if negative_count > 0:
            logger.warning(
                f"逆归一化后 {negative_count} 个负值，裁剪为0"
            )
            real_values = np.maximum(real_values, 0)

        logger.info(
            f"  逆归一化完成: shape={real_values.shape}, "
            f"范围 [{real_values.min():.1f}, {real_values.max():.1f}] MW"
        )

        return real_values

    # ========================================================================
    # 目标归一化（用于评估）
    # ========================================================================

    def transform_target(
        self,
        real_values: Union[pd.Series, np.ndarray, float],
    ) -> np.ndarray:
        """
        将真实负荷值归一化（用于计算评估指标）

        Args:
            real_values: 真实负荷值 (MW)

        Returns:
            np.ndarray: 归一化后的值
        """
        if isinstance(real_values, (int, float)):
            real_values = np.array([[real_values]])

        values = np.asarray(real_values, dtype=np.float64)

        if values.ndim == 1:
            values = values.reshape(-1, 1)

        return self.target_scaler.transform(values)

    # ========================================================================
    # 内部辅助方法
    # ========================================================================

    def _to_numpy(
        self,
        features: Union[pd.DataFrame, np.ndarray],
    ) -> Tuple[np.ndarray, Optional[List[str]]]:
        """
        将输入转为 numpy 数组

        Args:
            features: DataFrame 或 ndarray

        Returns:
            Tuple[ndarray, feature_names]
        """
        if isinstance(features, pd.DataFrame):
            # 验证列数
            if features.shape[1] != self.feature_scaler.n_features_in_:
                raise NormalizationError(
                    f"特征数不匹配: 输入 {features.shape[1]}，"
                    f"Scaler 期望 {self.feature_scaler.n_features_in_}"
                )

            # 如果有特征列名，验证顺序
            if self.feature_cols is not None:
                missing = set(self.feature_cols) - set(features.columns)
                if not missing:
                    # 按正确顺序排列
                    features = features[self.feature_cols]

            return features.values.astype(np.float64), list(features.columns)

        elif isinstance(features, np.ndarray):
            if features.ndim == 1:
                features = features.reshape(1, -1)

            if features.shape[1] != self.feature_scaler.n_features_in_:
                raise NormalizationError(
                    f"特征数不匹配: 输入 {features.shape[1]}，"
                    f"Scaler 期望 {self.feature_scaler.n_features_in_}"
                )

            return features.astype(np.float64), None

        else:
            raise NormalizationError(
                f"不支持的数据类型: {type(features)}，期望 DataFrame 或 ndarray"
            )

    def _handle_nan(
        self,
        data: np.ndarray,
        result: NormalizationResult,
    ) -> Tuple[np.ndarray, int]:
        """
        处理 NaN 值

        策略: 用训练数据的 (min+max)/2 填充
        """
        nan_mask = np.isnan(data)
        nan_count = nan_mask.sum()

        if nan_count > 0:
            # 用每个特征的填充值替换 NaN
            fill_values = np.where(
                nan_mask,
                np.broadcast_to(self._feature_fill_values, data.shape),
                data
            )
            data = fill_values
            result.n_nan_filled = int(nan_count)
            result.warnings.append(
                f"填充了 {nan_count} 个NaN值"
            )
            logger.warning(f"  检测到 {nan_count} 个NaN，用训练中位数填充")

        return data, nan_count

    def _handle_inf(
        self,
        data: np.ndarray,
        result: NormalizationResult,
    ) -> Tuple[np.ndarray, int]:
        """
        处理 Inf 值

        策略: 正Inf用训练最大值替换，负Inf用训练最小值替换
        """
        inf_mask = np.isinf(data)
        inf_count = inf_mask.sum()

        if inf_count > 0:
            pos_inf = np.isposinf(data)
            neg_inf = np.isneginf(data)

            # 正Inf → data_max_，负Inf → data_min_
            data = np.where(
                pos_inf,
                np.broadcast_to(self.feature_scaler.data_max_, data.shape),
                data
            )
            data = np.where(
                neg_inf,
                np.broadcast_to(self.feature_scaler.data_min_, data.shape),
                data
            )
            result.n_inf_replaced = int(inf_count)
            result.warnings.append(
                f"替换了 {inf_count} 个Inf值"
            )
            logger.warning(f"  检测到 {inf_count} 个Inf，用训练边界值替换")

        return data, inf_count

    # ========================================================================
    # 便捷方法
    # ========================================================================

    def get_scaler_info(self) -> Dict[str, Any]:
        """
        获取 Scaler 的详细信息

        Returns:
            dict: 包含 data_min_, data_max_, data_range_ 等信息
        """
        return {
            'feature_scaler': {
                'n_features': self.feature_scaler.n_features_in_,
                'feature_range': list(self.feature_scaler.feature_range),
                'data_min_': self.feature_scaler.data_min_.tolist(),
                'data_max_': self.feature_scaler.data_max_.tolist(),
                'data_range_': self.feature_scaler.data_range_.tolist(),
                'zero_range_features': int(self._zero_range_count),
            },
            'target_scaler': {
                'n_features': self.target_scaler.n_features_in_,
                'data_min_': self.target_scaler.data_min_.tolist(),
                'data_max_': self.target_scaler.data_max_.tolist(),
                'load_range_mw': [
                    float(self.target_scaler.data_min_[0]),
                    float(self.target_scaler.data_max_[0]),
                ],
            },
            'clip_limit': self.clip_limit,
        }

    def validate_features(
        self,
        features: Union[pd.DataFrame, np.ndarray],
    ) -> Dict[str, Any]:
        """
        验证特征数据质量（归一化前检查）

        Args:
            features: 待验证的特征数据

        Returns:
            dict: 验证结果
        """
        data, names = self._to_numpy(features)

        nan_count = np.isnan(data).sum()
        inf_count = np.isinf(data).sum()

        # 检查超出训练范围的值
        below_min = (data < self.feature_scaler.data_min_).sum()
        above_max = (data > self.feature_scaler.data_max_).sum()

        # 按特征统计超出范围
        out_of_range_features = {}
        if names:
            for i, name in enumerate(names):
                below = (data[:, i] < self.feature_scaler.data_min_[i]).sum()
                above = (data[:, i] > self.feature_scaler.data_max_[i]).sum()
                if below > 0 or above > 0:
                    out_of_range_features[name] = {
                        'below_min': int(below),
                        'above_max': int(above),
                        'train_min': float(self.feature_scaler.data_min_[i]),
                        'train_max': float(self.feature_scaler.data_max_[i]),
                        'actual_min': float(data[:, i].min()),
                        'actual_max': float(data[:, i].max()),
                    }

        return {
            'n_samples': data.shape[0],
            'n_features': data.shape[1],
            'nan_count': int(nan_count),
            'inf_count': int(inf_count),
            'below_train_min': int(below_min),
            'above_train_max': int(above_max),
            'out_of_range_features': out_of_range_features,
            'is_valid': nan_count == 0 and inf_count == 0,
        }


# ============================================================================
# 使用示例
# ============================================================================

def demo():
    """演示 NormalizationAdapter 的使用"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from realtime_api.feature_generator import FeatureGenerator, FEATURE_COLS

    print("=" * 60)
    print("数据归一化适配器演示")
    print("=" * 60)

    # 1. 创建适配器
    print("\n[1] 创建归一化适配器...")
    adapter = NormalizationAdapter(feature_cols=FEATURE_COLS)

    # 2. 构造模拟特征数据
    print("\n[2] 构造模拟特征数据...")
    generator = FeatureGenerator()
    timestamps = pd.date_range("2025-07-10", periods=200, freq="h")
    np.random.seed(42)
    weather_df = pd.DataFrame({
        "timestamp": timestamps,
        "location": "Boston",
        "temperature_2m": 25 + 5 * np.sin(np.arange(200) * 2 * np.pi / 24),
        "dew_point_2m": 15 + 3 * np.sin(np.arange(200) * 2 * np.pi / 24),
    })
    load_df = pd.DataFrame({
        "timestamp": timestamps,
        "System_Load": 15000 + 2000 * np.sin(np.arange(200) * 2 * np.pi / 24) + np.random.normal(0, 100, 200),
    })
    features = generator.generate(weather_df, load_df)

    # 3. 归一化（带对比）
    print("\n[3] 归一化特征...")
    result = adapter.transform_with_comparison(features)
    print(f"  原始范围: [{result.original.min():.4f}, {result.original.max():.4f}]")
    print(f"  归一化范围: [{result.normalized.min():.4f}, {result.normalized.max():.4f}]")
    print(f"  NaN填充: {result.n_nan_filled}, Inf替换: {result.n_inf_replaced}")
    print(f"  裁剪: {result.n_clipped}")

    # 4. 模拟模型预测并逆归一化
    print("\n[4] 模拟模型预测逆归一化...")
    # 模拟24小时预测（归一化空间）
    mock_predictions = np.random.uniform(0.2, 0.8, size=(1, 24))
    real_predictions = adapter.inverse_transform_target(mock_predictions)
    print(f"  预测负荷 (MW): {real_predictions[0][:6].round(1)}...")

    # 5. 验证特征质量
    print("\n[5] 特征质量验证...")
    validation = adapter.validate_features(features)
    print(f"  NaN: {validation['nan_count']}, Inf: {validation['inf_count']}")
    print(f"  超出训练范围: {validation['below_train_min'] + validation['above_train_max']}")

    # 6. Scaler 信息
    print("\n[6] Scaler 信息:")
    info = adapter.get_scaler_info()
    print(f"  特征数: {info['feature_scaler']['n_features']}")
    print(f"  负荷范围: {info['target_scaler']['load_range_mw']} MW")

    return adapter, result, real_predictions


if __name__ == "__main__":
    demo()
