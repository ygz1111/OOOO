#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补建数据库索引 (MySQL 不支持 CREATE INDEX IF NOT EXISTS)"""
import mysql.connector

conn = mysql.connector.connect(
    use_pure=True,
    host='localhost',
    port=3306,
    user='root',
    password='315131',
    database='OOOO'
)
cursor = conn.cursor()

indexes = [
    'CREATE INDEX idx_weather_timestamp ON weather_data(timestamp)',
    'CREATE INDEX idx_weather_location ON weather_data(location)',
    'CREATE INDEX idx_weather_location_ts ON weather_data(location, timestamp)',
    'CREATE INDEX idx_pred_pred_ts ON load_predictions(prediction_timestamp)',
    'CREATE INDEX idx_pred_target_ts ON load_predictions(target_timestamp)',
    'CREATE INDEX idx_pred_model ON load_predictions(model_type)',
    'CREATE INDEX idx_model_perf_ts ON model_performance(timestamp)',
    'CREATE INDEX idx_model_perf_model ON model_performance(model_name)',
    'CREATE INDEX idx_api_logs_ts ON api_request_logs(timestamp)',
    'CREATE INDEX idx_api_logs_endpoint ON api_request_logs(endpoint)',
    'CREATE INDEX idx_api_logs_status ON api_request_logs(status_code)',
    'CREATE INDEX idx_sys_metrics_ts ON system_metrics(timestamp)',
    'CREATE INDEX idx_alerts_ts ON performance_alerts(timestamp)',
    'CREATE INDEX idx_alerts_type ON performance_alerts(alert_type)',
    'CREATE INDEX idx_alerts_resolved ON performance_alerts(resolved)',
    'CREATE INDEX idx_actual_load_ts ON actual_load_data(timestamp)',
]

for sql in indexes:
    try:
        cursor.execute(sql)
        conn.commit()
    except Exception as e:
        if e.errno != 1061:
            print(f"WARN: {e}")

cursor.close()
conn.close()
print("All indexes created successfully!")
