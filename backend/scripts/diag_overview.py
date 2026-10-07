# -*- coding: utf-8 -*-
"""诊断 overview 耗时与数据一致性"""
import json
import time
import urllib.request

BASE = 'http://localhost:8000'


def call(path, method='GET', body=None, token=None, timeout=180):
    req = urllib.request.Request(BASE + path, method=method)
    if body is not None:
        req.add_header('Content-Type', 'application/json')
        req.data = json.dumps(body).encode()
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode()), time.time() - t0


def main():
    s, b, _ = call('/api/auth/login', 'POST', {'username': 'demo2026', 'password': 'Demo1234'})
    token = b['access_token']
    print('登录:', s)

    # 1) overview 计时（第一次=冷缓存，Archive 并行拉取）
    s, b, dt = call('/api/prediction/overview', token=token)
    print(f'overview 冷缓存: {s} 耗时 {dt:.1f}s')
    data = b.get('data', {})
    hist = data.get('historical', {}).get('pairs', [])
    fut = data.get('future', {}).get('predictions', [])
    print(f'  历史回测段: {len(hist)} 条, {hist[0]["target_time"] if hist else "-"} ~ {hist[-1]["target_time"] if hist else "-"}')
    print(f'  历史指标: {json.dumps(data.get("historical", {}).get("metrics", {}), ensure_ascii=False)}')
    print(f'  未来预测段: {len(fut)} 条, 首条 {fut[0]["target_time"] if fut else "-"} 负荷 {fut[0]["future_forecast"] if fut else "-"}')

    # 1b) 第二次 overview（应命中 60s 结果缓存）
    s, b, dt = call('/api/prediction/overview', token=token)
    print(f'overview 热缓存: {s} 耗时 {dt:.1f}s')

    # 2) analytics 历史记录（最近 100 条）
    s, b, dt = call('/api/prediction/history?limit=100', token=token)
    recs = b.get('data', [])
    print(f'history: {s} 耗时 {dt:.1f}s, {len(recs)} 条')
    if recs:
        print(f'  最新: 预测时间 {recs[0]["prediction_timestamp"]} 目标 {recs[0]["target_timestamp"]} 负荷 {recs[0]["load_forecast_mw"]} 实际 {recs[0].get("actual_load_mw")}')
        print(f'  最旧: 预测时间 {recs[-1]["prediction_timestamp"]} 目标 {recs[-1]["target_timestamp"]}')

    # 3) 对比：取最近入库预测的目标时间与 overview 未来预测做差
    if fut and recs:
        rec_targets = sorted({r['target_timestamp'] for r in recs})
        fut_targets = sorted(p['target_time'] for p in fut)
        print(f'  入库预测目标时间: {rec_targets[0]} ~ {rec_targets[-1]} ({len(rec_targets)} 个唯一目标)')
        print(f'  overview 未来预测: {fut_targets[0]} ~ {fut_targets[-1]} ({len(fut_targets)} 条)')
        overlap = set(rec_targets) & set(fut_targets)
        print(f'  重叠目标时刻: {len(overlap)} 个: {sorted(overlap)[:5]}...')


if __name__ == '__main__':
    main()
