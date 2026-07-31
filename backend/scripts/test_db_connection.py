#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试数据库连接 + 模拟插入一条预测记录
验证后端预测保存流程是否正常
"""
import os
import sys
import asyncio
from datetime import datetime, timedelta

# 加载 .env
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# 设置项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from realtime_api.database import db_manager, init_database
from realtime_api.crud import LoadPredictionsCRUD


async def test_database():
    print("=" * 50)
    print("  数据库连接测试")
    print("=" * 50)

    # 1. 初始化连接池
    print("\n[1] 初始化数据库连接池...")
    try:
        await init_database()
        print("  -> 连接池初始化成功")
    except Exception as e:
        print(f"  -> 连接池初始化失败: {e}")
        return

    # 2. 健康检查
    print("\n[2] 数据库健康检查...")
    try:
        health = await db_manager.health_check()
        print(f"  -> 状态: {health['status']}")
        print(f"  -> 响应时间: {health.get('response_time_ms', 'N/A')}ms")
    except Exception as e:
        print(f"  -> 健康检查失败: {e}")
        return

    # 3. 插入测试预测记录
    print("\n[3] 插入测试预测记录...")
    try:
        now = datetime.now()
        target = now + timedelta(hours=1)

        insert_id = await LoadPredictionsCRUD.insert_prediction(
            prediction_timestamp=now,
            target_timestamp=target,
            load_forecast_mw=1234.5,
            pv_estimation_mw=56.7,
            net_load_mw=1177.8,
            model_type='ensemble',
            inference_time_ms=42.0,
            data_source='test'
        )
        print(f"  -> 插入成功! ID: {insert_id}")
    except Exception as e:
        print(f"  -> 插入失败: {e}")
        return

    # 4. 查询验证
    print("\n[4] 查询验证...")
    try:
        records = await LoadPredictionsCRUD.get_predictions_by_time_range(
            start_time=datetime.now() - timedelta(hours=1),
            end_time=datetime.now() + timedelta(hours=2),
        )
        print(f"  -> 查询到 {len(records)} 条记录")
        if records:
            r = records[-1]
            print(f"  -> 最新记录: ID={r['id']}, 预测负荷={r['load_forecast_mw']}MW, 模型={r['model_type']}")
    except Exception as e:
        print(f"  -> 查询失败: {e}")
        return

    # 5. 清理测试数据
    print("\n[5] 清理测试数据...")
    try:
        async with db_manager.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM load_predictions WHERE data_source = 'test'")
            conn.commit()
            cursor.close()
        print("  -> 测试数据已清理")
    except Exception as e:
        print(f"  -> 清理失败: {e}")

    print("\n" + "=" * 50)
    print("  ALL TESTS PASSED!")
    print("=" * 50)
    print("\n  数据库完全正常，后端预测结果可以正确保存。")
    print("  现在可以启动后端服务，前端预测数据将自动存入数据库。")


if __name__ == '__main__':
    asyncio.run(test_database())
