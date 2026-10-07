# -*- coding: utf-8 -*-
"""验证 history / 模型对比修复后的数据返回"""
import json
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
    print(f'登录: {s}')

    s, b = call('/api/prediction/history?limit=30', token=token)
    data = b.get('data', [])
    print(f'history: {s}, {len(data)} 条')
    if data:
        r = data[0]
        print(f'  最新: 预测时间 {r["prediction_timestamp"]} 目标 {r["target_timestamp"]} 负荷 {r["load_forecast_mw"]} 实际 {r.get("actual_load_mw")}')
        print(f'  时间跨度: {data[-1]["prediction_timestamp"]} ~ {data[0]["prediction_timestamp"]}')

    s, b = call('/api/analytics/comparison/models?hours=48', token=token)
    d = b.get('data', {})
    print(f'comparison/models: {s}, 模型数 {len(d)}')
    for name, item in d.items():
        print(f'  {name}: count={item.get("count")}, MAPE={item.get("mape")}, RMSE={item.get("rmse")}, MAE={item.get("mae")}')

    s, b = call('/api/analytics/accuracy/stats', token=token)
    print(f'accuracy/stats: {s}, {json.dumps(b.get("data", {}))[:120]}')


if __name__ == '__main__':
    main()
