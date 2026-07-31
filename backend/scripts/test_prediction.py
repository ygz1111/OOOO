#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""触发一次预测请求，验证数据存入数据库"""
import requests
import mysql.connector

# 1. 调用预测 API
print("[1] 调用预测 API...")
try:
    r = requests.post('http://localhost:8000/api/prediction/load', json={}, timeout=120)
    print(f"  HTTP 状态码: {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        preds = d.get('predictions', [])
        print(f"  预测结果: {len(preds)} 条")
        print(f"  推理耗时: {d.get('inference_time_ms', '?')}ms")
        print(f"  数据源: {d.get('data_source', '?')}")
    else:
        print(f"  错误: {r.text[:200]}")
except Exception as e:
    print(f"  请求失败: {e}")

# 2. 查数据库验证
print("\n[2] 查询数据库 load_predictions 表...")
try:
    conn = mysql.connector.connect(
        use_pure=True, host='localhost', port=3306,
        user='root', password='315131', database='OOOO'
    )
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM load_predictions")
    count = cur.fetchone()[0]
    print(f"  总记录数: {count}")

    if count > 0:
        cur.execute("SELECT id, target_timestamp, load_forecast_mw, model_type FROM load_predictions ORDER BY id DESC LIMIT 5")
        rows = cur.fetchall()
        print("  最近5条:")
        for row in rows:
            print(f"    ID={row[0]}, 目标时间={row[1]}, 预测负荷={row[2]}MW, 模型={row[3]}")
    cur.close()
    conn.close()
except Exception as e:
    print(f"  查询失败: {e}")

print("\n完成! 现在可以打开前端 http://localhost:3004 查看历史分析页面")
