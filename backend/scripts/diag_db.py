# -*- coding: utf-8 -*-
"""诊断 load_predictions / actual_load_data 数据分布（绕过 API 直查 MySQL）"""
import os
import sys
from datetime import datetime, timedelta

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, '..', '.env'))

from realtime_api.database import db_manager
import asyncio


async def main():
    await db_manager.initialize()
    # 1) load_predictions 最近记录的时间分布
    rows = await db_manager.execute_sql("""
        SELECT prediction_timestamp, target_timestamp, load_forecast_mw, actual_load_mw, data_source
        FROM load_predictions
        ORDER BY prediction_timestamp DESC, target_timestamp ASC
        LIMIT 60
    """)
    print(f'load_predictions 最近 60 条（预测时间/目标时间/负荷/实际/来源）:')
    for r in rows[:20]:
        print(f'  pred={r["prediction_timestamp"]} target={r["target_timestamp"]} '
              f'load={r["load_forecast_mw"]} actual={r["actual_load_mw"]} src={r["data_source"]}')
    print(f'  ... 共取 {len(rows)} 条')

    # 2) 唯一目标时间数量（最近 500 条）
    cnt = await db_manager.execute_sql("""
        SELECT COUNT(DISTINCT target_timestamp) AS n, COUNT(*) AS total
        FROM load_predictions
    """)
    print(f'全表: 唯一目标时间 {cnt[0]["n"]} 个, 总记录 {cnt[0]["total"]} 条')

    # 3) actual_load_data 覆盖范围
    act = await db_manager.execute_sql("""
        SELECT MIN(timestamp) AS mn, MAX(timestamp) AS mx, COUNT(*) AS n
        FROM actual_load_data
    """)
    print(f'actual_load_data: {act[0]["mn"]} ~ {act[0]["mx"]}, {act[0]["n"]} 条')

    # 4) 最近 48h 实际负荷小时覆盖
    cutoff = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=48)
    hourly = await db_manager.execute_sql("""
        SELECT DATE_FORMAT(timestamp, '%Y-%m-%d %H:00') AS hr, COUNT(*) AS n
        FROM actual_load_data
        WHERE timestamp >= %s
        GROUP BY hr ORDER BY hr
    """, (cutoff,))
    print(f'最近 48h 实际负荷按小时覆盖（共 {len(hourly)} 个有数据的小时）:')
    print('  ' + ', '.join(f'{h["hr"]}({h["n"]})' for h in hourly[:30]))

    await db_manager.close()


asyncio.run(main())
