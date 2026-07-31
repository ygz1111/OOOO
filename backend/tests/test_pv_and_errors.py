# -*- coding: utf-8 -*-
"""光伏物理估算模型与错误响应格式测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtime_api.pv_estimator import PVGenerationEstimator
from realtime_api.error_handling import create_error_response, ErrorCode


class TestPVEstimator:
    def test_estimate_zero_radiation(self):
        """无辐射 → 光伏出力为 0"""
        est = PVGenerationEstimator(installed_capacity_mw=100.0)
        out = est.estimate(radiation=0.0, temperature=25.0)
        assert out == 0.0

    def test_estimate_positive_bounded(self):
        """正辐射下的出力应在 [0, 装机容量] 范围内"""
        est = PVGenerationEstimator(installed_capacity_mw=100.0)
        out = est.estimate(radiation=800.0, temperature=25.0)
        assert 0.0 <= out <= 100.0

    def test_estimate_24h_shape(self):
        import pandas as pd
        est = PVGenerationEstimator(installed_capacity_mw=50.0)
        # 构造全天无辐射的气象 DataFrame
        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-07-31", periods=24, freq="h"),
            "shortwave_radiation": [0.0] * 24,
            "cloud_cover": [100] * 24,
            "temperature_2m": [25.0] * 24,
        })
        res = est.estimate_24h(df)
        assert hasattr(res, "hourly_generation_mw")
        # 夜间无出力
        pv = res.hourly_generation_mw
        assert len(pv) == 24
        assert all(v == 0.0 for v in pv)


class TestErrorResponse:
    def test_create_error_response_format(self):
        resp = create_error_response(ErrorCode.VALIDATION_ERROR, message="参数错误")
        assert resp["error_code"] == ErrorCode.VALIDATION_ERROR.value
        assert resp["message"] == "参数错误"
        assert "timestamp" in resp and "error_id" in resp
        # 时间戳必须是可序列化字符串
        assert isinstance(resp["timestamp"], str)

    def test_error_code_enum_values(self):
        assert ErrorCode.VALIDATION_ERROR.value == 40001
