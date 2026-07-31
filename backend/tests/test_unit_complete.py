#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整的系统单元测试套件

测试类型:
  - 单元测试：各模块功能验证
  - 数据验证测试
  - 边界条件测试
  - 错误处理测试

运行:
  pytest tests/test_unit_complete.py -v --tb=short
  pytest tests/test_unit_complete.py::TestWeatherValidator -v
  pytest tests/test_unit_complete.py -k "test_weather" -v
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
import json

from realtime_api.openmeteo_client import OpenMeteoClient, WeatherLocation
from realtime_api.weather_validator import WeatherDataValidator, DataQualityReport
from realtime_api.feature_generator import FeatureGenerator
from realtime_api.normalization_adapter import NormalizationAdapter
from realtime_api.prediction_service import ModelInferenceService, PredictionResult
from realtime_api.pv_estimator import SolarEstimator
from realtime_api.net_load_calculator import NetLoadCalculator
from realtime_api.monitoring_service import MonitoringService


class TestWeatherValidator:
    """气象数据验证器单元测试"""
    
    @pytest.mark.unit
    def test_normal_weather_data_validation(self, weather_validator, sample_weather_data):
        """测试正常气象数据验证"""
        clean_df, quality_report, anomaly_flags = weather_validator.validate(sample_weather_data)
        
        assert isinstance(clean_df, pd.DataFrame)
        assert isinstance(quality_report, DataQualityReport)
        assert isinstance(anomaly_flags, dict)
        assert len(clean_df) <= len(sample_weather_data)
        
        # 验证质量报告结构
        assert hasattr(quality_report, 'overall_score')
        assert hasattr(quality_report, 'parameter_scores')
        assert hasattr(quality_report, 'anomaly_count')
        assert quality_report.overall_score >= 0.8  # 正常数据应该有高分数
    
    @pytest.mark.unit 
    def test_extreme_weather_data_validation(self, weather_validator, extreme_weather_data):
        """测试极端气象数据验证"""
        clean_df, quality_report, anomaly_flags = weather_validator.validate(extreme_weather_data)
        
        assert isinstance(clean_df, pd.DataFrame)
        assert quality_report.overall_score < 0.8  # 极端数据分数应该较低
        assert 'temperature_2m' in quality_report.parameter_scores
    
    @pytest.mark.unit
    def test_anomaly_weather_data_validation(self, weather_validator, anomaly_weather_data):
        """测试异常气象数据验证"""
        clean_df, quality_report, anomaly_flags = weather_validator.validate(
            anomaly_weather_data, raise_on_severe=False
        )
        
        assert quality_report.anomaly_count > 0
        assert quality_report.overall_score < 0.5  # 异常数据分数应该很低
    
    @pytest.mark.unit
    def test_missing_data_handling(self, weather_validator, test_data_generator):
        """测试缺失数据处理"""
        # 创建包含缺失值的数据
        data_with_nan = test_data_generator.generate_weather_data(hours=10)
        data_with_nan.loc[5, 'temperature_2m'] = np.nan
        data_with_nan.loc[7, 'wind_speed_10m'] = np.nan
        
        clean_df, quality_report, _ = weather_validator.validate(data_with_nan)
        
        # 验证缺失值被处理
        assert not clean_df['temperature_2m'].isna().any()
        assert quality_report.missing_data_count > 0
    
    @pytest.mark.unit
    def test_temperature_range_validation(self, weather_validator):
        """测试温度范围验证"""
        # 创建异常温度数据
        test_data = pd.DataFrame([{
            'timestamp': datetime.now(timezone.utc),
            'location': 'Test',
            'temperature_2m': 100.0,  # 异常高温
            'dew_point_2m': 20.0,
            'relative_humidity_2m': 60,
            'wind_speed_10m': 10,
            'cloud_cover': 50,
            'shortwave_radiation': 800
        }])
        
        clean_df, quality_report, anomaly_flags = weather_validator.validate(
            test_data, raise_on_severe=False
        )
        
        assert quality_report.anomaly_count > 0
        assert quality_report.overall_score < 0.6


class TestFeatureGenerator:
    """特征生成器单元测试"""
    
    @pytest.mark.unit
    def test_feature_generation_pipeline(self, feature_generator, sample_weather_data, historical_load_data):
        """测试完整特征生成管道"""
        features = feature_generator.generate(sample_weather_data, historical_load_data)
        
        assert isinstance(features, pd.DataFrame)
        assert len(features) > 0
        
        # 验证必需特征存在
        required_features = [
            'Dry_Bulb', 'Dew_Point', 'humidity_index', 'wind_speed', 
            'load_lag_1h', 'load_lag_24h', 'hour_sin', 'hour_cos'
        ]
        
        for feature in required_features:
            assert feature in features.columns, f"缺少必需特征: {feature}"
    
    @pytest.mark.unit
    def test_lag_feature_generation(self, feature_generator, test_data_generator):
        """测试滞后特征生成"""
        weather_data = test_data_generator.generate_weather_data(hours=48)
        load_data = test_data_generator.generate_historical_load_data(hours=192)  # 8天数据
        
        features = feature_generator.generate(weather_data, load_data)
        
        # 验证滞后特征存在且值合理
        lag_features = [col for col in features.columns if 'lag' in col]
        assert len(lag_features) >= 6  # 至少6个滞后特征
        
        for feature in lag_features:
            assert not features[feature].isna().all(), f"{feature}特征全部为NaN"
    
    @pytest.mark.unit
    def test_rolling_feature_generation(self, feature_generator, test_data_generator):
        """测试滚动窗口特征生成"""
        weather_data = test_data_generator.generate_weather_data(hours=72)
        load_data = test_data_generator.generate_historical_load_data(hours=240)  # 10天数据
        
        features = feature_generator.generate(weather_data, load_data)
        
        # 验证滚动特征存在
        rolling_features = [col for col in features.columns if 'rolling' in col]
        assert len(rolling_features) >= 6  # 至少6个滚动特征
        
        # 验证统计特征值范围
        for feature in rolling_features:
            if 'mean' in feature:
                assert features[feature].min() >= 0, f"{feature}存在负值"
    
    @pytest.mark.unit
    def test_time_feature_generation(self, feature_generator, test_data_generator):
        """测试时间特征生成"""
        weather_data = test_data_generator.generate_weather_data(hours=48)
        load_data = test_data_generator.generate_historical_load_data(hours=168)
        
        features = feature_generator.generate(weather_data, load_data)
        
        # 验证时间特征
        time_features = ['hour_sin', 'hour_cos', 'day_of_week', 'is_weekend']
        for feature in time_features:
            assert feature in features.columns, f"缺少时间特征: {feature}"
        
        # 验证正弦余弦值范围
        assert features['hour_sin'].between(-1, 1).all()
        assert features['hour_cos'].between(-1, 1).all()
    
    @pytest.mark.unit
    def test_sequence_building(self, feature_generator, test_data_generator):
        """测试序列构建"""
        # 生成测试特征数据
        weather_data = test_data_generator.generate_weather_data(hours=24)
        load_data = test_data_generator.generate_historical_load_data(hours=200)
        
        features = feature_generator.generate(weather_data, load_data)
        
        # 构建序列
        sequences = feature_generator.build_sequences(features, lookback=168, horizon=24)
        
        assert isinstance(sequences, dict)
        assert 'X' in sequences
        assert 'y' in sequences
        
        # 验证序列形状
        assert len(sequences['X'].shape) == 3  # (samples, timesteps, features)
        assert len(sequences['y'].shape) == 2  # (samples, horizon)
        assert sequences['X'].shape[2] == 38  # 38个特征


class TestNormalizationAdapter:
    """归一化适配器单元测试"""
    
    @pytest.mark.unit
    def test_normalization_pipeline(self, normalization_adapter, test_data_generator):
        """测试归一化管道"""
        # 生成测试特征数据
        weather_data = test_data_generator.generate_weather_data(hours=24)
        load_data = test_data_generator.generate_historical_load_data(hours=200)
        
        # 创建特征数据
        features_df = test_data_generator.generate_weather_data(hours=10)
        features_df = features_df.rename(columns={
            'temperature_2m': 'Dry_Bulb',
            'dew_point_2m': 'Dew_Point'
        })
        
        # 添加必需的38个特征 (简化版本)
        required_features = [f'feature_{i}' for i in range(38)]
        for i, feature in enumerate(required_features):
            features_df[feature] = np.random.randn(len(features_df)) * 100
        
        # 测试归一化
        try:
            normalized = normalization_adapter.transform_features(features_df)
            
            assert isinstance(normalized, np.ndarray)
            assert normalized.shape[1] == 38  # 38个归一化特征
            
            # 验证归一化范围 (应该在合理范围内)
            assert normalized.min() >= -10, "归一化值过低"
            assert normalized.max() <= 10, "归一化值过高"
            
        except Exception as e:
            # 如果没有预训练的scaler，应该能正常处理
            assert "scalers not fitted" in str(e) or "No scalers" in str(e)
    
    @pytest.mark.unit
    def test_inverse_normalization(self, normalization_adapter, test_data_generator):
        """测试逆归一化"""
        # 生成归一化数据
        normalized_data = np.random.randn(24, 38)
        
        try:
            inverse_data = normalization_adapter.inverse_transform(normalized_data)
            
            assert isinstance(inverse_data, np.ndarray)
            assert inverse_data.shape == normalized_data.shape
            
        except Exception as e:
            # 如果没有预训练的scaler，应该抛出适当的异常
            assert "scalers not fitted" in str(e) or "No scalers" in str(e)
    
    @pytest.mark.unit
    def test_missing_feature_handling(self, normalization_adapter):
        """测试缺失特征处理"""
        # 创建不包含所有必需特征的数据
        incomplete_features = pd.DataFrame({
            'Dry_Bulb': [25.0, 26.0],
            'Dew_Point': [15.0, 16.0]
            # 故意缺少其他特征
        })
        
        with pytest.raises((KeyError, ValueError)):
            normalization_adapter.transform_features(incomplete_features)


class TestSolarEstimator:
    """光伏发电估算器单元测试"""
    
    @pytest.mark.unit
    def test_basic_pv_estimation(self, solar_estimator):
        """测试基础光伏发电估算"""
        # 测试正常条件
        radiation = 800  # W/m²
        temperature = 25  # °C
        
        pv_output = solar_estimator.estimate(radiation, temperature)
        
        assert isinstance(pv_output, (int, float))
        assert pv_output > 0
        assert pv_output <= solar_estimator.installed_capacity  # 不能超过装机容量
    
    @pytest.mark.unit
    def test_zero_radiation(self, solar_estimator):
        """测试零辐射情况"""
        pv_output = solar_estimator.estimate(0, 25)
        assert pv_output == 0
    
    @pytest.mark.unit
    def test_high_temperature_effect(self, solar_estimator):
        """测试高温对效率的影响"""
        radiation = 800
        temp_normal = 25
        temp_high = 45
        
        pv_normal = solar_estimator.estimate(radiation, temp_normal)
        pv_high_temp = solar_estimator.estimate(radiation, temp_high)
        
        assert pv_high_temp < pv_normal  # 高温时效率降低
        assert pv_high_temp > 0  # 但仍应有一定输出
    
    @pytest.mark.unit
    def test_extreme_temperature(self, solar_estimator):
        """测试极端温度"""
        radiation = 500
        extreme_temp = 80  # 极端高温
        
        pv_output = solar_estimator.estimate(radiation, extreme_temp)
        
        assert pv_output >= 0  # 不应为负
        assert pv_output < solar_estimator.estimate(radiation, 25)  # 低于正常温度
    
    @pytest.mark.unit
    def test_custom_parameters(self):
        """测试自定义参数"""
        custom_estimator = SolarEstimator(
            installed_capacity_mw=1000.0,
            performance_ratio=0.85
        )
        
        pv_output = custom_estimator.estimate(800, 25)
        
        assert pv_output <= 1000.0  # 不超过自定义装机容量
        
        # 对比不同性能比的影响
        pv_custom = custom_estimator.estimate(800, 25)
        pv_default = SolarEstimator().estimate(800, 25)
        
        assert pv_custom > pv_default  # 更高性能比应有更高输出


class TestNetLoadCalculator:
    """净负荷计算器单元测试"""
    
    @pytest.mark.unit
    def test_basic_net_load_calculation(self, net_load_calculator):
        """测试基础净负荷计算"""
        total_load = [10000, 11000, 12000]  # MW
        pv_generation = [0, 500, 1000]  # MW
        
        net_load = net_load_calculator.calculate_net_load(total_load, pv_generation)
        
        assert len(net_load) == len(total_load)
        assert net_load[0] == 10000  # 夜间无光伏发电
        assert net_load[1] == 10500  # 日间减去光伏发电
        assert net_load[2] == 11000
    
    @pytest.mark.unit
    def test_negative_pv_handling(self, net_load_calculator):
        """测试负值处理"""
        total_load = [10000, 11000]
        pv_generation = [0, -100]  # 负值光伏 (异常情况)
        
        net_load = net_load_calculator.calculate_net_load(total_load, pv_generation)
        
        assert net_load[1] >= 0  # 净负荷不应为负
    
    @pytest.mark.unit
    def test_zero_net_load(self, net_load_calculator):
        """测试零净负荷情况"""
        total_load = [1000]
        pv_generation = [1000]  # 光伏发电等于总负荷
        
        net_load = net_load_calculator.calculate_net_load(total_load, pv_generation)
        
        assert net_load[0] == 0  # 净负荷为零
    
    @pytest.mark.unit
    def test_excess_pv_generation(self, net_load_calculator):
        """测试光伏过剩情况"""
        total_load = [1000]
        pv_generation = [1500]  # 光伏发电超过负荷
        
        net_load = net_load_calculator.calculate_net_load(total_load, pv_generation)
        
        # 根据实现，可能需要考虑是否允许负净负荷
        assert isinstance(net_load[0], (int, float))


class TestMonitoringService:
    """监控服务单元测试"""
    
    @pytest.mark.unit
    def test_monitoring_metrics_collection(self, monitoring_service):
        """测试监控指标收集"""
        # 模拟添加一些监控数据
        monitoring_service.record_prediction_request('test_request')
        monitoring_service.record_inference_time(150.5)
        monitoring_service.record_data_quality(0.95)
        
        # 获取监控指标
        metrics = monitoring_service.get_metrics()
        
        assert isinstance(metrics, dict)
        assert 'prediction_requests' in metrics
        assert 'average_inference_time_ms' in metrics
        assert 'data_quality_score' in metrics
        
        assert metrics['prediction_requests'] > 0
    
    @pytest.mark.unit
    def test_error_rate_tracking(self, monitoring_service):
        """测试错误率跟踪"""
        # 模拟正常请求
        for _ in range(8):
            monitoring_service.record_prediction_request('normal_request')
        
        # 模拟错误请求
        for _ in range(2):
            try:
                raise Exception("模拟错误")
            except:
                monitoring_service.record_error()
        
        metrics = monitoring_service.get_metrics()
        
        assert 'error_count' in metrics
        assert 'error_rate' in metrics
        assert metrics['error_count'] == 2
        assert 0.1 <= metrics['error_rate'] <= 0.3  # 大约20%的错误率
    
    @pytest.mark.unit
    def test_performance_monitoring(self, monitoring_service):
        """测试性能监控"""
        # 记录不同时间的推理时间
        times = [100, 150, 200, 120, 180]
        
        for time_ms in times:
            monitoring_service.record_inference_time(time_ms)
        
        metrics = monitoring_service.get_metrics()
        
        assert 'min_inference_time_ms' in metrics
        assert 'max_inference_time_ms' in metrics
        assert 'average_inference_time_ms' in metrics
        
        assert metrics['min_inference_time_ms'] == min(times)
        assert metrics['max_inference_time_ms'] == max(times)
        assert 140 <= metrics['average_inference_time_ms'] <= 160  # 平均值
    
    @pytest.mark.unit
    def test_alert_generation(self, monitoring_service):
        """测试告警生成"""
        # 模拟触发各种告警条件
        
        # 高错误率告警
        for _ in range(20):
            monitoring_service.record_prediction_request('test')
        
        for _ in range(15):  # 75% 错误率
            monitoring_service.record_error()
        
        # 慢响应时间告警
        for _ in range(5):
            monitoring_service.record_inference_time(1000)  # 1秒，很慢
        
        alerts = monitoring_service.check_alerts()
        
        assert isinstance(alerts, list)
        alert_types = [alert.get('type') for alert in alerts]
        
        assert 'high_error_rate' in alert_types or 'slow_response' in alert_types