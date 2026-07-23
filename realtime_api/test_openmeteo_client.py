"""
Open-Meteo API 客户端单元测试

测试内容:
  1. 客户端初始化和配置
  2. API 响应解析
  3. 数据验证和清洗逻辑
  4. 请求频率限制
  5. 错误处理和重试机制
  6. 区域平均计算

运行方式:
    cd c:/OOOO/OOOO
    python -m pytest realtime_api/test_openmeteo_client.py -v

    或者直接运行:
    python realtime_api/test_openmeteo_client.py
"""

import unittest
from unittest.mock import patch, MagicMock, Mock
from datetime import datetime, timedelta
import time
import json

import numpy as np
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtime_api.openmeteo_client import (
    OpenMeteoClient,
    WeatherLocation,
    DataQualityReport,
)


# ============================================================================
# 测试用的 Mock 数据
# ============================================================================

def create_mock_api_response(
    num_hours: int = 192,
    start_time: str = "2025-07-16T00:00"
) -> dict:
    """
    创建模拟的 Open-Meteo API 响应数据

    Args:
        num_hours: 小时数 (默认 192 = 8天 × 24小时)
        start_time: 起始时间

    Returns:
        dict: 模拟的 API JSON 响应
    """
    timestamps = pd.date_range(
        start=start_time, periods=num_hours, freq="h"
    ).strftime("%Y-%m-%dT%H:%M").tolist()

    # 生成合理的气象数据
    np.random.seed(42)
    hours = np.arange(num_hours)
    # 温度：日内变化 + 日间变化
    base_temp = 20 + 10 * np.sin(2 * np.pi * hours / 24) + 5 * np.sin(2 * np.pi * hours / (24 * 7))
    temperature = base_temp + np.random.normal(0, 1.5, num_hours)

    return {
        "latitude": 42.36,
        "longitude": -71.06,
        "timezone": "America/New_York",
        "hourly": {
            "time": timestamps,
            "temperature_2m": temperature.round(1).tolist(),
            "dew_point_2m": (temperature - 5 + np.random.normal(0, 1, num_hours)).round(1).tolist(),
            "relative_humidity_2m": np.random.randint(40, 90, num_hours).tolist(),
            "wind_speed_10m": np.random.uniform(0, 15, num_hours).round(1).tolist(),
            "cloud_cover": np.random.randint(0, 100, num_hours).tolist(),
            "shortwave_radiation": np.maximum(
                0, 500 * np.maximum(0, np.sin(2 * np.pi * (hours % 24) / 24)) +
                np.random.normal(0, 50, num_hours)
            ).round(1).tolist(),
        }
    }


def create_mock_api_response_with_issues() -> dict:
    """创建带异常值的模拟 API 响应（用于测试数据清洗）"""
    response = create_mock_api_response(num_hours=48)
    hourly = response["hourly"]

    # 注入异常值
    # 1. 温度异常值 (超出 -40~50 范围)
    hourly["temperature_2m"][5] = 99.0    # 异常高温
    hourly["temperature_2m"][10] = -99.0  # 异常低温

    # 2. 湿度异常值 (超出 0~100 范围)
    hourly["relative_humidity_2m"][15] = 150.0  # 超出100%

    # 3. 露点高于气温
    hourly["dew_point_2m"][20] = hourly["temperature_2m"][20] + 5.0

    # 4. 辐射负值
    hourly["shortwave_radiation"][30] = -100.0

    # 5. 缺失值 (设为 None)
    hourly["wind_speed_10m"][3] = None
    hourly["cloud_cover"][7] = None

    return response


# ============================================================================
# 测试类
# ============================================================================

class TestWeatherLocation(unittest.TestCase):
    """测试 WeatherLocation 数据类"""

    def test_creation(self):
        """测试创建站点对象"""
        loc = WeatherLocation(name="Boston", lat=42.3601, lon=-71.0589)
        self.assertEqual(loc.name, "Boston")
        self.assertEqual(loc.lat, 42.3601)
        self.assertEqual(loc.lon, -71.0589)

    def test_repr(self):
        """测试字符串表示"""
        loc = WeatherLocation(name="Boston", lat=42.36, lon=-71.06)
        repr_str = repr(loc)
        self.assertIn("Boston", repr_str)
        self.assertIn("42.36", repr_str)


class TestOpenMeteoClientInit(unittest.TestCase):
    """测试 OpenMeteoClient 初始化"""

    def test_default_init(self):
        """测试默认初始化"""
        client = OpenMeteoClient()
        self.assertEqual(len(client.locations), 6)
        self.assertEqual(client.locations[0].name, "Boston")
        self.assertEqual(client.past_days, 7)
        self.assertEqual(client.forecast_days, 1)
        self.assertEqual(client.timezone_str, "America/New_York")

    def test_custom_locations(self):
        """测试自定义站点"""
        custom = [
            {"name": "TestCity", "lat": 40.0, "lon": -75.0},
            WeatherLocation(name="TestCity2", lat=41.0, lon=-72.0),
        ]
        client = OpenMeteoClient(locations=custom)
        self.assertEqual(len(client.locations), 2)
        self.assertEqual(client.locations[0].name, "TestCity")
        self.assertEqual(client.locations[1].name, "TestCity2")

    def test_custom_params(self):
        """测试自定义参数"""
        client = OpenMeteoClient(
            past_days=3,
            forecast_days=2,
            timezone_str="UTC",
            rate_limit_interval=0.1,
            max_retries=5,
            request_timeout=10,
        )
        self.assertEqual(client.past_days, 3)
        self.assertEqual(client.forecast_days, 2)
        self.assertEqual(client.timezone_str, "UTC")
        self.assertEqual(client.rate_limit_interval, 0.1)
        self.assertEqual(client.max_retries, 5)
        self.assertEqual(client.request_timeout, 10)

    def test_session_created(self):
        """测试 Session 创建"""
        client = OpenMeteoClient()
        self.assertIsNotNone(client.session)


class TestRateLimit(unittest.TestCase):
    """测试请求频率限制"""

    def test_rate_limit_enforced(self):
        """测试频率限制实际生效"""
        client = OpenMeteoClient(rate_limit_interval=0.3)

        # 第一次请求
        client._enforce_rate_limit()
        t1 = time.time()

        # 第二次请求（应等待）
        client._enforce_rate_limit()
        t2 = time.time()

        elapsed = t2 - t1
        self.assertGreaterEqual(elapsed, 0.25, "频率限制未生效")


class TestResponseParsing(unittest.TestCase):
    """测试 API 响应解析"""

    def setUp(self):
        self.client = OpenMeteoClient()

    def test_parse_normal_response(self):
        """测试正常响应解析"""
        mock_response = create_mock_api_response(num_hours=48)
        location = WeatherLocation(name="Boston", lat=42.36, lon=-71.06)

        df, report = self.client._parse_response(mock_response, location)

        self.assertIsNotNone(df)
        self.assertEqual(len(df), 48)
        self.assertIn("timestamp", df.columns)
        self.assertIn("location", df.columns)
        self.assertIn("temperature_2m", df.columns)
        self.assertIn("dew_point_2m", df.columns)
        self.assertEqual(report.total_records, 48)
        self.assertTrue(report.is_valid)

    def test_parse_empty_response(self):
        """测试空响应解析"""
        mock_response = {"hourly": {}}
        location = WeatherLocation(name="Test", lat=40.0, lon=-70.0)

        df, report = self.client._parse_response(mock_response, location)

        self.assertIsNone(df)
        self.assertFalse(report.is_valid)

    def test_parse_no_hourly_key(self):
        """测试缺少 hourly 字段"""
        mock_response = {"latitude": 42.36, "longitude": -71.06}
        location = WeatherLocation(name="Test", lat=40.0, lon=-70.0)

        df, report = self.client._parse_response(mock_response, location)

        self.assertIsNone(df)
        self.assertFalse(report.is_valid)
        self.assertIn("响应中没有 hourly 字段", report.issues)

    def test_parse_mismatched_lengths(self):
        """测试参数长度不匹配"""
        mock_response = {
            "hourly": {
                "time": ["2025-07-16T00:00", "2025-07-16T01:00", "2025-07-16T02:00"],
                "temperature_2m": [20.0, 21.0],  # 少一个
                "dew_point_2m": [15.0, 16.0, 17.0],
            }
        }
        location = WeatherLocation(name="Test", lat=40.0, lon=-70.0)

        df, report = self.client._parse_response(mock_response, location)

        self.assertIsNotNone(df)
        self.assertEqual(len(df), 3)
        # 缺失的值应该被补齐为 None
        self.assertTrue(pd.isna(df["temperature_2m"].iloc[2]))


class TestDataValidation(unittest.TestCase):
    """测试数据验证和清洗"""

    def setUp(self):
        self.client = OpenMeteoClient()

    def test_outlier_detection_and_correction(self):
        """测试异常值检测和修正"""
        mock_response = create_mock_api_response_with_issues()
        location = WeatherLocation(name="Test", lat=40.0, lon=-70.0)

        # 解析
        df, report = self.client._parse_response(mock_response, location)

        # 验证和清洗
        df, report = self._clean(df, report)

        # 检查异常值被修正（不再是原始异常值）
        self.assertGreater(report.outliers_detected, 0)
        self.assertGreater(report.outliers_corrected, 0)

        # 检查温度范围
        temp_col = df["temperature_2m"]
        self.assertTrue((temp_col >= -40).all(), "温度仍存在异常低值")
        self.assertTrue((temp_col <= 50).all(), "温度仍存在异常高值")

        # 检查湿度范围
        humidity_col = df["relative_humidity_2m"]
        self.assertTrue((humidity_col >= 0).all(), "湿度仍存在负值")
        self.assertTrue((humidity_col <= 100).all(), "湿度仍存在超100%值")

        # 检查辐射非负
        radiation_col = df["shortwave_radiation"]
        self.assertTrue((radiation_col >= 0).all(), "辐射仍存在负值")

    def _clean(self, df, report):
        """辅助方法：调用验证清洗"""
        return self.client._validate_and_clean(df, report)

    def test_dew_point_constraint(self):
        """测试露点温度约束（露点不应高于气温）"""
        # 构造露点高于气温的数据
        mock_response = create_mock_api_response(num_hours=24)
        # 让第 10 个时间点的露点高于气温
        mock_response["hourly"]["dew_point_2m"][10] = \
            mock_response["hourly"]["temperature_2m"][10] + 10.0

        location = WeatherLocation(name="Test", lat=40.0, lon=-70.0)
        df, report = self.client._parse_response(mock_response, location)
        df, report = self.client._validate_and_clean(df, report)

        # 验证露点被修正
        self.assertTrue(
            (df["dew_point_2m"] <= df["temperature_2m"]).all(),
            "露点温度仍高于气温"
        )

    def test_missing_value_interpolation(self):
        """测试缺失值插值"""
        mock_response = create_mock_api_response_with_issues()
        location = WeatherLocation(name="Test", lat=40.0, lon=-70.0)

        df, report = self.client._parse_response(mock_response, location)
        df, report = self.client._validate_and_clean(df, report)

        # 插值后不应有缺失值
        param_cols = [c for c in df.columns if c in self.client.weather_params]
        missing_count = df[param_cols].isna().sum().sum()
        self.assertEqual(missing_count, 0, f"仍有 {missing_count} 个缺失值未处理")

    def test_quality_report_generation(self):
        """测试质量报告生成"""
        mock_response = create_mock_api_response(num_hours=48)
        location = WeatherLocation(name="Test", lat=40.0, lon=-70.0)

        df, report = self.client._parse_response(mock_response, location)
        df, report = self.client._validate_and_clean(df, report)

        report_dict = report.to_dict()
        self.assertIn("location", report_dict)
        self.assertIn("total_records", report_dict)
        self.assertEqual(report_dict["total_records"], 48)
        self.assertTrue(report_dict["is_valid"])


class TestFetchWithMock(unittest.TestCase):
    """使用 Mock 测试 API 请求"""

    @patch('realtime_api.openmeteo_client.requests.Session.get')
    def test_fetch_weather_data_success(self, mock_get):
        """测试成功获取数据"""
        # 设置 Mock 响应
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = create_mock_api_response(num_hours=48)
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # 执行
        client = OpenMeteoClient(rate_limit_interval=0.01)
        df, reports = client.fetch_weather_data()

        # 验证
        self.assertGreater(len(df), 0)
        self.assertIn("temperature_2m", df.columns)
        self.assertEqual(len(reports), 6)  # 6 个站点

        # 验证每个站点都有数据
        locations_in_df = df["location"].unique()
        self.assertEqual(len(locations_in_df), 6)

    @patch('realtime_api.openmeteo_client.requests.Session.get')
    def test_fetch_with_network_error(self, mock_get):
        """测试网络错误处理"""
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError("连接失败")

        client = OpenMeteoClient(rate_limit_interval=0.01)
        df, reports = client.fetch_weather_data()

        # 应返回空 DataFrame
        self.assertEqual(len(df), 0)
        # 所有站点应标记为无效
        for name, report in reports.items():
            self.assertFalse(report.is_valid)

    @patch('realtime_api.openmeteo_client.requests.Session.get')
    def test_fetch_with_timeout(self, mock_get):
        """测试超时处理"""
        import requests as req
        mock_get.side_effect = req.exceptions.Timeout("请求超时")

        client = OpenMeteoClient(rate_limit_interval=0.01, request_timeout=1)
        df, reports = client.fetch_weather_data()

        self.assertEqual(len(df), 0)
        for name, report in reports.items():
            self.assertFalse(report.is_valid)

    @patch('realtime_api.openmeteo_client.requests.Session.get')
    def test_fetch_single_location(self, mock_get):
        """测试获取单个站点"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = create_mock_api_response(num_hours=24)
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = OpenMeteoClient(rate_limit_interval=0.01)
        df, report = client.fetch_single_location("Boston")

        self.assertGreater(len(df), 0)
        self.assertTrue((df["location"] == "Boston").all())
        self.assertEqual(report.location, "Boston")


class TestRegionalAverage(unittest.TestCase):
    """测试区域平均计算"""

    @patch('realtime_api.openmeteo_client.requests.Session.get')
    def test_regional_average(self, mock_get):
        """测试区域平均数据计算"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = create_mock_api_response(num_hours=48)
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = OpenMeteoClient(rate_limit_interval=0.01)
        regional_df = client.get_regional_average()

        self.assertGreater(len(regional_df), 0)
        self.assertIn("timestamp", regional_df.columns)
        self.assertIn("temperature_2m", regional_df.columns)
        self.assertTrue((regional_df["location"] == "Regional_Average").all())

        # 验证行数应该等于时间点数（48小时）
        # 由于6个站点的时间戳相同，平均后应该有48行
        self.assertEqual(len(regional_df), 48)


class TestErrorHandling(unittest.TestCase):
    """测试错误处理"""

    def test_invalid_location_name(self):
        """测试无效站点名称"""
        client = OpenMeteoClient()
        with self.assertRaises(ValueError) as context:
            client.fetch_single_location("InvalidCity")

        self.assertIn("未找到站点", str(context.exception))

    def test_quality_report_json(self):
        """测试 JSON 质量报告"""
        client = OpenMeteoClient()
        reports = {
            "Boston": DataQualityReport(location="Boston", total_records=192),
            "Hartford": DataQualityReport(location="Hartford", total_records=192),
        }

        json_str = client.get_quality_report_json(reports)
        parsed = json.loads(json_str)

        self.assertIn("Boston", parsed)
        self.assertEqual(parsed["Boston"]["total_records"], 192)


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    # 使用 unittest 运行
    unittest.main(verbosity=2)

    # 也可以使用 pytest:
    # python -m pytest realtime_api/test_openmeteo_client.py -v
