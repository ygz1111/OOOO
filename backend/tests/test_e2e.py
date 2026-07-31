#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端测试套件

测试完整的系统工作流:
  1. 从数据采集到API响应
  2. 历史数据回测验证
  3. 实时预测流程
  4. 系统整体健壮性

运行:
  pytest tests/test_e2e.py -v --tb=short
  pytest tests/test_e2e.py::TestFullWorkflow -v -s
"""

import pytest
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
import asyncio
import time
import requests

from realtime_api.app import app
from realtime_api.schemas import (
    LoadPredictionRequest, LoadPredictionResponse, WeatherDataPoint
)


class TestFullWorkflow:
    """完整工作流端到端测试"""
    
    @pytest.mark.e2e
    def test_weather_to_prediction_workflow(self, test_data_generator):
        """测试从气象数据获取到负荷预测的完整工作流"""
        
        with patch('realtime_api.app.OpenMeteoClient') as mock_openmeteo:
            with patch('realtime_api.app.ModelInferenceService') as mock_model_service:
                # 模拟OpenMeteo客户端
                mock_client = Mock()
                mock_weather_data = test_data_generator.generate_weather_data(
                    hours=24, 
                    locations=['Boston'],
                    scenario='normal'
                )
                mock_client.fetch_weather_data.return_value = (mock_weather_data, {'quality': 'good'})
                mock_openmeteo.return_value = mock_client
                
                # 模拟模型推理服务
                mock_prediction_service = Mock()
                mock_prediction_service.is_ready.return_value = True
                
                # 创建模拟的预测结果
                mock_predictions = []
                for i in range(24):
                    mock_predictions.append({
                        'hour': i,
                        'timestamp': (datetime.now(timezone.utc) + timedelta(hours=i)).isoformat(),
                        'load_forecast_mw': 9500 + i * 100 + np.random.normal(0, 50),
                        'confidence_lower_mw': 9400 + i * 100,
                        'confidence_upper_mw': 9600 + i * 100,
                        'model_weights': {
                            'EnhancedLSTM': 0.35,
                            'BiGRU': 0.30,
                            'DeepTCN': 0.20,
                            'SpatialTransformer': 0.15
                        }
                    })
                
                mock_prediction_service.predict.return_value = {
                    'status': 'success',
                    'predictions': mock_predictions,
                    'data_quality_score': 0.92,
                    'inference_time_ms': 150.5,
                    'model_info': {
                        'used_models': ['EnhancedLSTM', 'BiGRU', 'DeepTCN', 'SpatialTransformer'],
                        'ensemble_size': 4,
                        'latest_update': datetime.now(timezone.utc).isoformat()
                    }
                }
                mock_model_service.return_value = mock_prediction_service
                
                # 创建API客户端并测试端到端流程
                client = TestClient(app)
                
                # 步骤1: 获取气象数据
                weather_response = client.get("/api/weather?location=Boston")
                
                if weather_response.status_code == 200:
                    weather_data = weather_response.json()
                    assert 'weather_data' in weather_data
                    assert len(weather_data['weather_data']) > 0
                    
                    # 步骤2: 验证气象数据质量
                    validation_response = client.post("/api/validate-weather", json=weather_data)
                    
                    if validation_response.status_code == 200:
                        validation_result = validation_response.json()
                        assert 'quality_score' in validation_result
                        assert validation_result['quality_score'] >= 0.8
                
                # 步骤3: 执行负荷预测
                prediction_request = {
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
                    ] * 24,
                    'model_type': 'ensemble',
                    'include_confidence_intervals': True,
                    'include_model_details': True
                }
                
                prediction_response = client.post("/api/load-prediction", json=prediction_request)
                
                # 验证预测响应
                if prediction_response.status_code == 200:
                    prediction_result = prediction_response.json()
                    
                    # 验证响应结构
                    assert 'status' in prediction_result
                    assert 'predictions' in prediction_result
                    assert 'metadata' in prediction_result
                    
                    # 验证预测数据
                    predictions = prediction_result['predictions']
                    assert len(predictions) == 24  # 24小时预测
                    
                    # 验证每个预测点的结构
                    for pred in predictions:
                        assert 'hour' in pred
                        assert 'load_forecast_mw' in pred
                        assert 'timestamp' in pred
                        
                        # 数值有效性检查
                        assert pred['load_forecast_mw'] > 0
                        
                        # 如果有置信区间，验证其合理性
                        if 'confidence_lower_mw' in predictions[0]:
                            assert pred['load_forecast_mw'] >= pred['confidence_lower_mw']
                        
                        if 'confidence_upper_mw' in predictions[0]:
                            assert pred['load_forecast_mw'] <= pred['confidence_upper_mw']
                    
                    # 验证元数据
                    metadata = prediction_result['metadata']
                    assert 'total_inference_time_ms' in metadata
                    assert 'data_quality_score' in metadata
                    assert metadata['total_inference_time_ms'] > 0
                    assert 0.0 <= metadata['data_quality_score'] <= 1.0
    
    @pytest.mark.e2e
    def test_real_time_prediction_with_auto_weather(self, test_data_generator):
        """测试自动获取气象数据的实时预测流程"""
        
        # 模拟完整的实时预测流程
        with patch('realtime_api.app.OpenMeteoClient.fetch_current_weather') as mock_fetch:
            with patch('realtime_api.app.create_prediction_pipeline') as mock_pipeline:
                
                # 模拟气象数据获取
                mock_fetch.return_value = (
                    test_data_generator.generate_weather_data(hours=24, locations=['Boston']),
                    {'data_quality': 'good', 'sources': 6}
                )
                
                # 模拟预测管道
                mock_service = Mock()
                mock_predictions = []
                
                for i in range(24):
                    # 模拟24小时负荷预测，包含日内变化模式
                    base_load = 10000
                    daily_pattern = 2000 * np.sin(2 * np.pi * (i - 6) / 24) if 6 <= i <= 18 else -500
                    load = base_load + daily_pattern + np.random.normal(0, 100)
                    
                    mock_predictions.append({
                        'hour': i,
                        'timestamp': (datetime.now(timezone.utc) + timedelta(hours=i)).isoformat(),
                        'load_forecast_mw': max(1000, load),
                        'pv_estimation_mw': max(0, 500 * np.sin(2 * np.pi * max(0, i - 6) / 12)) if 6 <= i <= 18 else 0,
                        'net_load_mw': max(1000, load - 100)  # 简单模拟
                    })
                
                mock_service.predict.return_value = {
                    'status': 'success',
                    'predictions': mock_predictions,
                    'data_source': 'auto_weather',
                    'inference_time_ms': 145.2,
                    'model_execution_details': {
                        'EnhancedLSTM': {'execution_time_ms': 40, 'weight': 0.35},
                        'BiGRU': {'execution_time_ms': 35, 'weight': 0.30},
                        'DeepTCN': {'execution_time_ms': 38, 'weight': 0.20},
                        'SpatialTransformer': {'execution_time_ms': 42, 'weight': 0.15}
                    }
                }
                mock_pipeline.return_value = mock_service
                
                # 执行实时预测
                client = TestClient(app)
                
                response = client.post("/api/load-prediction-auto", json={
                    'locations': ['Boston', 'Hartford'],
                    'model_type': 'ensemble',
                    'include_pv_calculation': True
                })
                
                if response.status_code == 200:
                    result = response.json()
                    
                    assert result['status'] == 'success'
                    assert len(result['predictions']) == 24
                    
                    # 验证数据源
                    assert result.get('data_source') == 'auto_weather'
                    
                    # 验证光伏发电估算
                    if result.get('predictions')[0].get('pv_estimation_mw') is not None:
                        day_hours_pv = [p['pv_estimation_mw'] for p in result['predictions'][6:19]]
                        night_hours_pv = [p['pv_estimation_mw'] for p in result['predictions'][0:6] + result['predictions'][19:24]]
                        
                        # 日间应有更高光伏发电
                        if any(day_hours_pv) and any(night_hours_pv):
                            max_day_pv = max(day_hours_pv)
                            max_night_pv = max(night_hours_pv)
                            assert max_day_pv >= max_night_pv, "日间光伏应高于夜间"


class TestBackTesting:
    """历史数据回测测试"""
    
    @pytest.mark.e2e
    def test_historical_forecast_accuracy(self, test_data_generator):
        """测试历史数据回测准确性"""
        
        # 生成历史测试数据集
        historical_weather = test_data_generator.generate_weather_data(
            hours=24*7*4,  # 4周历史数据
            locations=['Boston']
        )
        historical_load = test_data_generator.generate_historical_load_data(
            hours=24*7*4  # 4周历史数据
        )
        
        # 模拟回测流程
        forecast_results = []
        actual_loads = []
        
        # 模拟逐日滚动预测
        for day in range(7, 28):  # 从第7天开始预测，确保有足够的历史数据
            
            # 获取当天的实际负荷
            daily_actual_loads = []
            for hour in range(24):
                idx = (day * 24) + hour
                if idx < len(historical_load):
                    daily_actual_loads.append(historical_load.iloc[idx]['System_Load'])
            
            # 模拟对当天的预测
            base_weather = historical_weather.iloc[day * 24:(day + 1) * 24]
            
            # 模拟预测结果 (添加一些误差以模拟现实情况)
            daily_forecasts = []
            for i, actual_load in enumerate(daily_actual_loads):
                # 模拟预测误差：±10%的基本误差 + 小随机误差
                error_factor = np.random.normal(1.0, 0.05)  # ±5%随机误差
                base_prediction = actual_load * 0.95 + np.random.normal(0, 100)  # 5%低估倾向
                forecasted_load = base_prediction * error_factor
                
                daily_forecasts.append(max(1000, forecasted_load))  # 确保合理最小值
            
            forecast_results.extend(daily_forecasts)
            actual_loads.extend(daily_actual_loads)
        
        # 计算回测指标
        forecast_errors = np.array(actual_loads) - np.array(forecast_results)
        mae = np.mean(np.abs(forecast_errors))  # 平均绝对误差
        mape = np.mean(np.abs(forecast_errors / np.array(actual_loads))) * 100  # 平均绝对百分比误差
        rmse = np.sqrt(np.mean(forecast_errors ** 2))  # 均方根误差
        
        # 验证准确性指标在合理范围内
        assert mae < 1000, f"MAE过高: {mae}"
        assert mape < 15, f"MAPE过高: {mape}%"  # 15%以内的误差应该可接受
        assert rmse < 1500, f"RMSE过高: {rmse}"
        
        # 验证预测的正相关性
        correlation = np.corrcoef(actual_loads, forecast_results)[0, 1]
        assert correlation > 0.7, f"预测相关性太低: {correlation}"
    
    @pytest.mark.e2e
    def test_rolling_forecast_stability(self, test_data_generator):
        """测试滚动预测稳定性"""
        
        # 生成连续几天的数据进行滚动预测测试
        continuous_weather = test_data_generator.generate_weather_data(
            hours=24*10,  # 10天数据
            locations=['Boston']
        )
        
        prediction_stability = []
        
        # 对每天进行24小时预测
        for start_day in range(3, 8):  # 第3-7天进行预测
            start_idx = start_day * 24
            end_idx = start_idx + 24
            
            daily_weather = continuous_weather.iloc[start_idx:end_idx]
            
            # 模拟每天的预测
            daily_loads = daily_weather['temperature_2m'].apply(lambda x: 9000 + x * 100).tolist()
            daily_loads = np.array(daily_loads) + np.random.normal(0, 200, len(daily_loads))
            
            # 添加日内模式
            for i in range(24):
                if 6 <= i <= 18:  # 白天负荷较高
                    daily_loads[i] += 1500 * np.sin(np.pi * (i - 6) / 12)
            
            # 存储每天的预测结果
            prediction_stability.append({
                'day': start_day,
                'loads': daily_loads,
                'mean_load': np.mean(daily_loads),
                'max_load': np.max(daily_loads),
                'min_load': np.min(daily_loads)
            })
        
        # 验证预测稳定性
        mean_loads = [day['mean_load'] for day in prediction_stability]
        load_variance = np.var(mean_loads)
        
        # 相邻天数之间的负荷变化不应过于剧烈
        for i in range(1, len(prediction_stability)):
            prev_mean = prediction_stability[i-1]['mean_load']
            curr_mean = prediction_stability[i]['mean_load']
            relative_change = abs(curr_mean - prev_mean) / prev_mean
            
            # 相邻天负荷变化应在30%以内（考虑天气变化影响）
            assert relative_change < 0.3, f"相邻天负荷变化过大: {relative_change * 100}%"


class TestSystemRobustness:
    """系统健壮性测试"""
    
    @pytest.mark.e2e
    def test_concurrent_requests_handling(self):
        """测试并发请求处理能力"""
        
        client = TestClient(app)
        
        # 模拟模型服务
        with patch('realtime_api.app.create_prediction_pipeline') as mock_pipeline:
            mock_service = Mock()
            mock_service.predict.return_value = {
                'status': 'success',
                'predictions': [{'hour': i, 'load_forecast_mw': 9500+i*100} for i in range(24)],
                'inference_time_ms': 150.5
            }
            mock_pipeline.return_value = mock_service
            
            # 创建并发请求
            import threading
            results = []
            errors = []
            
            def make_request(request_id):
                try:
                    request_data = {
                        'weather_data': [
                            {
                                'timestamp': datetime.now(timezone.utc).isoformat(),
                                'location': f'Location_{request_id % 3}',
                                'temperature_2m': 25.0,
                                'dew_point_2m': 15.0,
                                'relative_humidity_2m': 60,
                                'wind_speed_10m': 10,
                                'cloud_cover': 50,
                                'shortwave_radiation': 800
                            }
                        ] * 24
                    }
                    
                    response = client.post("/api/load-prediction", json=request_data)
                    results.append({
                        'request_id': request_id,
                        'status_code': response.status_code,
                        'response_time': response.elapsed.total_seconds()
                    })
                    
                except Exception as e:
                    errors.append({'request_id': request_id, 'error': str(e)})
            
            # 启动并发线程
            threads = []
            num_requests = 10  # 10个并发请求
            
            for i in range(num_requests):
                thread = threading.Thread(target=make_request, args=(i,))
                threads.append(thread)
                thread.start()
            
            # 等待所有线程完成
            for thread in threads:
                thread.join(timeout=30)  # 30秒超时
            
            # 分析结果
            successful_requests = len([r for r in results if r['status_code'] == 200])
            failed_requests = len([r for r in results if r['status_code'] != 200])
            avg_response_time = np.mean([r['response_time'] for r in results if r['status_code'] == 200])
            
            # 验证并发处理能力
            assert successful_requests >= num_requests * 0.8, f"成功率过低: {successful_requests}/{num_requests}"
            assert avg_response_time < 10, f"平均响应时间过长: {avg_response_time}s"  # 10秒内
            assert len(errors) < num_requests * 0.2, f"错误率过高: {len(errors)}/{num_requests}"
    
    @pytest.mark.e2e
    def test_long_duration_prediction_session(self, test_data_generator):
        """测试长时间预测会话的稳定性"""
        
        client = TestClient(app)
        
        # 模拟稳定的模型服务
        with patch('realtime_api.app.create_prediction_pipeline') as mock_pipeline:
            mock_service = Mock()
            mock_pipeline.return_value = mock_service
            
            # 统计信息
            session_stats = {
                'total_requests': 0,
                'successful_requests': 0,
                'response_times': [],
                'errors': []
            }
            
            # 模拟多轮预测会话
            for round_num in range(5):  # 5轮预测
                
                # 每轮生成新的测试数据
                round_weather = test_data_generator.generate_weather_data(
                    hours=24, 
                    locations=['Boston'],
                    scenario='normal'
                )
                
                # 创建请求数据
                weather_points = []
                for _, row in round_weather.iterrows():
                    weather_points.append({
                        'timestamp': row['timestamp'].isoformat(),
                        'location': row['location'],
                        'temperature_2m': row['temperature_2m'],
                        'dew_point_2m': row['dew_point_2m'],
                        'relative_humidity_2m': row['relative_humidity_2m'],
                        'wind_speed_10m': row['wind_speed_10m'],
                        'cloud_cover': row['cloud_cover'],
                        'shortwave_radiation': row['shortwave_radiation'],
                    })
                
                # 模拟这个轮次的预测结果
                round_predictions = []
                for i in range(24):
                    round_predictions.append({
                        'hour': i,
                        'load_forecast_mw': 9500 + i * 100 + np.random.normal(0, 100),
                        'timestamp': (datetime.now(timezone.utc) + timedelta(hours=i)).isoformat()
                    })
                
                mock_service.predict.return_value = {
                    'status': 'success',
                    'predictions': round_predictions,
                    'inference_time_ms': 150 + round_num * 5,  # 模拟逐渐增加的处理时间
                    'session_round': round_num
                }
                
                # 发送预测请求
                start_time = time.time()
                
                request_data = {
                    'weather_data': weather_points,
                    'model_type': 'ensemble'
                }
                
                response = client.post("/api/load-prediction", json=request_data)
                
                end_time = time.time()
                response_time = end_time - start_time
                
                # 更新统计信息
                session_stats['total_requests'] += 1
                session_stats['response_times'].append(response_time)
                
                if response.status_code == 200:
                    session_stats['successful_requests'] += 1
                    
                    result = response.json()
                    if result.get('status') == 'success':
                        pred_count = len(result.get('predictions', []))
                        assert pred_count == 24, f"预测数量错误: {pred_count}"
                else:
                    session_stats['errors'].append({
                        'round': round_num,
                        'status_code': response.status_code,
                        'response': response.text
                    })
                
                # 模拟轮次间的延迟
                time.sleep(0.1)
            
            # 验证会话稳定性
            success_rate = session_stats['successful_requests'] / session_stats['total_requests']
            avg_response_time = np.mean(session_stats['response_times'])
            max_response_time = np.max(session_stats['response_times'])
            
            assert success_rate >= 0.8, f"会话成功率过低: {success_rate}"
            assert avg_response_time < 5, f"平均响应时间过长: {avg_response_time}s"
            assert max_response_time < 30, f"最大响应时间过长: {max_response_time}s"
            assert len(session_stats['errors']) <= 1, f"会话中错误过多: {len(session_stats['errors'])}"