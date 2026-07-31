#!/usr/bin/env python3
"""
智能电网负荷预测系统 - MySQL数据库功能测试

用于测试数据库连接、插入、查询等功能是否正常工作

使用方法:
    python test_database.py
"""

import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta
import json

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 添加项目根目录到Python路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

try:
    # 导入数据库模块
    from realtime_api.database import (
        DatabaseManager,
        init_database,
        close_database,
        db_manager,
    )
    from realtime_api.crud import (
        LoadPredictionsCRUD,
        WeatherDataCRUD,
        ModelPerformanceCRUD,
        APILogsCRUD,
        SystemMetricsCRUD,
        PerformanceAlertsCRUD,
    )
    logger.info("✅ 成功导入数据库模块")
except ImportError as e:
    logger.error(f"❌ 导入数据库模块失败: {e}")
    logger.info("请确保已安装mysql-connector-python: pip install mysql-connector-python")
    sys.exit(1)


async def test_database_connection():
    """测试数据库连接"""
    print("\n" + "="*60)
    print("测试1: 数据库连接")
    print("="*60)
    
    try:
        # 初始化数据库
        logger.info("正在初始化数据库连接...")
        await init_database()
        logger.info("✅ 数据库初始化成功")
        
        # 健康检查
        health = await db_manager.health_check()
        logger.info(f"数据库健康状态: {health}")
        
        if health['status'] == 'healthy':
            logger.info("✅ 数据库连接健康")
            return True
        else:
            logger.error("❌ 数据库连接异常")
            return False
            
    except Exception as e:
        logger.error(f"❌ 数据库连接测试失败: {e}")
        return False


async def test_weather_data_crud():
    """测试气象数据CRUD操作"""
    print("\n" + "="*60)
    print("测试2: 气象数据CRUD操作")
    print("="*60)
    
    try:
        now = datetime.now()
        
        # 插入测试数据
        logger.info("正在插入气象数据...")
        insert_id = await WeatherDataCRUD.insert_weather_data(
            timestamp=now,
            location="Test_City",
            temperature_2m=25.5,
            relative_humidity_2m=65.0,
            wind_speed_10m=8.5,
            cloud_cover=30,
            shortwave_radiation=800,
            data_quality_score=0.95,
            is_validated=True
        )
        logger.info(f"✅ 成功插入气象数据，ID: {insert_id}")
        
        # 查询测试数据
        start_time = now - timedelta(hours=1)
        end_time = now + timedelta(hours=1)
        
        result = await WeatherDataCRUD.get_weather_by_location_and_time(
            location="Test_City",
            start_time=start_time,
            end_time=end_time
        )
        
        if result and len(result) > 0:
            logger.info(f"✅ 成功查询到 {len(result)} 条气象数据")
            logger.info(f"   示例数据: 温度={result[0]['temperature_2m']}, 湿度={result[0]['relative_humidity_2m']}")
            return True
        else:
            logger.warning("⚠️  查询结果为空")
            return False
            
    except Exception as e:
        logger.error(f"❌ 气象数据CRUD测试失败: {e}")
        return False


async def test_load_predictions_crud():
    """测试负荷预测数据CRUD操作"""
    print("\n" + "="*60)
    print("测试3: 负荷预测数据CRUD操作")
    print("="*60)
    
    try:
        now = datetime.now()
        target_time = now + timedelta(hours=1)
        
        # 插入测试数据
        logger.info("正在插入负荷预测数据...")
        insert_id = await LoadPredictionsCRUD.insert_prediction(
            prediction_timestamp=now,
            target_timestamp=target_time,
            load_forecast_mw=1200.5,
            pv_estimation_mw=150.2,
            net_load_mw=1050.3,
            confidence_lower_mw=1150.0,
            confidence_upper_mw=1250.0,
            model_type='ensemble',
            model_weights={'lstm': 0.25, 'bigru': 0.25, 'tcn': 0.25, 'transformer': 0.25},
            inference_time_ms=125.5,
            cache_hit=False,
            data_source='openmeteo'
        )
        logger.info(f"✅ 成功插入负荷预测数据，ID: {insert_id}")
        
        # 查询测试数据
        start_time = now - timedelta(hours=1)
        end_time = now + timedelta(hours=2)
        
        result = await LoadPredictionsCRUD.get_predictions_by_time_range(
            start_time=start_time,
            end_time=end_time
        )
        
        if result and len(result) > 0:
            logger.info(f"✅ 成功查询到 {len(result)} 条负荷预测数据")
            logger.info(f"   示例数据: 负荷={result[0]['load_forecast_mw']}MW, 光伏={result[0]['pv_estimation_mw']}MW")
            return True
        else:
            logger.warning("⚠️  查询结果为空")
            return False
            
    except Exception as e:
        logger.error(f"❌ 负荷预测数据CRUD测试失败: {e}")
        return False


async def test_model_performance_crud():
    """测试模型性能数据CRUD操作"""
    print("\n" + "="*60)
    print("测试4: 模型性能数据CRUD操作")
    print("="*60)
    
    try:
        # 插入测试数据
        logger.info("正在插入模型性能数据...")
        insert_id = await ModelPerformanceCRUD.insert_performance(
            model_name='ensemble',
            model_version='1.0.0',
            total_inferences=1000,
            successful_inferences=995,
            failed_inferences=5,
            average_inference_time_ms=125.5,
            mae=15.2,
            rmse=22.1,
            mape=0.0125,
            gpu_memory_used_mb=512.5,
            cpu_utilization_percent=35.2,
            batch_size=16,
            device='cuda'
        )
        logger.info(f"✅ 成功插入模型性能数据，ID: {insert_id}")
        
        # 查询测试数据
        result = await ModelPerformanceCRUD.get_performance_by_model(
            model_name='ensemble',
            hours=24
        )
        
        if result and len(result) > 0:
            logger.info(f"✅ 成功查询到 {len(result)} 条模型性能数据")
            logger.info(f"   示例数据: 推理次数={result[0]['total_inferences']}, "
                       f"成功率={result[0]['successful_inferences']/result[0]['total_inferences']:.2%}")
            return True
        else:
            logger.warning("⚠️  查询结果为空")
            return False
            
    except Exception as e:
        logger.error(f"❌ 模型性能数据CRUD测试失败: {e}")
        return False


async def test_api_logs_crud():
    """测试API日志CRUD操作"""
    print("\n" + "="*60)
    print("测试5: API日志CRUD操作")
    print("="*60)
    
    try:
        # 插入测试数据
        logger.info("正在插入API日志数据...")
        insert_id = await APILogsCRUD.insert_log(
            request_id='test-request-123',
            endpoint='/api/prediction/load',
            method='POST',
            status_code=200,
            response_time_ms=125.5,
            request_size_bytes=512,
            response_size_bytes=1024,
            client_ip='192.168.1.100',
            user_agent='Test Client',
            error_message=None
        )
        logger.info(f"✅ 成功插入API日志数据，ID: {insert_id}")
        
        # 查询测试数据
        result = await APILogsCRUD.get_logs_by_endpoint(
            endpoint='/api/prediction/load',
            hours=24,
            limit=10
        )
        
        if result and len(result) > 0:
            logger.info(f"✅ 成功查询到 {len(result)} 条API日志")
            logger.info(f"   示例数据: 端点={result[0]['endpoint']}, 状态码={result[0]['status_code']}")
            return True
        else:
            logger.warning("⚠️  查询结果为空")
            return False
            
    except Exception as e:
        logger.error(f"❌ API日志CRUD测试失败: {e}")
        return False


async def test_batch_operations():
    """测试批量操作"""
    print("\n" + "="*60)
    print("测试6: 批量插入性能测试")
    print("="*60)
    
    try:
        # 准备批量数据
        batch_data = []
        now = datetime.now()
        
        for i in range(10):
            timestamp = now + timedelta(hours=i)
            batch_data.append((
                timestamp, "Test_City", 25.0 + i, 65.0 + i,
                8.0 + i, 30 + i, 800 + i*10
            ))
        
        logger.info(f"正在批量插入 {len(batch_data)} 条测试数据...")
        
        sql = """
        INSERT INTO weather_data (
            timestamp, location, temperature_2m, relative_humidity_2m,
            wind_speed_10m, cloud_cover, shortwave_radiation
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        count = await db_manager.execute_sql_many(sql, batch_data)
        logger.info(f"✅ 成功批量插入 {count} 条数据")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ 批量操作测试失败: {e}")
        return False


async def cleanup_test_data():
    """清理测试数据（可选）"""
    print("\n" + "="*60)
    print("清理: 测试数据")
    print("="*60)
    
    try:
        logger.info("正在清理测试数据...")
        
        # 删除测试数据
        await db_manager.execute_sql(
            "DELETE FROM weather_data WHERE location = 'Test_City'"
        )
        await db_manager.execute_sql(
            "DELETE FROM load_predictions WHERE data_source = 'openmeteo'"
        )
        await db_manager.execute_sql(
            "DELETE FROM model_performance WHERE model_name = 'ensemble'"
        )
        
        logger.info("✅ 测试数据清理完成")
        return True
        
    except Exception as e:
        logger.warning(f"⚠️  清理测试数据时出现异常: {e}")
        return False


async def run_all_tests():
    """运行所有测试"""
    print("\n" + "█" * 60)
    print("    智能电网负荷预测系统 - MySQL数据库功能测试")
    print("█" * 60)
    
    results = []
    
    # 测试数据库连接
    results.append(await test_database_connection())
    
    # 仅当数据库连接成功时才继续
    if results[0]:
        # 运行各种CRUD测试
        results.append(await test_weather_data_crud())
        results.append(await test_load_predictions_crud())
        results.append(await test_model_performance_crud())
        results.append(await test_api_logs_crud())
        results.append(await test_batch_operations())
        
        # 清理测试数据
        await cleanup_test_data()
    
    # 关闭数据库连接
    try:
        await close_database()
        logger.info("✅ 数据库连接已关闭")
    except Exception as e:
        logger.warning(f"⚠️  关闭数据库连接时出现异常: {e}")
    
    # 显示测试报告
    print("\n" + "="*60)
    print("    测试报告")
    print("="*60)
    
    test_names = [
        "数据库连接",
        "气象数据CRUD",
        "负荷预测CRUD",
        "模型性能CRUD",
        "API日志CRUD",
        "批量操作"
    ]
    
    passed = 0
    for i, (name, result) in enumerate(zip(test_names, results)):
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{i+1}. {name:<15} {status}")
        if result:
            passed += 1
    
    print("="*60)
    print(f"总结: {passed}/{len(results)} 项测试通过")
    
    if passed == len(results):
        print("🎉 所有测试全部通过！数据库功能正常。")
        return 0
    else:
        print("⚠️  部分测试失败，请检查错误信息。")
        return 1


if __name__ == "__main__":
    """主函数"""
    try:
        exit_code = asyncio.run(run_all_tests())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        logger.error(f"测试运行失败: {e}")
        sys.exit(1)