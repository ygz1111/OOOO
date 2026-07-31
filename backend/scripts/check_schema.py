"""检查数据库中所有表和关键列"""
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
print(f'数据库共有 {len(tables)} 张表/视图')
for t in sorted(tables):
    print(f'  - {t}')

# 检查 users 表结构
print('\n' + '=' * 60)
print('users 表结构:')
try:
    cursor.execute('DESCRIBE users')
    for col in cursor.fetchall():
        print(f'  {col["Field"]:30s} {col["Type"]:30s} {col["Null"]:5s} {col["Default"]}')
except Exception as e:
    print(f'  错误: {e}')

# 检查 performance_alerts 表结构 (可能有 PostgreSQL 语法错误)
print('\n' + '=' * 60)
print('performance_alerts 表结构:')
try:
    cursor.execute('DESCRIBE performance_alerts')
    for col in cursor.fetchall():
        print(f'  {col["Field"]:30s} {col["Type"]:30s} {col["Null"]:5s} {col["Default"]}')
except Exception as e:
    print(f'  错误: {e}')

# 检查 auth 相关表是否存在
print('\n' + '=' * 60)
print('Auth 相关表检查:')
auth_tables = ['roles', 'user_roles', 'user_sessions', 'login_histories',
               'api_access_logs', 'operation_logs', 'permissions', 'role_permissions']
for t in auth_tables:
    exists = t in tables
    print(f'  {t:30s} {"存在" if exists else "不存在"}')

# 检查 load_predictions 是否有 actual_load_mw 列
print('\n' + '=' * 60)
print('load_predictions 表结构:')
cursor.execute('DESCRIBE load_predictions')
for col in cursor.fetchall():
    print(f'  {col["Field"]:30s} {col["Type"]:30s} {col["Null"]:5s}')

cursor.close()
conn.close()
print('\n数据库连接已关闭')
