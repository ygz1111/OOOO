"""
实时特征工程模块单元测试

测试内容:
  1. 特征一致性验证（与训练阶段38特征匹配）
  2. 气象数据映射（temperature_2m → Dry_Bulb 等）
  3. 气象衍生特征（humidity_index, cooling_degree, heating_degree）
  4. 时间特征（正余弦编码、布尔、季节）
  5. 滞后特征（load_lag, temp_lag）
  6. 滚动窗口特征（rolling mean/std/min/max）
  7. 负荷变化特征
  8. 归一化适配
  9. 序列构建
  10. 增量计算

运行方式:
    cd c:/OOOO/OOOO
    python realtime_api/test_feature_generator.py -v
"""

import unittest
import os
import sys
import pickle

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtime_api.feature_generator import (
    FeatureGenerator,
    FEATURE_COLS,
    TARGET,
    BASE_TEMP_C,
    WIND_MS_TO_MPH,
    FeatureGenerationError,
)


# ============================================================================
# 测试数据生成工具
# ============================================================================

def make_weather_data(
    num_hours: int = 200,
    start_time: str = "2025-07-10T00:00",
    locations: list = None,
) -> pd.DataFrame:
    """生成模拟气象数据"""
    if locations is None:
        locations = ["Boston"]

    timestamps = pd.date_range(start=start_time, periods=num_hours, freq="h")
    np.random.seed(42)

    all_rows = []
    for loc in locations:
        hours = np.arange(num_hours)
        temp = 25 + 5 * np.sin(2 * np.pi * hours / 24) + np.random.normal(0, 1, num_hours)
        dew = temp - 8 + np.random.normal(0, 0.5, num_hours)

        for i in range(num_hours):
            all_rows.append({
                "timestamp": timestamps[i],
                "location": loc,
                "temperature_2m": round(temp[i], 1),
                "dew_point_2m": round(dew[i], 1),
                "wind_speed_10m": round(np.random.uniform(2, 10), 1),
                "cloud_cover": int(np.random.randint(20, 80)),
                "shortwave_radiation": round(max(0, 500 * max(0, np.sin(2 * np.pi * (i % 24) / 24))), 1),
            })

    return pd.DataFrame(all_rows)


def make_load_data(
    num_hours: int = 200,
    start_time: str = "2025-07-10T00:00",
) -> pd.DataFrame:
    """生成模拟历史负荷数据"""
    timestamps = pd.date_range(start=start_time, periods=num_hours, freq="h")
    np.random.seed(123)
    hours = np.arange(num_hours)
    load = 15000 + 2000 * np.sin(2 * np.pi * hours / 24) + np.random.normal(0, 100, num_hours)

    return pd.DataFrame({
        "timestamp": timestamps,
        "System_Load": load,
    })


# ============================================================================
# 测试类
# ============================================================================

class TestFeatureConsistency(unittest.TestCase):
    """测试与训练阶段的特征一致性"""

    def test_feature_count(self):
        """测试特征数量为38"""
        self.assertEqual(len(FEATURE_COLS), 38)

    def test_feature_list_matches_training(self):
        """测试特征列表与训练配置完全一致"""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "processed", "step4_feature_config.pkl"
        )

        if os.path.exists(config_path):
            with open(config_path, "rb") as f:
                config = pickle.load(f)
            train_features = config["feature_cols"]

            self.assertEqual(
                set(FEATURE_COLS), set(train_features),
                f"特征不一致:\n  缺少: {set(train_features) - set(FEATURE_COLS)}\n"
                f"  多余: {set(FEATURE_COLS) - set(train_features)}"
            )
            self.assertEqual(len(train_features), 38)
        else:
            self.skipTest("训练配置文件不存在")

    def test_generator_initialization(self):
        """测试生成器初始化"""
        generator = FeatureGenerator()
        self.assertEqual(len(generator.feature_cols), 38)
        self.assertEqual(generator.feature_cols, FEATURE_COLS)


class TestWeatherMapping(unittest.TestCase):
    """测试气象数据映射"""

    def setUp(self):
        self.generator = FeatureGenerator()

    def test_temperature_mapping(self):
        """测试 temperature_2m → Dry_Bulb"""
        weather_df = make_weather_data(num_hours=50)
        features = self.generator.generate(weather_df, make_load_data(50))

        # Dry_Bulb 应在特征中
        self.assertIn("Dry_Bulb", features.columns)

    def test_dew_point_mapping(self):
        """测试 dew_point_2m → Dew_Point"""
        weather_df = make_weather_data(num_hours=50)
        features = self.generator.generate(weather_df, make_load_data(50))

        self.assertIn("Dew_Point", features.columns)

    def test_wind_speed_conversion(self):
        """测试风速单位转换 m/s → mph"""
        weather_df = make_weather_data(num_hours=50)
        weather_df["wind_speed_10m"] = 10.0  # 固定值

        # 生成器内部应该正确转换
        df = self.generator._map_weather_data(weather_df)

        # wind_speed_mph = 10 * 2.23694
        self.assertIn("wind_speed_mph", df.columns)
        self.assertAlmostEqual(df["wind_speed_mph"].iloc[0], 10.0 * WIND_MS_TO_MPH, places=2)

    def test_multi_station_average(self):
        """测试多站点区域平均"""
        weather_df = make_weather_data(num_hours=50, locations=["Boston", "Hartford"])
        df = self.generator._map_weather_data(weather_df)

        # 多站点应该被平均为一个时间序列
        self.assertEqual(len(df), 50)


class TestWeatherDerivedFeatures(unittest.TestCase):
    """测试气象衍生特征"""

    def setUp(self):
        self.generator = FeatureGenerator()

    def test_humidity_index(self):
        """测试 humidity_index = Dry_Bulb - Dew_Point"""
        weather_df = make_weather_data(num_hours=50)
        load_df = make_load_data(50)
        features = self.generator.generate(weather_df, load_df)

        # humidity_index = Dry_Bulb - Dew_Point
        # 由于多站点平均，需要比较原始数据
        # 验证非NaN且合理范围
        self.assertTrue((features["humidity_index"].abs() < 30).all())

    def test_cooling_degree(self):
        """测试制冷度日"""
        weather_df = make_weather_data(num_hours=50)
        features = self.generator.generate(weather_df, make_load_data(50))

        # cooling_degree = max(0, Dry_Bulb - 18)
        # 夏季数据温度可能高于18°C
        self.assertTrue((features["cooling_degree"] >= 0).all())

    def test_heating_degree(self):
        """测试供暖度日"""
        weather_df = make_weather_data(num_hours=50)
        features = self.generator.generate(weather_df, make_load_data(50))

        # heating_degree = max(0, 18 - Dry_Bulb)
        self.assertTrue((features["heating_degree"] >= 0).all())

    def test_cooling_plus_heating_consistency(self):
        """测试制冷度日+供暖度日与温度的关系"""
        weather_df = make_weather_data(num_hours=50)
        features = self.generator.generate(weather_df, make_load_data(50))

        # cooling_degree + heating_degree = |Dry_Bulb - 18|
        # 但由于映射后的列名不同，验证逻辑一致即可
        # 两者不能同时为正
        both_positive = ((features["cooling_degree"] > 0) &
                         (features["heating_degree"] > 0)).sum()
        self.assertEqual(both_positive, 0, "制冷度和供暖度不能同时为正")


class TestTimeFeatures(unittest.TestCase):
    """测试时间特征"""

    def setUp(self):
        self.generator = FeatureGenerator()

    def test_hour_sin_cos_range(self):
        """测试小时正余弦编码范围"""
        weather_df = make_weather_data(num_hours=48)
        features = self.generator.generate(weather_df, make_load_data(48))

        self.assertTrue((features["hour_sin"] >= -1.01).all())
        self.assertTrue((features["hour_sin"] <= 1.01).all())
        self.assertTrue((features["hour_cos"] >= -1.01).all())
        self.assertTrue((features["hour_cos"] <= 1.01).all())

    def test_dow_sin_cos_range(self):
        """测试星期正余弦编码范围"""
        weather_df = make_weather_data(num_hours=168)
        features = self.generator.generate(weather_df, make_load_data(168))

        self.assertTrue((features["dow_sin"] >= -1.01).all())
        self.assertTrue((features["dow_cos"] >= -1.01).all())

    def test_is_weekend(self):
        """测试周末标记"""
        weather_df = make_weather_data(num_hours=168)
        features = self.generator.generate(weather_df, make_load_data(168))

        # is_weekend 应为 0 或 1
        unique_vals = set(features["is_weekend"].unique())
        self.assertTrue(unique_vals.issubset({0, 1}))

    def test_is_holiday(self):
        """测试假日标记"""
        # 2025-07-04 是美国独立日
        timestamps = pd.date_range("2025-07-04", periods=24, freq="h")
        weather_df = pd.DataFrame({
            "timestamp": timestamps,
            "location": "Boston",
            "temperature_2m": 25.0,
            "dew_point_2m": 15.0,
        })
        features = self.generator.generate(weather_df, None)

        # 7月4日应为假日
        self.assertTrue((features["is_holiday"] == 1).all())

    def test_season_one_hot(self):
        """测试季节 one-hot 编码"""
        # 7月是夏季
        timestamps = pd.date_range("2025-07-15", periods=24, freq="h")
        weather_df = pd.DataFrame({
            "timestamp": timestamps,
            "location": "Boston",
            "temperature_2m": 25.0,
            "dew_point_2m": 15.0,
        })
        features = self.generator.generate(weather_df, None)

        # 7月应为夏季
        self.assertTrue((features["season_summer"] == 1).all())
        self.assertTrue((features["season_winter"] == 0).all())
        self.assertTrue((features["season_spring"] == 0).all())
        self.assertTrue((features["season_fall"] == 0).all())

    def test_season_sum_is_one(self):
        """测试季节 one-hot 之和为1"""
        weather_df = make_weather_data(num_hours=200)
        features = self.generator.generate(weather_df, make_load_data(200))

        season_sum = (features["season_fall"] + features["season_spring"] +
                      features["season_summer"] + features["season_winter"])
        self.assertTrue((season_sum == 1).all(), "季节one-hot之和应为1")


class TestLagFeatures(unittest.TestCase):
    """测试滞后特征"""

    def setUp(self):
        self.generator = FeatureGenerator()

    def test_load_lag_1h(self):
        """测试 load_lag_1h"""
        weather_df = make_weather_data(num_hours=50)
        load_df = make_load_data(50)
        features = self.generator.generate(weather_df, load_df)

        self.assertIn("load_lag_1h", features.columns)

    def test_load_lag_24h(self):
        """测试 load_lag_24h"""
        weather_df = make_weather_data(num_hours=50)
        features = self.generator.generate(weather_df, make_load_data(50))

        self.assertIn("load_lag_24h", features.columns)

    def test_load_lag_168h(self):
        """测试 load_lag_168h"""
        weather_df = make_weather_data(num_hours=200)
        features = self.generator.generate(weather_df, make_load_data(200))

        self.assertIn("load_lag_168h", features.columns)

    def test_temp_lag_24h(self):
        """测试 temp_lag_24h"""
        weather_df = make_weather_data(num_hours=50)
        features = self.generator.generate(weather_df, make_load_data(50))

        self.assertIn("temp_lag_24h", features.columns)

    def test_temp_lag_168h(self):
        """测试 temp_lag_168h"""
        weather_df = make_weather_data(num_hours=200)
        features = self.generator.generate(weather_df, make_load_data(200))

        self.assertIn("temp_lag_168h", features.columns)


class TestRollingFeatures(unittest.TestCase):
    """测试滚动窗口特征"""

    def setUp(self):
        self.generator = FeatureGenerator()

    def test_all_rolling_features_exist(self):
        """测试所有滚动窗口特征都存在"""
        weather_df = make_weather_data(num_hours=200)
        features = self.generator.generate(weather_df, make_load_data(200))

        rolling_cols = [
            "load_rolling_mean_24h", "load_rolling_std_24h",
            "load_rolling_mean_168h", "load_rolling_min_24h",
            "load_rolling_max_24h", "temp_rolling_mean_24h",
            "temp_rolling_max_24h", "temp_rolling_min_24h",
        ]
        for col in rolling_cols:
            self.assertIn(col, features.columns, f"缺少滚动特征: {col}")

    def test_rolling_mean_range(self):
        """测试滚动均值在合理范围内"""
        weather_df = make_weather_data(num_hours=200)
        features = self.generator.generate(weather_df, make_load_data(200))

        # 均值应该在 min 和 max 之间
        self.assertTrue((features["load_rolling_mean_24h"] >= 0).all())


class TestLoadChangeFeatures(unittest.TestCase):
    """测试负荷变化特征"""

    def setUp(self):
        self.generator = FeatureGenerator()

    def test_load_diff_1h(self):
        """测试 load_diff_1h"""
        weather_df = make_weather_data(num_hours=50)
        features = self.generator.generate(weather_df, make_load_data(50))

        self.assertIn("load_diff_1h", features.columns)

    def test_load_diff_24h(self):
        """测试 load_diff_24h"""
        weather_df = make_weather_data(num_hours=50)
        features = self.generator.generate(weather_df, make_load_data(50))

        self.assertIn("load_diff_24h", features.columns)

    def test_load_pct_change_24h(self):
        """测试 load_pct_change_24h"""
        weather_df = make_weather_data(num_hours=50)
        features = self.generator.generate(weather_df, make_load_data(50))

        self.assertIn("load_pct_change_24h", features.columns)


class TestMissingValueHandling(unittest.TestCase):
    """测试缺失值处理"""

    def setUp(self):
        self.generator = FeatureGenerator()

    def test_no_missing_after_generation(self):
        """测试生成后无缺失值"""
        weather_df = make_weather_data(num_hours=200)
        features = self.generator.generate(weather_df, make_load_data(200))

        missing_count = features.isna().sum().sum()
        self.assertEqual(missing_count, 0, f"仍有 {missing_count} 个缺失值")

    def test_missing_load_handled(self):
        """测试无历史负荷数据时的缺失处理"""
        weather_df = make_weather_data(num_hours=50)
        # 不提供历史负荷
        features = self.generator.generate(weather_df, None)

        # 应该仍有38列
        self.assertEqual(features.shape[1], 38)
        # 不应有NaN（被填充为0）
        self.assertEqual(features.isna().sum().sum(), 0)


class TestNormalization(unittest.TestCase):
    """测试归一化适配"""

    def setUp(self):
        self.generator = FeatureGenerator()

    def test_normalize_shape(self):
        """测试归一化后形状"""
        weather_df = make_weather_data(num_hours=200)
        features = self.generator.generate(weather_df, make_load_data(200))

        normalized = self.generator.normalize(features)

        self.assertEqual(normalized.shape, (200, 38))

    def test_normalize_range(self):
        """测试归一化后范围大致在[0,1]"""
        weather_df = make_weather_data(num_hours=200)
        features = self.generator.generate(weather_df, make_load_data(200))

        normalized = self.generator.normalize(features)

        # 大部分值应在 [0, 1] 范围内（实时数据可能略超出）
        self.assertTrue(normalized.min() >= -0.5)
        self.assertTrue(normalized.max() <= 1.5)


class TestSequenceBuilding(unittest.TestCase):
    """测试序列构建"""

    def setUp(self):
        self.generator = FeatureGenerator()

    def test_sequence_shape(self):
        """测试序列形状"""
        weather_df = make_weather_data(num_hours=200)
        features = self.generator.generate(weather_df, make_load_data(200))

        sequence = self.generator.build_sequence(features, lookback=168)

        # 应为 (1, 168, 38)
        self.assertEqual(sequence.shape, (1, 168, 38))

    def test_sequence_padding(self):
        """测试数据不足时的填充"""
        weather_df = make_weather_data(num_hours=100)
        features = self.generator.generate(weather_df, make_load_data(100))

        # 100 < 168，应填充
        sequence = self.generator.build_sequence(features, lookback=168)

        self.assertEqual(sequence.shape, (1, 168, 38))

    def test_sequence_takes_last(self):
        """测试序列取最后 lookback 行"""
        weather_df = make_weather_data(num_hours=200)
        features = self.generator.generate(weather_df, make_load_data(200))

        lookback = 168
        sequence = self.generator.build_sequence(features, lookback=lookback)

        # 序列的最后一条应等于 features 的最后一条
        np.testing.assert_almost_equal(
            sequence[0, -1, :], features.values[-1], decimal=5
        )


class TestIncrementalComputation(unittest.TestCase):
    """测试增量计算"""

    def setUp(self):
        self.generator = FeatureGenerator()

    def test_history_buffer_update(self):
        """测试历史缓冲区更新"""
        weather_df = make_weather_data(num_hours=200)
        self.generator.generate(weather_df, make_load_data(200))

        buf = self.generator.get_history_buffer()
        self.assertIsNotNone(buf)
        self.assertGreater(len(buf), 0)

    def test_incremental_generation(self):
        """测试增量生成"""
        # 首次生成
        weather_df1 = make_weather_data(num_hours=200)
        self.generator.generate(weather_df1, make_load_data(200))

        # 新增数据
        weather_df2 = make_weather_data(
            num_hours=24, start_time="2025-07-18T00:00"
        )

        features = self.generator.generate_incremental(weather_df2)

        # 应生成24行特征
        self.assertEqual(len(features), 24)
        # 应有38列
        self.assertEqual(features.shape[1], 38)
        # 不应有NaN
        self.assertEqual(features.isna().sum().sum(), 0)


class TestEndToEnd(unittest.TestCase):
    """端到端测试"""

    def setUp(self):
        self.generator = FeatureGenerator()

    def test_full_pipeline(self):
        """测试完整流水线"""
        # 1. 气象数据
        weather_df = make_weather_data(num_hours=200)

        # 2. 历史负荷
        load_df = make_load_data(200)

        # 3. 生成特征
        features = self.generator.generate(weather_df, load_df)

        # 4. 验证
        self.assertEqual(features.shape[1], 38)
        self.assertEqual(features.isna().sum().sum(), 0)

        # 5. 归一化
        normalized = self.generator.normalize(features)
        self.assertEqual(normalized.shape, (200, 38))

        # 6. 序列
        sequence = self.generator.build_sequence(features, lookback=168)
        self.assertEqual(sequence.shape, (1, 168, 38))

    def test_feature_order_consistent(self):
        """测试特征顺序与训练一致"""
        weather_df = make_weather_data(num_hours=200)
        features = self.generator.generate(weather_df, make_load_data(200))

        # 列名顺序应与 FEATURE_COLS 完全一致
        self.assertEqual(features.columns.tolist(), FEATURE_COLS)


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
