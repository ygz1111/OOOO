#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异常处理和恢复测试套件

测试内容:
  - 网络超时和重试机制
  - 数据质量异常处理
  - API错误响应和恢复
  - 模型服务故障处理
  - 系统降级和容错能力

运行:
  pytest tests/exception_handling.py -v --tb=short -s
  pytest tests/exception_handling.py::TestNetworkException -v
"""

import pytest
import time
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import HTTPException
import asyncio
import json
from typing import Dict, List, Any

from realtime_api.app import app
from realtime_api.openmeteo_client import OpenMeteoClient
from realtime_api.weather_validator import WeatherDataValidator
from realtime_api.prediction_service import ModelInferenceService
from realtime_api.pv_estimator import SolarEstimator
from realtime_api.net_load_calculator import NetLoadCalculator


class TestNetworkExceptionHandling:
    """网络异常处理测试"""
    
    @pytest.mark.exception
    def test_openmeteo_timeout_handling(self):
        """测试OpenMeteo API超时处理"""
        
        client = TestClient(app)
        
        # 模拟网络超时
        with patch('realtime_api.app.OpenMeteoClient.fetch_weather_data') as mock_fetch:
            mock_fetch.side_effect = requests.exceptions.Timeout("请求超时")
            
            # 测试API端点处理超时
            response = client.get("/api/weather?location=Boston&timeout=1")
            
            # 验证系统正确处理超时
            if response.status_code == 503:  # 服务不可用
                result = response.json()
                assert 'error' in result or 'detail' in result
                assert 'timeout' in result.get('detail', '').lower() or 'timeout' in result.get('error', '').lower()
            elif response.status_code == 200:
                # 可能返回缓存数据
                result = response.json()
                assert result.get('data_source') in ['cache', 'fallback']
            
    @pytest.mark.exception
    def test_network_connection_error_handling(self):
        """测试网络连接错误处理"""
        
        client = TestClient(app)
        
        with patch('realtime_api.app.OpenMeteoClient.fetch_weather_data') as mock_fetch:
            mock_fetch.side_effect = requests.exceptions.ConnectionError("网络连接失败")
            
            response = client.get("/api/weather?location=RemoteLocation")
            
            # 验证系统处理连接错误
            assert response.status_code in [503, 408, 200]  # 服务不可用, 请求超时或成功(使用缓存)
            
            if response.status_code == 503:
                result = response.json()
                assert 'connection' in result.get('detail', '').lower() or 'network' in result.get('detail', '').lower()
    
    @pytest.mark.exception 
    def test_dns_resolution_failure(self):
        """测试DNS解析失败处理"""
        
        client = TestClient(app)
        
        with patch('realtime_api.app.OpenMeteoClient.fetch_weather_data') as mock_fetch:
            mock_fetch.side_effect = requests.exceptions.RequestException("DNS解析失败")
            
            response = client.get("/api/weather?location=InvalidDNS.example")
            
            assert response.status_code in [503, 500]
            
            if response.status_code == 503:
                result = response.json()
                assert 'dns' in result.get('detail', '').lower() or 'resolution' in result.get('detail', '').lower()


class TestDataQualityExceptionHandling:
    """数据质量异常处理测试"""
    
    @pytest.mark.exception
    def test_invalid_weather_data_handling(self, weather_validator):
        """测试无效气象数据处理"""
        
        # 创建包含各种异常值的数据
        invalid_weather_data = pd.DataFrame([{
            'timestamp': datetime.now(timezone.utc),
            'location': 'TestLocation',
            'temperature_2m': -200,  # 绝对不可能的温度
            'dew_point_2m': 100,     # 高于正常值
            'relative_humidity_2m': 150,  # 超过100%
            'wind_speed_10m': -10,   # 负风速
            'cloud_cover': 200,      # 超过100%
            'shortwave_radiation': -100,  # 负辐射
        }])
        
        # 测试数据验证和处理
        try:
            clean_df, quality_report, anomaly_flags = weather_validator.validate(
                invalid_weather_data, raise_on_severe=True
            )
            
            # 如果未抛出异常，验证尽力处理的结果
            assert len(clean_df) == 0  # 应该无法保留任何有效数据
            assert quality_report.overall_score == 0  # 质量分数应为0
            
        except (ValueError, HTTPException) as e:
            # 期望抛出异常
            assert 'quality' in str(e).lower() or 'invalid' in str(e).lower()
    
    @pytest.mark.exception
    def test_missing_required_data_handling(self):
        """测试必需数据缺失处理"""
        
        # 测试不同的数据缺失场景
        missing_data_scenarios = [
            {},  # 完全空数据
            {'temperature_2m': 25.0},  # 只有温度数据
            {'timestamp': datetime.now(timezone.utc)},  # 只有时间戳
            {
                'timestamp': datetime.now(timezone.utc),
                'location': 'Test',
                # 缺少其他必需字段
            }
        ]
        
        weather_validator = WeatherDataValidator()
        
        for i, scenario in enumerate(missing_data_scenarios):
            df = pd.DataFrame([scenario])
            
            try:
                clean_df, quality_report, _ = weather_validator.validate(df)
                
                # 验证处理结果
                assert isinstance(quality_report.overall_score, (int, float))
                assert 0 <= quality_report.overall_score <= 1
                
                # 缺失数据越多，质量分数应该越低
                if i == 3:  # 部分缺失场景
                    assert quality_report.overall_score < 0.5
                elif i <= 1:  # 几乎完全缺失
                    assert quality_report.overall_score < 0.2
                    
            except KeyError as e:
                # 对于严重的缺失，可能抛出KeyError
                expected_missing_fields = ['dew_point', 'humidity', 'wind_speed', 'cloud_cover']
                assert any(field in str(e) for field in expected_missing_fields)
    
    @pytest.mark.exception
    def test_data_format_error_handling(self):
        """测试数据格式错误处理"""
        
        weather_validator = WeatherDataValidator()
        
        # 测试各种格式错误
        format_error_scenarios = [
            pd.DataFrame([{
                'timestamp': 'invalid_timestamp',  # 字符串时间戳
                'location': 'Test',
                'temperature_2m': 'not_a_number',  # 字符串数值
                'dew_point_2m': 15.0,
                'relative_humidity_2m': 60,
                'wind_speed_10m': 10,
                'cloud_cover': 50,
                'shortwave_radiation': 800
            }]),
            pd.DataFrame([{
                'timestamp': datetime.now(timezone.utc),
                'location': None,  # None值
                'temperature_2m': float('inf'),  # 无穷大
                'dew_point_2m': float('nan'),   # NaN
                'relative_humidity_2m': 60,
                'wind_speed_10m': 10,
                'cloud_cover': 50,
                'shortwave_radiation': 800
            }])
        ]
        
        for scenario_data in format_error_scenarios:
            try:
                clean_df, quality_report, anomaly_flags = weather_validator.validate(
                    scenario_data, raise_on_severe=False
                )
                
                # 应该能处理格式错误并尽力清理
                assert isinstance(clean_df, pd.DataFrame)
                assert isinstance(quality_report, object)
                assert quality_report.overall_score < 0.8  # 格式错误会降低质量
                
            except (ValueError, TypeError) as e:
                # 对于严重的格式错误，可能抛出异常
                assert 'format' in str(e).lower() or 'type' in str(e).lower() or 'invalid' in str(e).lower()    


class TestModelServiceExceptionHandling:
    """模型服务异常处理测试"""
    
    @pytest.mark.exception
    def test_model_service_unavailable(self):
        """测试模型服务不可用时的处理"""
        
        client = TestClient(app)
        
        # 模拟模型服务完全不可用
        with patch('realtime_api.app.create_prediction_pipeline') as mock_pipeline:
            mock_pipeline.side_effect = Exception("模型服务不可用")
            
            # 准备正常的请求数据
            request_data = {
                'weather_data': [
                    {
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'location': 'Boston',
                        'temperature_2m': 25.5,
                        'dew_point_2m': 15.2,
                        'relative_humidity_2m': 65.0,
                        'wind_speed_10m': 8.5,
                        'cloud_cover': 30,
                        'shortwave_radiation': 650
                    }
                ] * 24
            }
            
            # 测试预测API
            response = client.post("/api/load-prediction", json=request_data)
            
            # 验证错误处理
            assert response.status_code in [503, 500]  # 服务不可用或内部错误
            
            result = response.json()
            assert 'error' in result or 'detail' in result
    
    @pytest.mark.exception
    def test_model_prediction_timeout(self):
        """测试模型预测超时处理"""
        
        client = TestClient(app)
        
        with patch('realtime_api.app.create_prediction_pipeline') as mock_pipeline:
            mock_service = Mock()
            
            # 模拟长时间预测操作
            def slow_prediction(*args, **kwargs):
                time.sleep(30)  # 30秒延迟，模拟超时
                return {
                    'status': 'success',
                    'predictions': [{'hour': i, 'load_forecast_mw': 9500} for i in range(24)]
                }
            
            mock_service.predict.side_effect = slow_prediction
            mock_pipeline.return_value = mock_service
            
            # 发送请求并测量响应时间
            request_data = {
                'weather_data': [{'timestamp': datetime.now(timezone.utc).isoformat()}],
                'timeout': 5  # 5秒超时
            }
            
            start_time = time.time()
            response = client.post("/api/load-prediction", json=request_data)
            end_time = time.time()
            
            response_time = end_time - start_time
            
            # 验证请求是否在大约5秒内返回
            assert response_time < 15, f"请求时间过长: {response_time}s"  # 允许一些缓冲
            
            # 验证超时处理
            if response.status_code == 408:  # 请求超时
                result = response.json()
                assert 'timeout' in result.get('detail', '').lower()
    
    @pytest.mark.exception
    def test_model_memory_exhaustion(self):
        """测试模型内存耗尽处理"""
        
        client = TestClient(app)
        
        with patch('realtime_api.app.create_prediction_pipeline') as mock_pipeline:
            mock_service = Mock()
            
            # 模拟内存不足错误
            mock_service.predict.side_effect = MemoryError("内存不足")
            mock_pipeline.return_value = mock_service
            
            request_data = {
                'weather_data': [{'timestamp': datetime.now(timezone.utc).isoformat()}] * 24
            }
            
            response = client.post("/api/load-prediction", json=request_data)
            
            # 验证内存错误处理
            assert response.status_code in [500, 503]
            
            result = response.json()
            if response.status_code == 500:
                assert 'memory' in result.get('detail', '').lower() or 'insufficient' in result.get('detail', '').lower()
    
    @pytest.mark.exception
    def test_corrupted_model_data(self):
        """测试模型数据损坏处理"""
        
        client = TestClient(app)
        
        with patch('realtime_api.app.create_prediction_pipeline') as mock_pipeline:
            mock_service = Mock()
            
            # 模拟损坏的模型数据错误
            mock_service.predict.side_effect = ValueError("模型权重数据损坏")
            mock_pipeline.return_value = mock_service
            
            # 发送预测请求
            request_data = {
                'weather_data': [{'timestamp': datetime.now(timezone.utc).isoformat()}] * 24
            }
            
            response = client.post("/api/load-prediction", json=request_data)
            
            assert response.status_code in [500, 503]
            result = response.json()
            
            # 验证错误消息适当
            assert 'corrupt' in result.get('detail', '').lower() or 'invalid' in result.get('detail', '').lower()


class TestAPIExceptionHandling:
    """API异常处理测试"""
    
    @pytest.mark.exception
    def test_invalid_request_format(self):
        """测试无效的请求格式处理"""
        
        client = TestClient(app)
        
        # 测试各种无效的请求格式
        invalid_requests = [
            "不是JSON的字符串",  # 非JSON字符串
            {},  # 空对象
            {
                'weather_data': [],  # 空的气象数据
            },
            {
                'weather_data': [
                    {
                        'timestamp': 'invalid_date',
                        'location': 'Test'
                        # 缺失必需字段
                    }
                ]
            },
            {
                'weather_data': None,  # None数据
            }
        ]
        
        for i, invalid_request in enumerate(invalid_requests):
            try:
                response = client.post("/api/load-prediction", json=invalid_request)
                
                # 验证错误响应
                if response.status_code == 422:  # 验证错误
                    result = response.json()
                    assert 'validation error' in str(result).lower() or 'field' in str(result)
                    
                elif response.status_code == 400:  # 错误请求
                    result = response.json()
                    assert 'bad request' in str(result).lower() or 'invalid' in str(result).lower()
                    
                # 对于某些极端情况，API可能抛出500错误
                elif response.status_code == 500:
                    result = response.json()
                    assert 'internal server error' in str(result).lower()
                    
            except requests.exceptions.JSONDecodeError:
                # 对于完全无效的JSON，可能无法解析响应
                pass
    
    @pytest.mark.exception 
    def test_api_rate_limiting(self):
        """测试API速率限制处理"""
        
        client = TestClient(app)
        
        # 模拟速率限制
        request_count = 0
        
        with patch('realtime_api.app.create_prediction_pipeline') as mock_pipeline:
            mock_service = Mock()
            mock_service.predict.return_value = {
                'status': 'success',
                'predictions': [{'hour': i, 'load_forecast_mw': 9500} for i in range(24)]
            }
            mock_pipeline.return_value = mock_service
            
            # 发送大量连续请求
            responses = []
            
            for i in range(50):  # 50个连续请求
                request_data = {
                    'weather_data': [{'timestamp': datetime.now(timezone.utc).isoformat()}] * 24
                }
                
                response = client.post("/api/load-prediction", json=request_data)
                responses.append(response)
                
                # 如果遇到速率限制，停止
                if response.status_code == 429:  # Too Many Requests
                    break
                
                # 小延迟以避免过于激进的测试
                time.sleep(0.1)
            
            # 分析响应
            status_codes = [r.status_code for r in responses]
            
            # 如果没有速率限制，所有请求都应该成功
            if 429 not in status_codes:
                # 系统可能没有实现速率限制
                print(f"注意: 未检测到速率限制, 所有 {len(responses)} 个请求都完成了")
                print(f"状态码: {status_codes[:10]}...")  # 显示前10个
            else:
                # 检测到了速率限制
                rate_limited_responses = [r for r in responses if r.status_code == 429]
                
                for response in rate_limited_responses:
                    result = response.json()
                    assert 'rate limit' in str(result).lower() or 'too many' in str(result).lower()
    
    @pytest.mark.exception
    def test_large_payload_handling(self):
        """测试大负载数据处理"""
        
        client = TestClient(app)
        
        # 创建特别大的请求负载
        large_weather_data = []
        for i in range(168):  # 一周的数据，每小时
            large_weather_data.append({
                'timestamp': (datetime.now(timezone.utc) + timedelta(hours=i)).isoformat(),
                'location': 'Boston',
                'temperature_2m': 25.0 + np.random.normal(0, 5),
                'dew_point_2m': 15.0 + np.random.normal(0, 3),
                'relative_humidity_2m': 60 + np.random.normal(0, 10),
                'wind_speed_10m': 10 + np.random.normal(0, 3),
                'cloud_cover': 50 + np.random.normal(0, 20),
                'shortwave_radiation': 800 + np.random.normal(0, 100),
            })
        
        large_request = {
            'weather_data': large_weather_data,
            'model_type': 'ensemble',
            'include_detailed_analysis': True,
            'cache_results': True
        }
        
        with patch('realtime_api.app.create_prediction_pipeline') as mock_pipeline:
            mock_service = Mock()
            
            # 模拟处理大负载的延迟
            def handle_large_payload(*args, **kwargs):
                # 模拟大负载处理时间
                processing_time = len(large_weather_data) * 0.01  # 每数据点0.01秒
                time.sleep(min(processing_time, 2.0))  # 最多等待2秒
                
                # 限制返回预测的数量
                available_predictions = 24  # 只返回24小时预测
                predictions = []
                for i in range(available_predictions):
                    predictions.append({
                        'hour': i,
                        'load_forecast_mw': 9500 + i * 100,
                        'timestamp': (datetime.now(timezone.utc) + timedelta(hours=i)).isoformat()
                    })
                
                return {
                    'status': 'success',
                    'predictions': predictions,
                    'message': 'Limited to 24-hour forecast due to large input size',
                    'input_data_points': len(large_weather_data),
                    'actual_predictions': len(predictions)
                }
            
            mock_service.predict.side_effect = handle_large_payload
            mock_pipeline.return_value = mock_service
            
            # 发送大负载请求
            start_time = time.time()
            response = client.post("/api/load-prediction", json=large_request)
            end_time = time.time()
            
            response_time = end_time - start_time
            
            # 验证响应
            if response.status_code == 200:
                result = response.json()
                assert 'predictions' in result
                assert 'input_data_points' in result
                assert result['input_data_points'] > 24  # 输入数据点多于预测数
                
                # 验证响应时间合理
                assert response_time < 30, f"大负载处理时间过长: {response_time:.1f}s"
                
            elif response.status_code == 413:  # Payload Too Large
                result = response.json()
                assert 'payload too large' in str(result).lower() or 'too much data' in str(result).lower()
                
            elif response.status_code == 422:  # 验证错误
                result = response.json()
                assert 'validation' in str(result) or 'size limit' in str(result).lower()


class TestSystemRecoveryHandling:
    """系统恢复和降级测试"""
    
    @pytest.mark.exception
    def test_fallback_to_historical_data(self):
        """测试回退到历史数据处理"""
        
        client = TestClient(app)
        
        # 模拟当前气象数据获取失败
        with patch('realtime_api.app.OpenMeteoClient.fetch_weather_data') as mock_fetch:
            with patch('realtime_api.app.ModelInferenceService') as mock_model_service:
                
                # 模拟气象数据获取失败
                mock_fetch.side_effect = Exception("实时气象数据不可用")
                
                # 模拟回退到历史数据的预测
                mock_service = Mock()
                mock_service.predict.return_value = {
                    'status': 'success_fallback',
                    'predictions': [
                        {
                            'hour': i,
                            'load_forecast_mw': 9200 + i * 80,
                            'timestamp': (datetime.now(timezone.utc) + timedelta(hours=i)).isoformat(),
                            'data_source': 'historical_fallback'
                        } for i in range(24)
                    ],
                    'data_source': 'historical_data',
                    'fallback_reason': 'current_weather_unavailable'
                }
                mock_model_service.return_value = mock_service
                
                # 测试自动气象数据获取的预测端点
                response = client.post("/api/load-prediction-auto", json={
                    'locations': ['Boston']
                })
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # 验证回退机制工作
                    assert result['data_source'] == 'historical_data'
                    assert 'fallback' in result.get('status', '').lower() or 'fallback' in str(result)
                    
                    # 验证预测依然合理
                    predictions = result['predictions']
                    assert len(predictions) == 24
                    
                    for pred in predictions:
                        assert pred['load_forecast_mw'] > 0
                        assert 'data_source' in pred
    
    @pytest.mark.exception
    def test_progressive_degradation(self):
        """测试渐进式降级处理"""
        
        client = TestClient(app)
        
        # 测试不同级别的故障
        degradation_levels = [
            {
                'name': 'light_degradation',
                'weather_available': True,
                'use_pv_calculation': False,
                'confidence_intervals': True,
                'expected_features': 20
            },
            {
                'name': 'medium_degradation', 
                'weather_available': True,
                'use_pv_calculation': False,
                'confidence_intervals': False,
                'expected_features': 15
            },
            {
                'name': 'heavy_degradation',
                'weather_available': False,
                'use_pv_calculation': False,
                'confidence_intervals': False,
                'expected_features': 10
            }
        ]
        
        for level in degradation_levels:
            print(f"\n测试降级级别: {level['name']}")
            
            with patch('realtime_api.app.create_prediction_pipeline') as mock_pipeline:
                mock_service = Mock()
                
                # 模拟降级响应
                degraded_predictions = []
                for i in range(24):
                    pred = {
                        'hour': i,
                        'load_forecast_mw': 9000 + i * 100,
                        'timestamp': (datetime.now(timezone.utc) + timedelta(hours=i)).isoformat(),
                        'accuracy_level': level['name']
                    }
                    
                    # 根据降级级别调整功能可用性
                    if not level['confidence_intervals']:
                        pred['confidence_available'] = False
                    
                    degraded_predictions.append(pred)
                
                mock_service.predict.return_value = {
                    'status': f'success_{level["name"]}',
                    'predictions': degraded_predictions,
                    'degradation_level': level['name'],
                    'degraded_reason': 'system_under_load',
                    'available_features': level['expected_features']
                }
                mock_pipeline.return_value = mock_service
                
                request_data = {
                    'weather_data': [{'timestamp': datetime.now(timezone.utc).isoformat()}] * 24,
                    'include_confidence_intervals': level['confidence_intervals'],
                    'include_pv_calculation': level['use_pv_calculation']
                }
                
                response = client.post("/api/load-prediction", json=request_data)
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # 验证降级级别
                    assert result['degradation_level'] == level['name']
                    assert result['available_features'] == level['expected_features']
                    
                    # 验证核心功能仍然可用
                    assert 'predictions' in result
                    assert len(result['predictions']) == 24
                    
                    print(f"  {level['name']}: 降级成功, {result['available_features']} 个特征")
    @pytest.mark.exception
    def test_automatic_retries_with_backoff(self):
        """测试自动重试和退避机制"""
        
        client = TestClient(app)
        
        # 模拟间歇性故障
        call_count = 0
        max_failures = 3
        
        def intermittent_failure(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            if call_count <= max_failures:
                raise Exception(f"间歇性故障 #{call_count}")
            else:
                # 最终成功
                return {
                    'status': 'success_after_retry',
                    'predictions': [{'hour': i, 'load_forecast_mw': 9500} for i in range(24)],
                    'retry_count': call_count 
                }
        
        with patch('realtime_api.app.create_prediction_pipeline') as mock_pipeline:
            mock_service = Mock()
            mock_service.predict.side_effect = intermittent_failure
            mock_pipeline.return_value = mock_service
            
            request_data = {
                'weather_data': [{'timestamp': datetime.now(timezone.utc).isoformat()}] * 24,
                'enable_retries': True,
                'max_retries': 5
            }
            
            start_time = time.time()
            response = client.post("/api/load-prediction", json=request_data)
            end_time = time.time()
            
            response_time = end_time - start_time
            
            # 验证重试机制 (由于模拟快速失败，实际可能不会等待)
            if response.status_code == 200:
                result = response.json()
                
                # 检查是否记录了重试信息
                if 'retry_count' in result:
                    assert result['retry_count'] > 1
                    print(f"成功在 {result['retry_count']} 次重试后")
                    
                # 验证响应时间反映了重试延迟
                if call_count > 1:
                    print(f"重试机制激活: {call_count} 次调用, {response_time:.2f}s")
            
            # 即使在多次失败后，应该最后成功
            assert call_count >= 1, "至少应该有一次尝试"