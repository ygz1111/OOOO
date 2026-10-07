# -*- coding: utf-8 -*-
"""错误响应格式测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtime_api.error_handling import create_error_response, ErrorCode
from realtime_api.routers.generation import _pv_backtest_metrics


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


def test_pv_backtest_mape_excludes_zero_night_hours():
    metrics = _pv_backtest_metrics([
        {"historical_actual": 0.0, "historical_forecast": 100.0},
        # 当前口径只在真实 BTM 估算值 > 500 MW 的稳定出力时段计算 MAPE。
        {"historical_actual": 600.0, "historical_forecast": 660.0},
    ])

    assert metrics["count"] == 2
    assert metrics["daylight_count"] == 1
    assert metrics["mae_mw"] == 80.0
    assert metrics["rmse_mw"] == 82.5
    assert metrics["mape"] == 10.0
