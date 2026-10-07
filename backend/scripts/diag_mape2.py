# -*- coding: utf-8 -*-
"""对比 overview 回测 pairs 与入库预测，定位 MAPE 差异来源"""
import json
import time
import urllib.request
import urllib.error

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


def main():
    s, b = call('/api/auth/login', 'POST', {'username': 'demo2026', 'password': 'Demo1234'})
    token = b.get('access_token', '')

    s, b = call('/api/prediction/overview', token=token)
    data = b.get('data', {})
    pairs = data.get('historical', {}).get('pairs', [])
    metrics = data.get('historical', {}).get('metrics', {})
    print(f'overview 历史回测: {len(pairs)} 条, 指标 {json.dumps(metrics, ensure_ascii=False)}')
    print(f'\n{"目标时间":<22}{"实际(MW)":>10}{"回测预测(MW)":>14}{"误差%":>8}{"星期":>6}')
    for p in pairs:
        t = p['target_time'][:10]
        from datetime import datetime
        wd = ['一', '二', '三', '四', '五', '六', '日'][datetime.fromisoformat(p['target_time']).weekday()]
        err = abs(p['historical_forecast'] - p['historical_actual']) / p['historical_actual'] * 100
        print(f'{p["target_time"]:<22}{p["historical_actual"]:>10.1f}{p["historical_forecast"]:>14.1f}{err:>8.2f}{wd:>6}')

    # 同时间入库预测（去重最新）
    s, b = call('/api/prediction/history?limit=200', token=token)
    recs = b.get('data', [])
    if recs:
        print(f'\n{"目标时间":<22}{"实际(MW)":>10}{"入库预测(MW)":>14}{"误差%":>8}')
        for r in sorted(recs, key=lambda x: x['target_timestamp']):
            if r.get('actual_load_mw') is not None:
                err = abs(r['load_forecast_mw'] - r['actual_load_mw']) / r['actual_load_mw'] * 100
                print(f'{r["target_timestamp"]:<22}{r["actual_load_mw"]:>10.1f}{r["load_forecast_mw"]:>14.1f}{err:>8.2f}')


if __name__ == '__main__':
    main()
