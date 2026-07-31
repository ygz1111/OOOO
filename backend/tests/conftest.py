#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试配置文件 - 提供通用测试夹具和配置

包含:
  - 测试数据生成器
  - 模拟对象(Mock)
  - 测试夹具(fixtures)
  - 测试环境配置
  - 常用测试工具函数

作者: 毕业设计项目
"""

import os
import sys
import pytest
import tempfile
import shutil
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 导入项目模块
from realtime_api.openmeteo_client import OpenMeteoClient, WeatherLocation
from realtime_api.weather_validator import WeatherDataValidator
from realtime_api.feature_generator import FeatureGenerator
from realtime_api.normalization_adapter import NormalizationAdapter
from realtime_api.prediction_service import ModelInferenceService, PredictionResult
from realtime_api.pv_estimator import SolarEstimator
from realtime_api.net_load_calculator import NetLoadCalculator
from realtime_api.monitoring_service import MonitoringService
from realtime_api.schemas import (
    WeatherDataPoint, LoadPredictionRequest, WeatherStationData
)


# =================================================================================
# 测试数据生成器
# =================================================================================

class TestDataGenerator:
    """测试数据生成器 - 生成各种场景的测试数据"""
    
    @staticmethod
    def generate_weather_data(
        hours: int = 24,
        locations: list = None,
        scenario: str = 'normal'
    ) -> pd.DataFrame:
        """生成气象数据
        
        Args:
            hours: 数据小时数
            locations: 位置列表
            scenario: 场景类型 ('normal', 'extreme', 'anomaly')
            
        Returns:
            pd.DataFrame: 生成的气象数据
        """
        if locations is None:
            locations = ['Boston', 'Hartford', 'Portland']
            
        # 基础参数设置
        base_temp = 25.0  # 基础温度
        base_humidity = 60.0  # 基础湿度
        base_wind = 10.0  # 基础风速
        
        if scenario == 'extreme':
            base_temp = 40.0  # 极端高温
        elif scenario == 'anomaly':
            base_temp = -50.0  # 异常温度
            
        data = []
        base_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        
        for hour in range(hours):
            for location in locations:
                timestamp = base_time + timedelta(hours=hour)
                
                # 添加日间变化模式
                temp_variation = 5 * np.sin(2 * np.pi * hour / 24)  # 24小时周期
                humidity_variation = 10 * np.sin(2 * np.pi * (hour + 6) / 24)
                
                record = {
                    'timestamp': timestamp,
                    'location': location,
                    'temperature_2m': base_temp + temp_variation + np.random.normal(0, 2),
                    'dew_point_2m': base_temp + temp_variation - 8 + np.random.normal(0, 1),
                    'relative_humidity_2m': max(0, min(100, base_humidity + humidity_variation + np.random.normal(0, 5))),
                    'wind_speed_10m': max(0, base_wind + np.random.normal(0, 3)),
                    'cloud_cover': max(0, min(100, 50 + np.random.normal(0, 20))),
                    'shortwave_radiation': max(0, 800 * max(0, np.sin(np.pi * max(0, hour - 6) / 12)) + np.random.normal(0, 50))
                }
                
                # 异常场景特殊处理
                if scenario == 'anomaly' and hour == 12:
                    record['temperature_2m'] = 100.0  # 异常高温
                    record['relative_humidity_2m'] = 150  # 异常湿度
                    
                data.append(record)
                
        return pd.DataFrame(data)
    
    @staticmethod
    def generate_historical_load_data(hours: int = 168) -> pd.DataFrame:
        """生成历史负荷数据
        
        Args:
            hours: 小时数(默认7天)
            
        Returns:
            pd.DataFrame: 历史负荷数据
        """
        data = []
        base_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours)
        base_load = 10000  # 基础负荷 10000MW
        
        for hour in range(hours):
            timestamp = base_time + timedelta(hours=hour)
            
            # 负荷模式: 工作日/周末 + 日间变化 + 随机波动
            is_weekend = timestamp.weekday() >= 5
            hour_of_day = timestamp.hour
            
            # 日变化模式
            daily_pattern = 2000 * np.sin(np.pi * (hour_of_day - 6) / 12) if 6 <= hour_of_day <= 18 else -1000
            
            # 周末影响
            weekend_factor = 0.8 if is_weekend else 1.0
            
            # 随机波动
            random_noise = np.random.normal(0, 200)
            
            load = (base_load + daily_pattern) * weekend_factor + random_noise
            load = max(1000, load)  # 确保最小负荷值
            
            data.append({
                'timestamp': timestamp,
                'System_Load': load
            })
            
        return pd.DataFrame(data)
    
    @staticmethod
    def generate_model_predictions() -> dict:
        """生成模型预测结果模拟数据"""
        hours = 24
        base_time = datetime.now(timezone.utc)
        
        predictions = []
        for hour in range(hours):
            timestamp = base_time + timedelta(hours=hour)
            load = 10000 + 2000 * np.sin(np.pi * max(0, hour - 6) / 12) + np.random.normal(0, 100)
            pv = max(0, 500 * np.sin(np.pi * max(0, hour - 6) / 12))
            
            predictions.append({
                'hour': hour,
                'timestamp': timestamp.isoformat(),
                'load_forecast_mw': round(load, 1),
                'pv_estimation_mw': round(pv, 1),
                'net_load_mw': round(load - pv, 1)
            })
            
        return {
            'status': 'success',
            'predictions': predictions,
            'model_info': [
                {'name': 'EnhancedLSTM', 'weight': 0.35, 'num_params': 1234567, 'loaded': True},
                {'name': 'BiGRU', 'weight': 0.30, 'num_params': 987654, 'loaded': True},
                {'name': 'DeepTCN', 'weight': 0.20, 'num_params': 765432, 'loaded': True},
                {'name': 'SpatialTransformer', 'weight': 0.15, 'num_params': 2345678, 'loaded': True},
            ],
            'ensemble_weights': {
                'EnhancedLSTM': 0.35,
                'BiGRU': 0.30,
                'DeepTCN': 0.20,
                'SpatialTransformer': 0.15
            },
            'inference_time_ms': 150.5,
            'data_source': 'test',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }


# =================================================================================
# 测试夹具 (Fixtures)
# =================================================================================

@pytest.fixture
def test_data_generator():
    """测试数据生成器夹具"""
    return TestDataGenerator()


@pytest.fixture
def sample_weather_data():
    """正常场景气象数据"""
    return TestDataGenerator.generate_weather_data(hours=24, scenario='normal')


@pytest.fixture
def extreme_weather_data():
    """极端条件气象数据"""
    return TestDataGenerator.generate_weather_data(hours=24, scenario='extreme')


@pytest.fixture
def anomaly_weather_data():
    """异常数据场景"""
    return TestDataGenerator.generate_weather_data(hours=24, scenario='anomaly')


@pytest.fixture
def historical_load_data():
    """历史负荷数据"""
    return TestDataGenerator.generate_historical_load_data(hours=168)


@pytest.fixture
def mock_openmeteo_client():
    """模拟OpenMeteo客户端"""
    with patch('realtime_api.openmeteo_client.OpenMeteoClient') as mock:
        mock_instance = Mock()
        mock_instance.fetch_weather_data.return_value = (
            TestDataGenerator.generate_weather_data(hours=24),
            {'data_quality': 'good', 'sources': 6}
        )
        mock.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_model_inference():
    """模拟模型推理服务"""
    with patch('realtime_api.prediction_service.ModelInferenceService') as mock:
        mock_instance = Mock()
        
        # 模拟预测结果
        mock_prediction_result = Mock(spec=PredictionResult)
        mock_prediction_result.ensemble_prediction = np.array([9500 + i*100 for i in range(24)])
        mock_prediction_result.model_predictions = {
            'EnhancedLSTM': np.array([9400 + i*90 for i in range(24)]),
            'BiGRU': np.array([9600 + i*110 for i in range(24)]),
            'DeepTCN': np.array([9300 + i*95 for i in range(24)]),
            'SpatialTransformer': np.array([9700 + i*105 for i in range(24)])
        }
        mock_prediction_result.confidence_intervals = {
            'lower': mock_prediction_result.ensemble_prediction * 0.95,
            'upper': mock_prediction_result.ensemble_prediction * 1.05
        }
        
        mock_instance.predict.return_value = mock_prediction_result
        mock_instance.ensemble_weights = {
            'EnhancedLSTM': 0.35,
            'BiGRU': 0.30, 
            'DeepTCN': 0.20,
            'SpatialTransformer': 0.15
        }
        mock_instance.get_model_info.return_value = {
            'EnhancedLSTM': {'weight': 0.35, 'num_params': 1234567, 'loaded': True},
            'BiGRU': {'weight': 0.30, 'num_params': 987654, 'loaded': True},
            'DeepTCN': {'weight': 0.20, 'num_params': 765432, 'loaded': True},
            'SpatialTransformer': {'weight': 0.15, 'num_params': 2345678, 'loaded': True}
        }
        mock_instance.is_ready.return_value = True
        
        mock.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def weather_validator():
    """气象数据验证器实例"""
    return WeatherDataValidator()


@pytest.fixture
def feature_generator():
    """特征生成器实例"""
    # 创建临时目录用于测试
    temp_dir = tempfile.mkdtemp()
    yield FeatureGenerator()
    # 清理临时目录
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def normalization_adapter():
    """归一化适配器实例"""
    temp_dir = tempfile.mkdtemp()
    yield NormalizationAdapter()
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def solar_estimator():
    """光伏发电估算器实例"""
    return SolarEstimator(installed_capacity_mw=500.0, performance_ratio=0.8)


@pytest.fixture
def net_load_calculator():
    """净负荷计算器实例"""
    return NetLoadCalculator()


@pytest.fixture
def monitoring_service():
    """监控服务实例"""
    return MonitoringService()


@pytest.fixture
def test_temp_dir():
    """临时测试目录"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_api_response():
    """模拟API响应"""
    return {
        'status': 'success',
        'data': {'temperature': 25.0, 'humidity': 60},
        'timestamp': datetime.now(timezone.utc).isoformat()
    }


# =================================================================================
# 测试配置
# =================================================================================

def pytest_configure(config):
    """pytest配置"""
    config.addinivalue_line(
        "markers", "unit: 单元测试"
    )
    config.addinivalue_line(
        "markers", "integration: 集成测试" 
    )
    config.addinivalue_line(
        "markers", "e2e: 端到端测试"
    )
    config.addinivalue_line(
        "markers", "performance: 性能测试"
    )
    config.addinivalue_line(
        "markers", "exception: 异常测试"
    )


# =================================================================================
# 测试工具函数
# =================================================================================

def create_test_csv_file(temp_dir: str, filename: str, data: list) -> str:
    """创建测试CSV文件"""
    filepath = os.path.join(temp_dir, filename)
    df = pd.DataFrame(data)
    df.to_csv(filepath, index=False)
    return filepath


def create_test_pickle_file(temp_dir: str, filename: str, data: object) -> str:
    """创建测试pickle文件"""
    filepath = os.path.join(temp_dir, filename)
    pd.to_pickle(data, filepath)
    return filepath


def assert_dataframe_structure(df: pd.DataFrame, required_columns: list, test_name: str = ""):
    """验证DataFrame结构"""
    assert isinstance(df, pd.DataFrame), f"{test_name}: 期望DataFrame对象"
    for col in required_columns:
        assert col in df.columns, f"{test_name}: 缺少必需列 '{col}'"


def assert_response_structure(response: dict, required_fields: list, test_name: str = ""):
    """验证响应结构"""
    assert isinstance(response, dict), f"{test_name}: 期望字典响应"
    for field in required_fields:
        assert field in response, f"{test_name}: 缺少必需字段 '{field}'"


def generate_random_string(length: int = 10) -> str:
    """生成随机字符串"""
    import random
    import string
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def simulate_api_error(status_code: int, message: str) -> Mock:
    """模拟API错误响应"""
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.json.return_value = {'error': message, 'status': 'error'}
    mock_response.raise_for_status.side_effect = Exception(f"HTTP {status_code}: {message}")
    return mock_response


class TestHelpers:
    """测试辅助工具类"""
    
    @staticmethod
    def wait_for_condition(condition_func, timeout: float = 5.0, interval: float = 0.1):
        """等待条件满足"""
        import time
        start_time = time.time()
        while time.time() - start_time < timeout:
            if condition_func():
                return True
            time.sleep(interval)
        return False
    
    @staticmethod
    def measure_execution_time(func, *args, **kwargs):
        """测量函数执行时间"""
        import time
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        return result, end_time - start_time
    
    @staticmethod
    def generate_correlation_matrix(size: int) -> np.ndarray:
        """生成相关性矩阵用于测试"""
        A = np.random.randn(size, size)
        return np.corrcoef(A)
    
    @staticmethod
    def simulate_memory_usage(size_mb: int) -> np.ndarray:
        """模拟内存使用"""
        return np.random.rand(int(size_mb * 1024 * 1024 / 8))  # 8 bytes per float64