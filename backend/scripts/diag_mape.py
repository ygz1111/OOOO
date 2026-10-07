# -*- coding: utf-8 -*-
"""核查 MAPE 骤降原因：实际负荷数据真实性 + 配对逻辑"""
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

    # 1) actual_load_data 覆盖与数据源分布
    cov = await db_manager.execute_sql("""
        SELECT MIN(timestamp) AS mn, MAX(timestamp) AS mx, COUNT(*) AS n,
               COUNT(DISTINCT timestamp) AS uniq_ts, COUNT(DISTINCT actual_load_mw) AS uniq_val
        FROM actual_load_data
    """)
    print(f'actual_load_data: {cov[0]["mn"]} ~ {cov[0]["mx"]}, {cov[0]["n"]} 条, '
          f'唯一时间 {cov[0]["uniq_ts"]}, 唯一值 {cov[0]["uniq_val"]}')

    src = await db_manager.execute_sql("""
        SELECT data_source, COUNT(*) AS n FROM actual_load_data GROUP BY data_source
    """)
    print('数据源分布:', {s['data_source']: s['n'] for s in src})

    # 2) 最近 24h 实际负荷与入库预测对比（同一 target 时刻）
    print('\n=== 最近 24h: 实际负荷 vs 入库预测（真实回填口径）===')
    rows = await db_manager.execute_sql("""
        SELECT a.timestamp, a.actual_load_mw, p.load_forecast_mw, p.actual_load_mw AS pred_backfilled
        FROM actual_load_data a
        LEFT JOIN (
            SELECT target_timestamp, load_forecast_mw, actual_load_mw,
                   ROW_NUMBER() OVER (PARTITION BY target_timestamp ORDER BY prediction_timestamp DESC) rn
            FROM load_predictions
        ) p ON p.target_timestamp = a.timestamp AND p.rn = 1
        WHERE a.timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
        ORDER BY a.timestamp
    """)
    if rows:
        print(f'{"时间":<20}{"实际(MW)":>10}{"入库预测(MW)":>14}{"误差%":>8}')
        for r in rows[:26]:
            err = ''
            if r['load_forecast_mw'] and r['actual_load_mw']:
                err = f"{abs(r['load_forecast_mw'] - r['actual_load_mw']) / r['actual_load_mw'] * 100:.1f}"
            print(f'{str(r["timestamp"]):<20}{r["actual_load_mw"]:>10.1f}'
                  f'{r["load_forecast_mw"] if r["load_forecast_mw"] is not None else 0:>14.1f}{err:>8}')
    else:
        print('无最近 24h 记录')

    # 3) 检查 actual_load_data 是否与训练数据重叠（时间范围）
    train = await db_manager.execute_sql("""
        SELECT COUNT(*) AS n FROM actual_load_data WHERE timestamp < '2026-01-01'
    """)
    print(f'\nactual_load_data 中早于 2026-01-01（训练期）的记录: {train[0]["n"]} 条')

    # 4) 最近 5 天实际负荷的日变化（检查是否真实波动）
    hourly = await db_manager.execute_sql("""
        SELECT timestamp, actual_load_mw FROM actual_load_data
        WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 5 DAY)
        ORDER BY timestamp LIMIT 30
    """)
    if hourly:
        vals = [h['actual_load_mw'] for h in hourly]
        print(f'最近 5 天实际负荷抽样: 均值 {sum(vals)/len(vals):.0f}, '
              f'min {min(vals):.0f}, max {max(vals):.0f}, 相邻差均值 {sum(abs(vals[i+1]-vals[i]) for i in range(len(vals)-1))/max(len(vals)-1,1):.0f} MW')

    await db_manager.close()


asyncio.run(main())
