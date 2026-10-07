# -*- coding: utf-8 -*-
"""并发压测：模拟首屏同时发起 overview + weather + predict/load（冷缓存场景）"""
import json
import time
import urllib.request
import urllib.error
import threading

BASE = 'http://localhost:8000'


def call(path, method='GET', body=None, token=None, timeout=150):
    req = urllib.request.Request(BASE + path, method=method)
    if body is not None:
        req.add_header('Content-Type', 'application/json')
        req.data = json.dumps(body).encode()
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode()), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, {}, time.time() - t0
    except Exception as e:
        return -1, {'err': str(e)}, time.time() - t0


def main():
    s, b, _ = call('/api/auth/login', 'POST', {'username': 'demo2026', 'password': 'Demo1234'})
    token = b.get('access_token', '')
    print(f'登录: {s}')

    results = {}
    lock = threading.Lock()

    def worker(name, path, method='GET', body=None):
        s, b, dt = call(path, method, body, token)
        with lock:
            results[name] = (s, round(dt, 1))
            print(f'  [{name}] {s} 耗时 {dt:.1f}s')

    # 模拟首屏并发：3× overview + 1 weather + 1 predict/load 同时发出
    threads = []
    for i in range(3):
        threads.append(threading.Thread(target=worker, args=(f'overview-{i}', '/api/prediction/overview')))
    threads.append(threading.Thread(target=worker, args=('weather', '/api/weather/current')))
    threads.append(threading.Thread(target=worker, args=('predict/load', '/api/prediction/load', 'POST', {})))

    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = time.time() - t0
    print(f'\n并发 5 请求全部完成: 总耗时 {total:.1f}s')
    for k, v in sorted(results.items()):
        status = '✅' if v[0] == 200 else f'❌{v[0]}'
        print(f'  {status} {k}: {v[1]}s')

    # 检查是否有 504
    bad = [k for k, v in results.items() if v[0] != 200]
    print('\n结论:', '全部 200 ✅ 无超时' if not bad else f'存在异常: {bad} ❌')


if __name__ == '__main__':
    main()
