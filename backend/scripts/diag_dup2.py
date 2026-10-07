# -*- coding: utf-8 -*-
"""检查 weather_data 唯一键 + prediction_id 空值 + 精确重复统计"""
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

    ddl = await db_manager.execute_sql("SHOW CREATE TABLE weather_data")
    print('=== weather_data 索引（检查是否有 (location,timestamp) 唯一键）===')
    # 从 DDL 里找 UNIQUE
    create_sql = ddl[0]['Create Table']
    for line in create_sql.split('\n'):
        ls = line.strip()
        if ls.upper().startswith('UNIQUE') or 'UNIQUE KEY' in ls.upper():
            print('  唯一键:', ls[:120])
    if 'UNIQUE' not in create_sql.upper():
        print('  ⚠️ weather_data 无唯一键！')

    # prediction_id 空值
    n = await db_manager.execute_sql(
        "SELECT COUNT(*) AS n FROM load_predictions WHERE prediction_id IS NULL")
    print(f'\nload_predictions 中 prediction_id 为 NULL: {n[0]["n"]} 条')

    # weather_data 重复 (location, timestamp) 数量
    dup_w = await db_manager.execute_sql("""
        SELECT SUM(c-1) AS extra FROM (
            SELECT location, timestamp, COUNT(*) AS c
            FROM weather_data GROUP BY location, timestamp HAVING c > 1) t
    """)
    print(f'weather_data 冗余记录: {dup_w[0]["extra"] or 0} 条')

    # load_predictions 冗余统计
    dup_l = await db_manager.execute_sql("""
        SELECT SUM(c-1) AS extra FROM (
            SELECT prediction_id, target_timestamp, COUNT(*) AS c
            FROM load_predictions GROUP BY prediction_id, target_timestamp HAVING c > 1) t
    """)
    print(f'load_predictions 冗余记录: {dup_l[0]["extra"] or 0} 条')

    await db_manager.close()


asyncio.run(main())
