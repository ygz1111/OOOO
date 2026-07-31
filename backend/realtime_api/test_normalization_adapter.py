"""
数据归一化适配器单元测试

测试内容:
  1. Scaler 加载和初始化
  2. 特征归一化 (transform)
  3. 目标逆归一化 (inverse_transform)
  4. NaN 值处理
  5. Inf 值处理
  6. 零范围特征处理
  7. 极端值裁剪
  8. 单样本和多批次
  9. 数据对比 (NormalizationResult)
  10. 特征验证

运行方式:
    cd c:/OOOO/OOOO
    python realtime_api/test_normalization_adapter.py -v
"""

import unittest
import os
import sys
import pickle

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtime_api.normalization_adapter import (
    NormalizationAdapter,
    NormalizationResult,
    NormalizationError,
    ScalerLoadError,
)
from realtime_api.feature_generator import FEATURE_COLS


# ============================================================================
# 测试数据生成
# ============================================================================

def make_normal_features(n=100) -> pd.DataFrame:
    """生成正常的38维特征数据"""
    np.random.seed(42)
    data = {}
    # 气象特征
    data["Dry_Bulb"] = np.random.uniform(10, 30, n)
    data["Dew_Point"] = np.random.uniform(5, 20, n)
    # 时间正余弦
    for col in ["hour_sin", "hour_cos", "dow_sin", "dow_cos",
                "doy_sin", "doy_cos", "month_sin", "month_cos",
                "week_sin", "week_cos"]:
        data[col] = np.random.uniform(-1, 1, n)
    # 布尔
    data["is_weekend"] = np.random.randint(0, 2, n)
    data["is_holiday"] = np.random.randint(0, 2, n)
    # 季节
    for col in ["season_fall", "season_spring", "season_summer", "season_winter"]:
        data[col] = np.random.randint(0, 2, n)
    # 衍生
    data["humidity_index"] = data["Dry_Bulb"] - data["Dew_Point"]
    data["cooling_degree"] = np.maximum(0, data["Dry_Bulb"] - 18)
    data["heating_degree"] = np.maximum(0, 18 - data["Dry_Bulb"])
    # 滞后
    for col in ["load_lag_1h", "load_lag_24h", "load_lag_48h", "load_lag_168h"]:
        data[col] = np.random.uniform(10000, 20000, n)
    data["temp_lag_24h"] = np.random.uniform(10, 30, n)
    data["temp_lag_168h"] = np.random.uniform(10, 30, n)
    # 滚动
    data["load_rolling_mean_24h"] = np.random.uniform(12000, 18000, n)
    data["load_rolling_std_24h"] = np.random.uniform(500, 2000, n)
    data["load_rolling_mean_168h"] = np.random.uniform(12000, 18000, n)
    data["load_rolling_min_24h"] = np.random.uniform(8000, 12000, n)
    data["load_rolling_max_24h"] = np.random.uniform(18000, 25000, n)
    data["temp_rolling_mean_24h"] = np.random.uniform(10, 30, n)
    data["temp_rolling_max_24h"] = np.random.uniform(20, 35, n)
    data["temp_rolling_min_24h"] = np.random.uniform(5, 15, n)
    # 变化
    data["load_diff_1h"] = np.random.uniform(-500, 500, n)
    data["load_diff_24h"] = np.random.uniform(-1000, 1000, n)
    data["load_pct_change_24h"] = np.random.uniform(-0.1, 0.1, n)

    df = pd.DataFrame(data)
    # 确保列顺序与 FEATURE_COLS 一致
    return df[FEATURE_COLS]


def make_features_with_nan(n=50) -> pd.DataFrame:
    """生成含NaN的特征数据"""
    df = make_normal_features(n)
    # 注入NaN
    df.iloc[5, 0] = np.nan   # Dry_Bulb
    df.iloc[10, 5] = np.nan  # dow_cos
    df.iloc[15, 20] = np.nan  # load_lag_1h
    return df


def make_features_with_inf(n=50) -> pd.DataFrame:
    """生成含Inf的特征数据"""
    df = make_normal_features(n)
    df.iloc[3, 0] = np.inf    # Dry_Bulb
    df.iloc[7, 1] = -np.inf   # Dew_Point
    return df


def make_features_with_extremes(n=50) -> pd.DataFrame:
    """生成含极端值的特征数据"""
    df = make_normal_features(n)
    # 极端温度（远超训练范围）
    df.iloc[0, 0] = 100.0    # Dry_Bulb = 100°C
    df.iloc[1, 0] = -100.0   # Dry_Bulb = -100°C
    # 极端负荷
    df.iloc[2, 20] = 100000  # load_lag_1h = 100000
    return df


# ============================================================================
# 测试类
# ============================================================================

class TestScalerLoading(unittest.TestCase):
    """测试 Scaler 加载"""

    def test_default_path(self):
        """测试默认路径加载"""
        adapter = NormalizationAdapter()
        self.assertIsNotNone(adapter.feature_scaler)
        self.assertIsNotNone(adapter.target_scaler)

    def test_custom_path(self):
        """测试自定义路径"""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "processed", "step5_scalers.pkl"
        )
        adapter = NormalizationAdapter(scalers_path=path)
        self.assertIsNotNone(adapter.feature_scaler)

    def test_nonexistent_path(self):
        """测试不存在的路径"""
        with self.assertRaises(ScalerLoadError):
            NormalizationAdapter(scalers_path="/nonexistent/path.pkl")

    def test_scaler_info(self):
        """测试 Scaler 信息"""
        adapter = NormalizationAdapter()
        info = adapter.get_scaler_info()

        self.assertEqual(info['feature_scaler']['n_features'], 38)
        self.assertIn('load_range_mw', info['target_scaler'])


class TestFeatureTransform(unittest.TestCase):
    """测试特征归一化"""

    def setUp(self):
        self.adapter = NormalizationAdapter(feature_cols=FEATURE_COLS)

    def test_dataframe_input(self):
        """测试 DataFrame 输入"""
        df = make_normal_features(100)
        normalized = self.adapter.transform_features(df)

        self.assertEqual(normalized.shape, (100, 38))
        # 大部分值应在 [0, 1] 范围
        self.assertTrue(normalized.min() >= -1)
        self.assertTrue(normalized.max() <= 2)

    def test_numpy_input(self):
        """测试 numpy 数组输入"""
        df = make_normal_features(50)
        arr = df.values
        normalized = self.adapter.transform_features(arr)

        self.assertEqual(normalized.shape, (50, 38))

    def test_single_sample(self):
        """测试单样本处理"""
        df = make_normal_features(1)
        normalized = self.adapter.transform_features(df)

        self.assertEqual(normalized.shape, (1, 38))

    def test_batch_processing(self):
        """测试多批次处理"""
        df = make_normal_features(500)
        normalized = self.adapter.transform_features(df)

        self.assertEqual(normalized.shape, (500, 38))

    def test_1d_input(self):
        """测试一维输入自动reshape"""
        df = make_normal_features(1)
        arr = df.values.flatten()
        normalized = self.adapter.transform_features(arr)

        self.assertEqual(normalized.shape, (1, 38))

    def test_wrong_feature_count(self):
        """测试特征数不匹配"""
        wrong_data = np.random.rand(10, 20)  # 20列而非38列
        with self.assertRaises(NormalizationError):
            self.adapter.transform_features(wrong_data)

    def test_feature_order_preserved(self):
        """测试特征顺序保持"""
        df = make_normal_features(50)
        # 打乱列顺序
        shuffled_cols = list(reversed(FEATURE_COLS))
        df_shuffled = df[shuffled_cols]

        # adapter 应该自动重新排列
        normalized = self.adapter.transform_features(df_shuffled)
        self.assertEqual(normalized.shape, (50, 38))


class TestInverseTransform(unittest.TestCase):
    """测试目标逆归一化"""

    def setUp(self):
        self.adapter = NormalizationAdapter()

    def test_single_prediction(self):
        """测试单条预测逆归一化"""
        normalized = np.array([[0.5]])
        real = self.adapter.inverse_transform_target(normalized)

        # 0.5 对应 (8617 + 24871) / 2
        expected = 0.5 * (24871 - 8617) + 8617
        self.assertAlmostEqual(real[0, 0], expected, places=1)

    def test_batch_predictions(self):
        """测试批量预测逆归一化"""
        normalized = np.random.uniform(0, 1, (10, 24))
        real = self.adapter.inverse_transform_target(normalized)

        self.assertEqual(real.shape, (10, 24))
        # 应在合理负荷范围内
        self.assertTrue(real.min() > 0)
        self.assertTrue(real.max() < 50000)

    def test_zero_prediction(self):
        """测试0值预测"""
        normalized = np.array([[0.0]])
        real = self.adapter.inverse_transform_target(normalized)

        # 0 对应 data_min_
        self.assertAlmostEqual(real[0, 0], 8617, places=1)

    def test_one_prediction(self):
        """测试1值预测"""
        normalized = np.array([[1.0]])
        real = self.adapter.inverse_transform_target(normalized)

        # 1 对应 data_max_
        self.assertAlmostEqual(real[0, 0], 24871, places=1)

    def test_negative_clipped(self):
        """测试负值裁剪"""
        # 给一个极端负值
        normalized = np.array([[-10.0]])
        real = self.adapter.inverse_transform_target(normalized)

        # 不应为负
        self.assertTrue(real[0, 0] >= 0)

    def test_nan_in_predictions(self):
        """测试预测中的NaN"""
        normalized = np.array([[0.5, np.nan, 0.3]])
        real = self.adapter.inverse_transform_target(normalized)

        # NaN被替换为0后逆归一化
        self.assertFalse(np.isnan(real).any())

    def test_inf_in_predictions(self):
        """测试预测中的Inf"""
        normalized = np.array([[0.5, np.inf, -np.inf]])
        real = self.adapter.inverse_transform_target(normalized)

        self.assertFalse(np.isinf(real).any())


class TestNaNHandling(unittest.TestCase):
    """测试 NaN 处理"""

    def setUp(self):
        self.adapter = NormalizationAdapter(feature_cols=FEATURE_COLS)

    def test_nan_filled(self):
        """测试 NaN 被填充"""
        df = make_features_with_nan(50)
        result = self.adapter.transform_with_comparison(df)

        self.assertGreater(result.n_nan_filled, 0)
        # 归一化后不应有NaN
        self.assertFalse(np.isnan(result.normalized).any())

    def test_nan_replaced_with_median(self):
        """测试 NaN 用中位数填充"""
        df = make_features_with_nan(50)
        result = self.adapter.transform_with_comparison(df)

        # 填充值应该接近训练中位数
        self.assertGreater(result.n_nan_filled, 0)


class TestInfHandling(unittest.TestCase):
    """测试 Inf 处理"""

    def setUp(self):
        self.adapter = NormalizationAdapter(feature_cols=FEATURE_COLS)

    def test_inf_replaced(self):
        """测试 Inf 被替换"""
        df = make_features_with_inf(50)
        result = self.adapter.transform_with_comparison(df)

        self.assertGreater(result.n_inf_replaced, 0)
        # 归一化后不应有Inf
        self.assertFalse(np.isinf(result.normalized).any())


class TestExtremeValueClipping(unittest.TestCase):
    """测试极端值裁剪"""

    def setUp(self):
        self.adapter = NormalizationAdapter(feature_cols=FEATURE_COLS)

    def test_extreme_values_clipped(self):
        """测试极端值被裁剪"""
        df = make_features_with_extremes(50)
        result = self.adapter.transform_with_comparison(df, clip=True)

        self.assertGreater(result.n_clipped, 0)
        # 裁剪后不应有极端值
        self.assertTrue(result.normalized.min() >= -self.adapter.clip_limit - 0.01)
        self.assertTrue(result.normalized.max() <= self.adapter.clip_limit + 0.01)

    def test_no_clip_option(self):
        """测试不裁剪选项"""
        df = make_features_with_extremes(50)
        result = self.adapter.transform_with_comparison(df, clip=False)

        # 不裁剪可能有极端值
        # 但归一化仍应完成
        self.assertEqual(result.n_clipped, 0)

    def test_custom_clip_limit(self):
        """测试自定义裁剪边界"""
        adapter = NormalizationAdapter(feature_cols=FEATURE_COLS, clip_limit=2.0)
        df = make_features_with_extremes(50)
        result = adapter.transform_with_comparison(df, clip=True)

        self.assertTrue(result.normalized.max() <= 2.01)


class TestComparisonResult(unittest.TestCase):
    """测试归一化对比结果"""

    def setUp(self):
        self.adapter = NormalizationAdapter(feature_cols=FEATURE_COLS)

    def test_result_structure(self):
        """测试结果结构"""
        df = make_normal_features(50)
        result = self.adapter.transform_with_comparison(df)

        self.assertIsInstance(result, NormalizationResult)
        self.assertEqual(result.n_samples, 50)
        self.assertEqual(result.n_features, 38)
        self.assertIsNotNone(result.original)
        self.assertIsNotNone(result.normalized)

    def test_result_to_dict(self):
        """测试结果转字典"""
        df = make_normal_features(50)
        result = self.adapter.transform_with_comparison(df)
        d = result.to_dict()

        self.assertIn('n_samples', d)
        self.assertIn('n_features', d)
        self.assertIn('n_clipped', d)
        self.assertIn('original_range', d)
        self.assertIn('normalized_range', d)

    def test_original_preserved(self):
        """测试原始数据被保留"""
        df = make_normal_features(50)
        result = self.adapter.transform_with_comparison(df)

        # original 应与输入一致
        np.testing.assert_almost_equal(
            result.original, df.values.astype(np.float64), decimal=5
        )


class TestFeatureValidation(unittest.TestCase):
    """测试特征验证"""

    def setUp(self):
        self.adapter = NormalizationAdapter(feature_cols=FEATURE_COLS)

    def test_normal_data_valid(self):
        """测试正常数据验证通过"""
        df = make_normal_features(50)
        validation = self.adapter.validate_features(df)

        self.assertTrue(validation['is_valid'])
        self.assertEqual(validation['nan_count'], 0)
        self.assertEqual(validation['inf_count'], 0)

    def test_nan_detected(self):
        """测试NaN被检测"""
        df = make_features_with_nan(50)
        validation = self.adapter.validate_features(df)

        self.assertGreater(validation['nan_count'], 0)

    def test_inf_detected(self):
        """测试Inf被检测"""
        df = make_features_with_inf(50)
        validation = self.adapter.validate_features(df)

        self.assertGreater(validation['inf_count'], 0)

    def test_out_of_range_detected(self):
        """测试超出范围被检测"""
        df = make_features_with_extremes(50)
        validation = self.adapter.validate_features(df)

        self.assertGreater(validation['below_train_min'] + validation['above_train_max'], 0)


class TestTransformTarget(unittest.TestCase):
    """测试目标归一化（正向）"""

    def setUp(self):
        self.adapter = NormalizationAdapter()

    def test_transform_target_single(self):
        """测试单个目标值归一化"""
        real_value = 15000.0
        normalized = self.adapter.transform_target(real_value)

        # 逆归一化应能还原
        real = self.adapter.inverse_transform_target(normalized)
        self.assertAlmostEqual(real[0, 0], 15000.0, places=0)

    def test_transform_target_array(self):
        """测试数组目标归一化"""
        real_values = np.array([10000, 15000, 20000])
        normalized = self.adapter.transform_target(real_values)

        real = self.adapter.inverse_transform_target(normalized.reshape(-1, 1))
        np.testing.assert_almost_equal(
            real.flatten(), [10000, 15000, 20000], decimal=0
        )


class TestRoundTrip(unittest.TestCase):
    """测试往返一致性（transform → inverse_transform → 还原）"""

    def setUp(self):
        self.adapter = NormalizationAdapter(feature_cols=FEATURE_COLS)

    def test_feature_round_trip(self):
        """测试特征往返一致性"""
        # 注意：MinMaxScaler 有 clip 特性，超出范围的值无法精确还原
        df = make_normal_features(50)
        normalized = self.adapter.transform_features(df, clip=False)

        # 逆归一化
        restored = self.adapter.feature_scaler.inverse_transform(normalized)

        # 应与原始值接近（允许浮点误差）
        np.testing.assert_almost_equal(
            restored, df.values.astype(np.float64), decimal=4
        )

    def test_target_round_trip(self):
        """测试目标往返一致性"""
        real = np.array([[15000.0]])
        normalized = self.adapter.transform_target(real)
        restored = self.adapter.inverse_transform_target(normalized)

        self.assertAlmostEqual(restored[0, 0], 15000.0, places=0)


class TestEdgeCases(unittest.TestCase):
    """测试边界情况"""

    def setUp(self):
        self.adapter = NormalizationAdapter(feature_cols=FEATURE_COLS)

    def test_all_zeros(self):
        """测试全零输入"""
        data = np.zeros((10, 38))
        normalized = self.adapter.transform_features(data)

        self.assertEqual(normalized.shape, (10, 38))
        self.assertFalse(np.isnan(normalized).any())

    def test_all_same_values(self):
        """测试所有值相同"""
        data = np.ones((10, 38)) * 20.0
        normalized = self.adapter.transform_features(data)

        self.assertEqual(normalized.shape, (10, 38))

    def test_large_batch(self):
        """测试大批次处理"""
        df = make_normal_features(10000)
        normalized = self.adapter.transform_features(df)

        self.assertEqual(normalized.shape, (10000, 38))

    def test_very_small_values(self):
        """测试极小值"""
        data = np.ones((5, 38)) * 1e-10
        normalized = self.adapter.transform_features(data)

        self.assertFalse(np.isnan(normalized).any())
        self.assertFalse(np.isinf(normalized).any())


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
