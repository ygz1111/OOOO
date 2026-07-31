# -*- coding: utf-8 -*-
"""特征工程与预测管线纯函数测试（离线，不依赖模型/数据库）。"""
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtime_api.services.prediction_pipeline import (
    weather_points_to_df,
    load_points_to_df,
    _extract_hourly_weather,
)
from realtime_api.feature_generator import FeatureGenerator


class TestPipelineHelpers:
    def test_weather_points_to_df(self):
        class P:
            def __init__(self, ts, t, d, h, w, c, s):
                self.timestamp = ts
                self.temperature_2m = t
                self.dew_point_2m = d
                self.relative_humidity_2m = h
                self.wind_speed_10m = w
                self.cloud_cover = c
                self.shortwave_radiation = s

        pts = [P("2026-07-31T10:00:00", 25.0, 15.0, 60.0, 3.0, 20.0, 500.0)]
        df = weather_points_to_df(pts)
        assert "temperature_2m" in df.columns
        assert df.iloc[0]["temperature_2m"] == 25.0

    def test_load_points_to_df(self):
        class LP:
            def __init__(self, ts, load):
                self.timestamp = ts
                self.system_load = load

        df = load_points_to_df([LP("2026-07-31T10:00:00", 15000.0)])
        assert df.iloc[0]["System_Load"] == 15000.0

    def test_extract_hourly_weather_windows(self):
        """±30 分钟窗口聚合：整点预测应取到窗口内的气象均值"""
        now = datetime(2026, 7, 31, 10, 0)
        df = pd.DataFrame({
            "timestamp": pd.to_datetime([
                "2026-07-31 09:59:00", "2026-07-31 10:00:00",
                "2026-07-31 10:01:00", "2026-07-31 11:00:00",
            ]),
            "shortwave_radiation": [100.0, 200.0, 300.0, 400.0],
            "temperature_2m": [20.0, 25.0, 30.0, 35.0],
            "wind_speed_10m": [1.0, 2.0, 3.0, 4.0],
        })
        rad, temp, ws, wd, pres, pv_df = _extract_hourly_weather(df, now, hours=2)
        # 第 0 小时窗口 09:30-10:30 覆盖前三条 → 辐射均值 (100+200+300)/3=200
        assert abs(rad[0] - 200.0) < 1e-6
        # 第 1 小时窗口 10:30-11:30 覆盖 11:00 → 辐射 400
        assert abs(rad[1] - 400.0) < 1e-6


class TestFeatureGenerator:
    def test_build_sequence_shape(self):
        """lookback=168, 38 特征 → 序列 (1, 168, 38)（返回单个 ndarray）"""
        fg = FeatureGenerator()
        n = 200
        rng = np.random.RandomState(0)
        df = pd.DataFrame(rng.uniform(0, 1, size=(n, 38)),
                          columns=fg.feature_cols)
        X = fg.build_sequence(df, lookback=168)
        assert X.shape == (1, 168, 38)

    def test_build_sequence_pads_short_input(self):
        """数据不足 lookback 时用 0 填充，不崩溃"""
        fg = FeatureGenerator()
        df = pd.DataFrame(np.zeros((10, 38)), columns=fg.feature_cols)
        X = fg.build_sequence(df, lookback=168)
        assert X.shape == (1, 168, 38)
        # 前 (168-10) 行应为填充的 0
        assert (X[0, :158, :] == 0).all()
        # 末尾 10 行为原始数据（也全 0）
        assert (X[0, 158:, :] == 0).all()
