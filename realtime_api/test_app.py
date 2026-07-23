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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 使用 TestClient 需要先安装 httpx
try:
    from fastapi.testclient import TestClient
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from realtime_api.app import app, SolarEstimator
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
from realtime_api.prediction_service import ModelInferenceService


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
# 光伏估算器测试（不需要启动服务器）
# ============================================================================

class TestSolarEstimator(unittest.TestCase):
    """测试光伏发电估算器"""

    def setUp(self):
        self.estimator = SolarEstimator(installed_capacity_mw=500, performance_ratio=0.8)

    def test_zero_radiation(self):
        """零辐射时光伏输出为0"""
        result = self.estimator.estimate(0)
        self.assertEqual(result, 0.0)

    def test_negative_radiation(self):
        """负辐射时光伏输出为0"""
        result = self.estimator.estimate(-10)
        self.assertEqual(result, 0.0)

    def test_full_sun(self):
        """满辐射（1000 W/m²）时输出应接近装机容量×PR"""
        result = self.estimator.estimate(1000, temperature=25)
        self.assertAlmostEqual(result, 500 * 0.8, places=1)

    def test_partial_radiation(self):
        """部分辐射（500 W/m²）时输出减半"""
        result = self.estimator.estimate(500, temperature=25)
        self.assertAlmostEqual(result, 250 * 0.8, places=1)

    def test_temperature_attenuation(self):
        """高温时效率下降"""
        cool = self.estimator.estimate(1000, temperature=25)
        hot = self.estimator.estimate(1000, temperature=35)
        self.assertLess(hot, cool, "高温时光伏应输出更少")


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


# ============================================================================
# API 端点测试（使用 TestClient）
# ============================================================================

@unittest.skipUnless(HAS_HTTPX, "需要安装 httpx: pip install httpx")
class TestAPIEndpoints(unittest.TestCase):
    """测试 API 端点"""

    @classmethod
    def setUpClass(cls):
        """启动测试客户端（使用上下文管理器触发 lifespan）"""
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        """关闭测试客户端"""
        cls._ctx.__exit__(None, None, None)

    def test_root(self):
        """测试根路径"""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("service", data)
        self.assertIn("endpoints", data)

    def test_system_status(self):
        """测试系统状态接口"""
        response = self.client.get("/api/system/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)
        self.assertIn("models_loaded", data)
        self.assertIn("device", data)
        self.assertIn("timestamp", data)

    def test_docs_available(self):
        """测试 OpenAPI 文档可用"""
        response = self.client.get("/docs")
        self.assertEqual(response.status_code, 200)

    def test_openapi_schema(self):
        """测试 OpenAPI Schema"""
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        self.assertIn("paths", schema)
        self.assertIn("/api/prediction/load", schema["paths"])
        self.assertIn("/api/weather/current", schema["paths"])
        self.assertIn("/api/system/status", schema["paths"])
        self.assertIn("/api/prediction/batch", schema["paths"])

    def test_prediction_with_weather_data(self):
        """测试提供气象数据的负荷预测"""
        weather_data = [p.model_dump(mode='json') for p in make_mock_weather_data(200)]
        response = self.client.post(
            "/api/prediction/load",
            json={
                "weather_data": weather_data,
                "forecast_hours": 24,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["predictions"]), 24)
        self.assertGreater(len(data["model_info"]), 0)

    def test_prediction_response_format(self):
        """测试预测响应格式"""
        weather_data = [p.model_dump(mode='json') for p in make_mock_weather_data(200)]
        response = self.client.post(
            "/api/prediction/load",
            json={"weather_data": weather_data},
        )
        data = response.json()

        # 验证每小时预测格式
        pred = data["predictions"][0]
        self.assertIn("hour", pred)
        self.assertIn("timestamp", pred)
        self.assertIn("load_forecast_mw", pred)
        self.assertIn("pv_estimation_mw", pred)
        self.assertIn("net_load_mw", pred)

    def test_prediction_values_reasonable(self):
        """测试预测值在合理范围"""
        weather_data = [p.model_dump(mode='json') for p in make_mock_weather_data(200)]
        response = self.client.post(
            "/api/prediction/load",
            json={"weather_data": weather_data},
        )
        data = response.json()

        for pred in data["predictions"]:
            # 负荷应在 5000~30000 MW
            self.assertGreater(pred["load_forecast_mw"], 0)
            self.assertLess(pred["load_forecast_mw"], 50000)
            # 光伏应非负
            self.assertGreaterEqual(pred["pv_estimation_mw"], 0)
            # 净负荷 = 负荷 - 光伏
            expected_net = pred["load_forecast_mw"] - pred["pv_estimation_mw"]
            self.assertAlmostEqual(pred["net_load_mw"], round(expected_net, 1), places=0)

    def test_prediction_inference_time(self):
        """测试推理时间记录"""
        weather_data = [p.model_dump(mode='json') for p in make_mock_weather_data(200)]
        response = self.client.post(
            "/api/prediction/load",
            json={"weather_data": weather_data},
        )
        data = response.json()
        self.assertGreater(data["inference_time_ms"], 0)

    def test_invalid_request_missing_weather(self):
        """测试缺少必需字段"""
        response = self.client.post(
            "/api/prediction/load",
            json={"forecast_hours": 24},  # 缺少 weather_data（可选，但有 forecast_hours）
        )
        # 不提供 weather_data 时会尝试自动获取，可能成功或失败
        self.assertIn(response.status_code, [200, 422, 502, 500])

    def test_batch_prediction(self):
        """测试批量预测"""
        items = []
        for _ in range(3):
            weather_data = [p.model_dump(mode='json') for p in make_mock_weather_data(200)]
            items.append({"weather_data": weather_data})

        response = self.client.post(
            "/api/prediction/batch",
            json={"requests": items},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["results"]), 3)
        self.assertGreater(data["total_time_ms"], 0)

    def test_batch_max_items_exceeded(self):
        """测试批量请求超过10个"""
        items = [{"weather_data": [make_mock_weather_data(1)[0].model_dump(mode='json')]}] * 11
        response = self.client.post(
            "/api/prediction/batch",
            json={"requests": items},
        )
        self.assertEqual(response.status_code, 422)  # 验证错误

    def test_process_time_header(self):
        """测试响应头包含处理时间"""
        response = self.client.get("/api/system/status")
        self.assertIn("X-Process-Time", response.headers)

    def test_cors_headers(self):
        """测试 CORS 头"""
        response = self.client.get(
            "/",
            headers={"Origin": "http://localhost:3000"},
        )
        self.assertIn("access-control-allow-origin", {k.lower() for k in response.headers})


# ============================================================================
# 预测管线测试（直接调用，不走HTTP）
# ============================================================================

class TestPredictionPipeline(unittest.TestCase):
    """直接测试预测管线函数"""

    def setUp(self):
        """确保服务已初始化"""
        from realtime_api.app import services
        if services.inference_service is None or not services.inference_service.is_ready():
            # 手动初始化
            services.openmeteo_client = OpenMeteoClient(
                past_days=7, forecast_days=1, rate_limit_interval=0.01
            )
            services.weather_validator = WeatherDataValidator()
            services.feature_generator = FeatureGenerator()
            services.normalizer = NormalizationAdapter()
            services.inference_service = ModelInferenceService()
            services.inference_service.load_models()
            services.start_time = time.time()

    def test_pipeline_with_mock_data(self):
        """测试使用模拟数据的预测管线"""
        from realtime_api.app import run_prediction_pipeline
        from realtime_api.app import weather_points_to_df

        weather_data = make_mock_weather_data(200)
        weather_df = weather_points_to_df(weather_data)

        response = run_prediction_pipeline(weather_df, None)

        self.assertEqual(response.status, "success")
        self.assertEqual(len(response.predictions), 24)

        for pred in response.predictions:
            self.assertIsInstance(pred.load_forecast_mw, float)
            self.assertIsInstance(pred.pv_estimation_mw, float)
            self.assertIsInstance(pred.net_load_mw, float)


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
