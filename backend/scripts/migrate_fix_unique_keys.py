# -*- coding: utf-8 -*-
"""
数据库修复迁移：唯一键补齐 + 冗余清理

背景（2026-08 诊断）：
  1. load_predictions 代码用 INSERT IGNORE + 期望 (prediction_id, target_timestamp) 唯一键
     去重，但表结构只有主键 id，唯一键从未建立；
  2. weather_data 代码用 INSERT ... ON DUPLICATE KEY UPDATE + 期望 (location, timestamp)
     唯一键，同样缺失 → 已产生 348 条冗余且继续膨胀。

本脚本：
  1. 清理 weather_data 中 (location, timestamp) 重复记录（每组保留最新一条）
  2. 为 weather_data 添加唯一键 uq_weather_location_timestamp (location, timestamp)
  3. 为 load_predictions 添加唯一键 uq_prediction_target (prediction_id, target_timestamp)
     （load_predictions 当前无 (prediction_id,target) 重复，可直接添加）

用法：cd backend && python scripts/migrate_fix_unique_keys.py
"""
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, '..', '.env'))

from realtime_api.database import db_manager
import asyncio


async def main():
    await db_manager.initialize()
    print('连接数据库成功')

    # ── 1. 清理 weather_data 重复（保留每组最新一条）──
    dup = await db_manager.execute_sql("""
        SELECT COUNT(*) AS n FROM (
            SELECT 1 FROM weather_data
            GROUP BY location, timestamp HAVING COUNT(*) > 1) t
    """)
    dup_n = dup[0]['n'] if dup else 0
    print(f'weather_data 重复组: {dup_n}')

    if dup_n > 0:
        deleted = await db_manager.execute_sql("""
            DELETE w FROM weather_data w
            JOIN (
                SELECT location, timestamp, MAX(id) AS keep_id
                FROM weather_data
                GROUP BY location, timestamp HAVING COUNT(*) > 1
            ) k ON w.location = k.location AND w.timestamp = k.timestamp
            WHERE w.id <> k.keep_id
        """)
        print(f'  已清理 weather_data 冗余: {deleted} 条')

    # ── 2. weather_data 唯一键 ──
    has_w = await db_manager.execute_sql("""
        SELECT COUNT(*) AS n FROM information_schema.statistics
        WHERE table_schema = DATABASE() AND table_name = 'weather_data'
          AND index_name = 'uq_weather_location_timestamp' AND non_unique = 0
    """)
    if has_w[0]['n'] == 0:
        await db_manager.execute_sql(
            "ALTER TABLE weather_data ADD UNIQUE KEY uq_weather_location_timestamp (location, timestamp)")
        print('✅ weather_data 已添加唯一键 uq_weather_location_timestamp')
    else:
        print('weather_data 唯一键已存在，跳过')

    # ── 3. load_predictions 唯一键 ──
    has_l = await db_manager.execute_sql("""
        SELECT COUNT(*) AS n FROM information_schema.statistics
        WHERE table_schema = DATABASE() AND table_name = 'load_predictions'
          AND index_name = 'uq_prediction_target' AND non_unique = 0
    """)
    if has_l[0]['n'] == 0:
        await db_manager.execute_sql(
            "ALTER TABLE load_predictions ADD UNIQUE KEY uq_prediction_target (prediction_id, target_timestamp)")
        print('✅ load_predictions 已添加唯一键 uq_prediction_target')
    else:
        print('load_predictions 唯一键已存在，跳过')

    # ── 4. 验证 ──
    w = await db_manager.execute_sql("SELECT COUNT(*) AS n FROM weather_data")
    l = await db_manager.execute_sql("SELECT COUNT(*) AS n FROM load_predictions")
    print(f'\n验证: weather_data {w[0]["n"]} 条, load_predictions {l[0]["n"]} 条')

    await db_manager.close()
    print('\n✅ 数据库修复完成')


if __name__ == '__main__':
    asyncio.run(main())
