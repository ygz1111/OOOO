"""
FastAPI 实时预测服务单元测试

测试内容:
  1. 根路径响应
  2. 系统状态接口
  3. 负荷预测接口（提供气象数据）
  4. 负荷预测接口（自动获取气象数据）
  5. 当前气象数据接口
  6. 批量预测接口
  7. 请求参数验证
  8. 错误处理
  9. 响应格式验证

运行方式:
    cd c:/OOOO/OOOO
    python realtime_api/test_app.py -v

    注意: 需要先安装 fastapi, uvicorn, httpx
"""

import unittest
import os
import sys
import json
import asyncio
import time
from datetime import datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 使用 TestClient 需要先安装 httpx
try:
    from fastapi.testclient import TestClient
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from realtime_api.schemas import (
    LoadPredictionRequest,
    LoadPredictionResponse,
    HourlyPrediction,
    WeatherDataPoint,
    WeatherResponse,
    SystemStatusResponse,
    BatchPredictionRequest,
)
from realtime_api.openmeteo_client import OpenMeteoClient
from realtime_api.weather_validator import WeatherDataValidator
from realtime_api.feature_generator import FeatureGenerator
from realtime_api.normalization_adapter import NormalizationAdapter


# ============================================================================
# 辅助函数
# ============================================================================

def make_mock_weather_data(n=200):
    """生成模拟气象数据点列表"""
    points = []
    base_time = datetime(2025, 7, 10, 0, 0)
    for i in range(n):
        points.append(WeatherDataPoint(
            timestamp=base_time + timedelta(hours=i),
            temperature_2m=25 + 5 * np.sin(2 * np.pi * i / 24),
            dew_point_2m=15 + 3 * np.sin(2 * np.pi * i / 24),
            relative_humidity_2m=65,
            wind_speed_10m=5.0,
            cloud_cover=30,
            shortwave_radiation=max(0, 500 * np.sin(2 * np.pi * (i % 24) / 24)),
        ))
    return points


# ============================================================================
# 数据模型验证测试
# ============================================================================

class TestSchemaValidation(unittest.TestCase):
    """测试 Pydantic 数据模型验证"""

    def test_valid_weather_point(self):
        """测试有效气象数据点"""
        point = WeatherDataPoint(
            timestamp=datetime(2025, 7, 23, 14),
            temperature_2m=28.5,
            dew_point_2m=18.0,
        )
        self.assertEqual(point.temperature_2m, 28.5)

    def test_invalid_temperature_range(self):
        """测试温度超出范围"""
        with self.assertRaises(Exception):
            WeatherDataPoint(
                timestamp=datetime(2025, 7, 23),
                temperature_2m=100,  # 超出 ge=-60, le=60
                dew_point_2m=15,
            )

    def test_dew_point_above_temp(self):
        """测试露点高于气温被拒绝"""
        with self.assertRaises(Exception):
            WeatherDataPoint(
                timestamp=datetime(2025, 7, 23),
                temperature_2m=20.0,
                dew_point_2m=25.0,  # 高于气温
            )

    def test_valid_prediction_request(self):
        """测试有效预测请求"""
        weather_data = make_mock_weather_data(200)
        req = LoadPredictionRequest(
            weather_data=weather_data,
            forecast_hours=24,
        )
        self.assertEqual(len(req.weather_data), 200)

    def test_batch_request_max_items(self):
        """测试批量请求最多10个"""
        items = [
            {"weather_data": [make_mock_weather_data(1)[0].model_dump(mode='json')]}
        ] * 11  # 超过10个
        with self.assertRaises(Exception):
            BatchPredictionRequest(requests=items)


class TestApplicationRoutes(unittest.TestCase):
    """检查实际应用路由，不启动生命周期、模型、数据库或外部请求。"""

    @classmethod
    def setUpClass(cls):
        from realtime_api.app import app

        cls.schema = app.openapi()

    def test_openapi_excludes_removed_caiso_feature(self):
        self.assertNotIn("caiso", json.dumps(self.schema, ensure_ascii=False).lower())

    def test_iso_ne_and_supporting_routes_remain_registered(self):
        expected_routes = {
            "/api/prediction/load": "post",
            "/api/prediction/overview": "get",
            "/api/price/forecast": "get",
            "/api/price/backtest": "get",
            "/api/price/model-info": "get",
            "/api/solar-generation": "get",
            "/api/solar-generation/model-info": "get",
            "/api/analytics/backtest/date": "get",
            "/api/weather/current": "get",
            "/api/system/status": "get",
            "/api/auth/login": "post",
            "/api/health": "get",
        }
        for path, method in expected_routes.items():
            with self.subTest(path=path, method=method):
                self.assertIn(method, self.schema["paths"].get(path, {}))
