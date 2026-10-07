# -*- coding: utf-8 -*-
"""诊断：历史记录/模型对比为何无数据（查库 + 查接口）"""
import json
import time
import urllib.request
import urllib.error
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)
from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, '..', '.env'))

from realtime_api.database import db_manager
import asyncio

BASE = 'http://localhost:8000'


def call(path, method='GET', body=None, token=None, timeout=60):
    req = urllib.request.Request(BASE + path, method=method)
    if body is not None:
        req.add_header('Content-Type', 'application/json')
        req.data = json.dumps(body).encode()
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}


async def db_diag():
    await db_manager.initialize()
    # load_predictions 最新记录
    rows = await db_manager.execute_sql("""
        SELECT prediction_timestamp, target_timestamp, load_forecast_mw, model_type
        FROM load_predictions ORDER BY prediction_timestamp DESC, target_timestamp DESC LIMIT 8
    """)
    print('=== load_predictions 最新 8 条 ===')
    for r in rows:
        print(f'  pred={r["prediction_timestamp"]} target={r["target_timestamp"]} load={r["load_forecast_mw"]} type={r["model_type"]}')
    cnt = await db_manager.execute_sql("SELECT COUNT(*) AS n, MAX(prediction_timestamp) AS mx FROM load_predictions")
    print(f'  全表 {cnt[0]["n"]} 条, 最新预测时间 {cnt[0]["mx"]}')
    # 最近 24h 目标时间有多少
    c24 = await db_manager.execute_sql("""
        SELECT COUNT(*) AS n FROM load_predictions
        WHERE target_timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
    """)
    print(f'  目标时间在最近 24h(MySQL NOW)内的记录: {c24[0]["n"]} 条')
    await db_manager.close()


async def main():
    await db_diag()
    s, b = call('/api/auth/login', 'POST', {'username': 'demo2026', 'password': 'Demo1234'})
    token = b.get('access_token', '')
    print(f'\n登录: {s}')

    s, b = call('/api/prediction/history?limit=50', token=token)
    data = b.get('data', [])
    print(f'history 接口: {s}, {len(data)} 条', (data[0] if data else ''))
    s, b = call('/api/analytics/comparison/models?hours=24', token=token)
    print(f'comparison/models: {s}, {json.dumps(b.get("data", {}))[:200]}')
    s, b = call('/api/analytics/accuracy/stats', token=token)
    print(f'accuracy/stats: {s}, {json.dumps(b.get("data", {}))[:150]}')


asyncio.run(main())
