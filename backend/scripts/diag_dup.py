# -*- coding: utf-8 -*-
"""检查 load_predictions 表结构 + 重复模式"""
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

    # 表结构
    ddl = await db_manager.execute_sql("SHOW CREATE TABLE load_predictions")
    print('=== load_predictions 表结构 ===')
    print(ddl[0]['Create Table'][:1200] if ddl else '无表?')

    # 唯一键检查
    keys = await db_manager.execute_sql("""
        SELECT index_name, GROUP_CONCAT(column_name ORDER BY seq_in_index) AS cols, non_unique
        FROM information_schema.statistics
        WHERE table_schema = DATABASE() AND table_name = 'load_predictions'
        GROUP BY index_name, non_unique
    """)
    print('\n=== 索引 ===')
    for k in keys:
        print(f'  {k["index_name"]}: {k["cols"]} unique={k["non_unique"]==0}')

    # 重复模式：同一 (prediction_id, target_timestamp) 出现次数分布
    dup = await db_manager.execute_sql("""
        SELECT cnt, COUNT(*) AS groups
        FROM (SELECT prediction_id, target_timestamp, COUNT(*) AS cnt
              FROM load_predictions GROUP BY prediction_id, target_timestamp) t
        GROUP BY cnt ORDER BY cnt
    """)
    print('\n=== (prediction_id, target) 重复度分布 ===')
    for d in dup:
        print(f'  重复 {d["cnt"]} 次的组数: {d["groups"]}')

    # 总重复量
    total = await db_manager.execute_sql("SELECT COUNT(*) AS n FROM load_predictions")
    uniq = await db_manager.execute_sql("""
        SELECT COUNT(*) AS n FROM (SELECT 1 FROM load_predictions GROUP BY prediction_id, target_timestamp) t
    """)
    print(f'\n总记录 {total[0]["n"]}, 去重后应保留 {uniq[0]["n"]}, 冗余 {total[0]["n"] - uniq[0]["n"]} 条')

    await db_manager.close()


asyncio.run(main())
