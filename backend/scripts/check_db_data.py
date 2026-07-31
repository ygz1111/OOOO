"""快速检查数据库各表数据量"""
import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv('.env')

conn = mysql.connector.connect(
    host=os.getenv('MYSQL_HOST', 'localhost'),
    port=int(os.getenv('MYSQL_PORT', '3306')),
    database=os.getenv('MYSQL_DATABASE', 'OOOO'),
    user=os.getenv('MYSQL_USER', 'root'),
    password=os.getenv('MYSQL_PASSWORD', ''),
    use_pure=True,
)
cursor = conn.cursor(dictionary=True)

# 列出所有表
cursor.execute('SHOW TABLES')
tables = [list(row.values())[0] for row in cursor.fetchall()]
print('=' * 60)
print(f'数据库 OOOO 共有 {len(tables)} 张表/视图')
print('=' * 60)

for table in sorted(tables):
    try:
        cursor.execute(f'SELECT COUNT(*) as cnt FROM `{table}`')
        cnt = cursor.fetchone()['cnt']
        print(f'  {table:35s}  {cnt:>6} 行')
    except Exception as e:
        print(f'  {table:35s}  (无法计数: {e})')

# 检查关键表的最新记录
print()
print('=' * 60)
print('关键表最新记录')
print('=' * 60)

for table in ['load_predictions', 'weather_data', 'system_metrics',
              'api_request_logs', 'model_performance']:
    try:
        cursor.execute(f'SELECT * FROM `{table}` ORDER BY id DESC LIMIT 3')
        rows = cursor.fetchall()
        if rows:
            print(f'\n--- {table} (最新3条) ---')
            for r in rows:
                show = {k: v for k, v in r.items() if k in (
                    'id', 'timestamp', 'prediction_timestamp', 'target_timestamp',
                    'location', 'load_forecast_mw', 'pv_estimation_mw',
                    'temperature_2m', 'shortwave_radiation', 'created_at',
                    'model_type', 'inference_time_ms'
                )}
                print(f'  {show}')
        else:
            print(f'\n--- {table}: 空 ---')
    except Exception as e:
        print(f'\n--- {table}: 查询失败 {e} ---')

cursor.close()
conn.close()
print('\n数据库连接已关闭')
