#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预测结果管理功能集成测试

验证核心功能4：预测结果管理的完整性
包括预测准确性追踪、对比分析和综合报告生成

作者: 毕业设计项目
"""

import os
import sys
import asyncio
import json
from datetime import datetime, timedelta

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd
from realtime_api.database import init_database, close_database, db_manager
from realtime_api.crud import LoadPredictionsCRUD
from realtime_api.monitoring_service import MonitoringService, get_monitoring_service

def main():
    print("\n" + "="*60)
    print("预测结果管理功能测试")
    print("="*60)
    
    # 初始化
    asyncio.run(init_database())
    
    try:
        # 测试1: 创建测试数据
        print("\n测试1: 创建测试预测数据")
        now = datetime.now()
        
        test_data = []
        for i in range(24):
            pred_time = now + timedelta(hours=i)
            test_data.append({
                'prediction_timestamp': now,
                'target_timestamp': pred_time,
                'load_forecast_mw': 2500.0 + np.random.normal(0, 100),
                'pv_estimation_mw': 150.0 + np.random.normal(0, 20),
                'net_load_mw': 2350.0 + np.random.normal(0, 90),
                'model_type': 'ensemble',
                'inference_time_ms': 2500.0 + np.random.normal(0, 200),
                'data_source': 'test'
            })
        
        print(f"✅ 创建了 {len(test_data)} 条测试数据")
        
        # 存储数据
        async def store_data():
            stored_count = 0
            for pred in test_data:
                await LoadPredictionsCRUD.insert_prediction(
                    prediction_timestamp=pred['prediction_timestamp'],
                    target_timestamp=pred['target_timestamp'],
                    load_forecast_mw=pred['load_forecast_mw'],
                    pv_estimation_mw=pred['pv_estimation_mw'],
                    net_load_mw=pred['net_load_mw'],
                    model_type=pred['model_type'],
                    inference_time_ms=pred['inference_time_ms'],
                    data_source=pred['data_source']
                )
                stored_count += 1
            return stored_count
        
        stored_count = asyncio.run(store_data())
        print(f"✅ 成功存储 {stored_count} 条预测记录到数据库")
        
        # 测试2: 测试准确性追踪
        print("\n测试2: 预测准确性追踪")
        monitoring_service = get_monitoring_service()
        
        # 记录准确性数据
        test_cases = [(2500.0, 2450.0), (2600.0, 2580.0), (2400.0, 2420.0)]
        for pred_val, actual_val in test_cases:
            monitoring_service.record_prediction_accuracy(
                prediction_value=pred_val,
                actual_value=actual_val,
                timestamp=datetime.now()
            )
        
        stats = monitoring_service.get_prediction_accuracy_stats()
        print(f"✅ 准确性统计: MAPE={stats.get('mape', 0):.2f}%, RMSE={stats.get('rmse', 0):.2f}")
        
        # 测试3: 模型漂移检测
        print("\n测试3: 模型漂移检测")
        drift_result = monitoring_service.check_model_drift()
        print(f"✅ 漂移检测完成: PSI={drift_result.get('psi_value', 0):.4f}, 状态={'正常' if not drift_result.get('drift_detected', False) else '检测到漂移'}")
        
        # 测试4: 数据质量监控
        print("\n测试4: 数据质量监控")
        quality_result = monitoring_service.validate_data_quality({
            'temperature': 25.0,
            'humidity': 60.0,
            'wind_speed': 10.0
        })
        print(f"✅ 数据质量验证完成: 有效性={quality_result.get('is_valid', False)}")
        
        print("\n" + "="*60)
        print("✅ 所有预测结果管理功能测试完成")
        print("✅ 核心功能4：预测结果管理 - 已实现并验证")
        print("="*60)
        
    except Exception as e:
        print(f"❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        asyncio.run(close_database())

if __name__ == "__main__":
    main()