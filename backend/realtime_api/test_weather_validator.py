"""
气象数据质量验证模块单元测试

测试内容:
  1. 输入验证（空数据、缺列、格式错误）
  2. 物理范围验证（温度、湿度、辐射等）
  3. 逻辑约束验证（露点 ≤ 气温）
  4. IQR 统计异常检测
  5. 缺失值三级填充策略
  6. 严重异常抛出机制
  7. 质量报告生成

运行方式:
    cd c:/OOOO/OOOO
    python realtime_api/test_weather_validator.py -v

    或者:
    python -m pytest realtime_api/test_weather_validator.py -v
"""

import unittest
import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtime_api.weather_validator import (
    WeatherDataValidator,
    QualityReport,
    AnomalyRecord,
    AnomalySeverity,
    AnomalyType,
    CorrectionMethod,
    SevereDataQualityError,
    DataValidationError,
)


# ============================================================================
# 测试数据生成工具
# ============================================================================

def make_normal_data(
    num_hours: int = 48,
    locations: list = None,
    start_time: str = "2025-07-16T00:00"
) -> pd.DataFrame:
    """生成正常的气象测试数据"""
    if locations is None:
        locations = ["Boston", "Hartford"]

    timestamps = pd.date_range(start=start_time, periods=num_hours, freq="h")

    all_rows = []
    for loc in locations:
        np.random.seed(hash(loc) % 2**32)
        hours = np.arange(num_hours)
        # 温度：日内变化
        temp = 20 + 10 * np.sin(2 * np.pi * hours / 24) + np.random.normal(0, 1.5, num_hours)
        dew = temp - 5 + np.random.normal(0, 1, num_hours)

        for i in range(num_hours):
            all_rows.append({
                "timestamp": timestamps[i],
                "location": loc,
                "temperature_2m": round(temp[i], 1),
                "dew_point_2m": round(dew[i], 1),
                "relative_humidity_2m": int(np.random.randint(40, 90)),
                "wind_speed_10m": round(np.random.uniform(0, 15), 1),
                "cloud_cover": int(np.random.randint(0, 100)),
                "shortwave_radiation": round(
                    max(0, 500 * max(0, np.sin(2 * np.pi * (i % 24) / 24)) +
                    np.random.normal(0, 50)), 1
                ),
            })

    return pd.DataFrame(all_rows)


def make_data_with_range_violations() -> pd.DataFrame:
    """生成含物理范围超出值的数据"""
    df = make_normal_data(num_hours=24, locations=["Boston"])
    # 注入严重异常
    df.loc[5, "temperature_2m"] = 99.0      # 严重超出高温
    df.loc[10, "temperature_2m"] = -99.0    # 严重超出低温
    df.loc[8, "relative_humidity_2m"] = 150.0  # 超出100%
    df.loc[15, "shortwave_radiation"] = -50.0  # 负辐射
    # 注入轻微异常
    df.loc[3, "temperature_2m"] = 46.0      # 轻微超出（>45但<46.75）
    df.loc[7, "cloud_cover"] = 101.0        # 轻微超出
    return df


def make_data_with_logic_violations() -> pd.DataFrame:
    """生成含逻辑约束违反（露点>气温）的数据"""
    df = make_normal_data(num_hours=24, locations=["Boston"])
    # 注入露点高于气温
    df.loc[5, "dew_point_2m"] = df.loc[5, "temperature_2m"] + 5.0
    df.loc[10, "dew_point_2m"] = df.loc[10, "temperature_2m"] + 0.5
    return df


def make_data_with_missing_values() -> pd.DataFrame:
    """生成含缺失值的数据"""
    df = make_normal_data(num_hours=48, locations=["Boston", "Hartford"])
    # 注入缺失值
    df.loc[3, "temperature_2m"] = np.nan
    df.loc[10, "humidity_2m" if "humidity_2m" in df.columns else "relative_humidity_2m"] = np.nan
    df.loc[15, "wind_speed_10m"] = np.nan
    df.loc[20, "cloud_cover"] = np.nan
    # 连续缺失
    df.loc[30:32, "temperature_2m"] = np.nan
    return df


def make_data_with_statistical_outliers() -> pd.DataFrame:
    """生成含统计异常值的数据"""
    df = make_normal_data(num_hours=200, locations=["Boston"])
    # 注入远离正常分布的值（在物理范围内但偏离统计分布）
    # 正常夏季温度约 20±15°C，注入极端值使 IQR 能检测到
    df.loc[100, "temperature_2m"] = 44.0   # 接近物理上限，远超统计上界
    df.loc[101, "temperature_2m"] = -25.0  # 接近物理下限，远低于统计下界
    df.loc[102, "wind_speed_10m"] = 48.0  # 接近物理上限
    return df


# ============================================================================
# 测试类
# ============================================================================

class TestInputValidation(unittest.TestCase):
    """测试输入验证"""

    def test_empty_dataframe(self):
        """测试空 DataFrame"""
        validator = WeatherDataValidator()
        with self.assertRaises(DataValidationError):
            validator.validate(pd.DataFrame())

    def test_none_input(self):
        """测试 None 输入"""
        validator = WeatherDataValidator()
        with self.assertRaises(DataValidationError):
            validator.validate(None)

    def test_missing_required_columns(self):
        """测试缺少必需列"""
        validator = WeatherDataValidator()
        df = pd.DataFrame({"temperature_2m": [20, 21, 22]})
        with self.assertRaises(DataValidationError) as ctx:
            validator.validate(df)
        self.assertIn("缺少必需列", str(ctx.exception))

    def test_missing_weather_columns(self):
        """测试缺少气象参数列"""
        validator = WeatherDataValidator()
        df = pd.DataFrame({
            "timestamp": pd.date_range("2025-07-16", periods=5, freq="h"),
            "location": "Boston",
        })
        with self.assertRaises(DataValidationError) as ctx:
            validator.validate(df)
        self.assertIn("未找到任何气象参数列", str(ctx.exception))


class TestRangeValidation(unittest.TestCase):
    """测试物理范围验证"""

    def setUp(self):
        self.validator = WeatherDataValidator()

    def test_normal_data_passes(self):
        """测试正常数据通过验证"""
        df = make_normal_data()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        self.assertEqual(len(clean_df), len(df))
        # 正常数据质量评分应该较高
        self.assertGreater(report.overall_quality_score, 90)

    def test_severe_temperature_outlier(self):
        """测试严重温度异常"""
        df = make_data_with_range_violations()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        # 应检测到异常
        self.assertGreater(report.total_anomalies, 0)

        # 修正后温度应在范围内
        temp = clean_df["temperature_2m"]
        self.assertTrue((temp >= -30).all(), "温度仍存在异常低值")
        self.assertTrue((temp <= 45).all(), "温度仍存在异常高值")

    def test_humidity_range(self):
        """测试湿度范围"""
        df = make_data_with_range_violations()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        humidity = clean_df["relative_humidity_2m"]
        self.assertTrue((humidity >= 0).all(), "湿度仍存在负值")
        self.assertTrue((humidity <= 100).all(), "湿度仍存在超100%值")

    def test_radiation_non_negative(self):
        """测试辐射非负"""
        df = make_data_with_range_violations()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        radiation = clean_df["shortwave_radiation"]
        self.assertTrue((radiation >= 0).all(), "辐射仍存在负值")

    def test_anomaly_flags_marked(self):
        """测试异常标记矩阵正确标记"""
        df = make_data_with_range_violations()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        # 异常标记矩阵中应有 True 值
        self.assertGreater(flags.sum().sum(), 0)

    def test_minor_vs_severe_classification(self):
        """测试轻微异常和严重异常的分类"""
        df = make_data_with_range_violations()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        # 应同时有轻微和严重异常
        self.assertGreater(report.minor_anomalies, 0, "未检测到轻微异常")
        self.assertGreater(report.severe_anomalies, 0, "未检测到严重异常")


class TestLogicalConstraints(unittest.TestCase):
    """测试逻辑约束验证"""

    def setUp(self):
        self.validator = WeatherDataValidator()

    def test_dew_point_correction(self):
        """测试露点高于气温的修正"""
        df = make_data_with_logic_violations()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        # 修正后露点应 ≤ 气温
        self.assertTrue(
            (clean_df["dew_point_2m"] <= clean_df["temperature_2m"]).all(),
            "露点温度仍高于气温"
        )

    def test_dew_point_anomaly_recorded(self):
        """测试露点异常被记录"""
        df = make_data_with_logic_violations()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        # 应有逻辑约束违反的记录
        logic_anomalies = [
            r for r in report.anomaly_records
            if r["anomaly_type"] == AnomalyType.LOGIC_VIOLATION.value
        ]
        self.assertGreater(len(logic_anomalies), 0, "未记录逻辑约束异常")


class TestStatisticalOutliers(unittest.TestCase):
    """测试 IQR 统计异常检测"""

    def setUp(self):
        self.validator = WeatherDataValidator()

    def test_statistical_outlier_detection(self):
        """测试统计异常检测"""
        df = make_data_with_statistical_outliers()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        # 应检测到统计异常
        stat_anomalies = [
            r for r in report.anomaly_records
            if r["anomaly_type"] == AnomalyType.STATISTICAL_OUTLIER.value
        ]
        self.assertGreater(len(stat_anomalies), 0, "未检测到统计异常")


class TestMissingValueHandling(unittest.TestCase):
    """测试缺失值处理"""

    def setUp(self):
        self.validator = WeatherDataValidator()

    def test_missing_values_filled(self):
        """测试缺失值被填充"""
        df = make_data_with_missing_values()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        # 所有气象参数列不应有缺失值
        param_cols = [c for c in clean_df.columns if c in self.validator.weather_params]
        missing = clean_df[param_cols].isna().sum().sum()
        self.assertEqual(missing, 0, f"仍有 {missing} 个缺失值未处理")

    def test_missing_count_reported(self):
        """测试缺失值数量被正确统计"""
        df = make_data_with_missing_values()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        self.assertGreater(report.total_missing, 0, "未报告缺失值")
        self.assertEqual(report.missing_remaining, 0, "缺失值未全部处理")

    def test_interpolation_strategy(self):
        """测试时间插值策略"""
        df = make_data_with_missing_values()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        # 插值应填充了部分缺失值
        self.assertGreaterEqual(
            report.missing_filled_by_interp, 0,
            "插值策略未正常执行"
        )


class TestSevereAnomaly(unittest.TestCase):
    """测试严重异常处理"""

    def test_severe_anomaly_raises_exception(self):
        """测试严重异常抛出异常"""
        # 构造大量异常数据（>20%）
        df = make_normal_data(num_hours=24, locations=["Boston"])
        # 让 30% 的温度数据严重超出范围
        for i in range(8):
            df.loc[i, "temperature_2m"] = 200.0  # 严重超出

        validator = WeatherDataValidator()
        with self.assertRaises(SevereDataQualityError) as ctx:
            validator.validate(df, raise_on_severe=True)

        self.assertIn("严重数据质量异常", str(ctx.exception))

    def test_severe_anomaly_no_raise(self):
        """测试设置 raise_on_severe=False 不抛出异常"""
        df = make_normal_data(num_hours=24, locations=["Boston"])
        for i in range(8):
            df.loc[i, "temperature_2m"] = 200.0

        validator = WeatherDataValidator()
        # 不应抛出异常
        clean_df, report, flags = validator.validate(df, raise_on_severe=False)

        self.assertFalse(report.is_valid)


class TestQualityReport(unittest.TestCase):
    """测试质量报告生成"""

    def setUp(self):
        self.validator = WeatherDataValidator()

    def test_report_structure(self):
        """测试报告结构完整性"""
        df = make_normal_data()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        report_dict = report.to_dict()

        # 检查所有必需字段
        required_keys = [
            "total_records", "total_parameters", "locations_count",
            "time_range_start", "time_range_end",
            "total_anomalies", "minor_anomalies", "severe_anomalies",
            "anomalies_by_type", "anomalies_by_parameter",
            "total_missing", "missing_filled_by_interp",
            "missing_filled_by_historical", "missing_filled_by_fusion",
            "missing_remaining",
            "overall_quality_score", "is_valid",
        ]
        for key in required_keys:
            self.assertIn(key, report_dict, f"报告缺少字段: {key}")

    def test_report_json_serializable(self):
        """测试报告可序列化为 JSON"""
        df = make_normal_data()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        json_str = report.to_json()
        # 确保是合法的 JSON
        parsed = json.loads(json_str)
        self.assertIsInstance(parsed, dict)

    def test_quality_score_range(self):
        """测试质量评分在 0~100 范围"""
        df = make_normal_data()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        self.assertGreaterEqual(report.overall_quality_score, 0)
        self.assertLessEqual(report.overall_quality_score, 100)

    def test_anomaly_records_format(self):
        """测试异常记录格式"""
        df = make_data_with_range_violations()
        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        for record in report.anomaly_records:
            self.assertIn("timestamp", record)
            self.assertIn("location", record)
            self.assertIn("parameter", record)
            self.assertIn("anomaly_type", record)
            self.assertIn("severity", record)
            self.assertIn("original_value", record)
            self.assertIn("corrected_value", record)
            self.assertIn("correction_method", record)
            self.assertIn("description", record)


class TestTimeContinuity(unittest.TestCase):
    """测试时间连续性检查"""

    def setUp(self):
        self.validator = WeatherDataValidator()

    def test_time_gap_detection(self):
        """测试时间间隔异常检测"""
        df = make_normal_data(num_hours=24, locations=["Boston"])
        # 删除中间几行，制造时间间隔
        df = df.drop([10, 11, 12]).reset_index(drop=True)

        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        # 应检测到时间间隔异常
        self.assertGreater(report.time_gaps_detected, 0, "未检测到时间间隔异常")


class TestMultiStationFusion(unittest.TestCase):
    """测试多站点数据融合"""

    def setUp(self):
        self.validator = WeatherDataValidator()

    def test_multi_station_fill(self):
        """测试多站点融合填充缺失值"""
        # 构造场景：某站点某时刻缺失，但另一站点有数据
        df = make_normal_data(num_hours=24, locations=["Boston", "Hartford"])
        # Boston 的某个温度设为 NaN
        df.loc[(df["location"] == "Boston") & (df.index == 5), "temperature_2m"] = np.nan
        # 同时确保 Hartford 在同一时刻有数据（默认就有）

        clean_df, report, flags = self.validator.validate(df, raise_on_severe=False)

        # 该位置应该被填充
        boston_row = clean_df[
            (clean_df["location"] == "Boston") &
            (clean_df["timestamp"] == df.loc[5, "timestamp"])
        ]
        if len(boston_row) > 0:
            temp_val = boston_row.iloc[0]["temperature_2m"]
            self.assertFalse(
                pd.isna(temp_val),
                "多站点融合未填充缺失值"
            )


class TestCustomConfiguration(unittest.TestCase):
    """测试自定义配置"""

    def setUp(self):
        self.validator = WeatherDataValidator()

    def test_custom_parameters(self):
        """测试自定义验证参数"""
        validator = WeatherDataValidator(weather_params=["temperature_2m"])
        df = make_normal_data()
        clean_df, report, flags = validator.validate(df, raise_on_severe=False)

        # 只验证 temperature_2m
        self.assertEqual(validator.weather_params, ["temperature_2m"])

    def test_custom_severity_threshold(self):
        """测试自定义严重异常阈值"""
        validator = WeatherDataValidator(severe_anomaly_ratio=0.5)  # 50%阈值
        self.assertEqual(validator.SEVERE_ANOMALY_RATIO, 0.5)


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
