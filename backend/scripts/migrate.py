#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
幂等数据库迁移脚本：确保 schema 完整（可重复运行）

设计：
- 从 docker/init-db.sql 提取所有 `CREATE TABLE IF NOT EXISTS` 块，逐条执行（幂等）
- 检查 load_predictions 关键列，缺失则 ALTER ADD（幂等）
- 跳过 INSERT 示例数据（避免重复插入）与存储过程（列级检查替代）

用法：
    cd backend
    python scripts/migrate.py [--host localhost --port 3306 --database OOOO]
"""
import argparse
import os
import re
import sys

import mysql.connector
from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 加载项目根目录 .env（MYSQL_HOST/PASSWORD 等）
load_dotenv(os.path.join(BACKEND_DIR, "..", ".env"))
INIT_SQL = os.path.join(BACKEND_DIR, "..", "docker", "init-db.sql")


def extract_create_tables(sql_text: str):
    """提取所有 CREATE TABLE IF NOT EXISTS 语句块"""
    pattern = re.compile(
        r"(CREATE TABLE IF NOT EXISTS \w+ \(.*?\)\s*(?:ENGINE[^;]*)?;)",
        re.IGNORECASE | re.DOTALL,
    )
    return pattern.findall(sql_text)


# 关键列检查（历史迁移：某些列在旧部署的表中缺失）
COLUMN_CHECKS = {
    "load_predictions": ["wind_estimation_mw", "net_load_mw", "data_source"],
    "weather_data": [],
    "model_performance": [],
}


def main():
    parser = argparse.ArgumentParser(description="幂等数据库迁移")
    parser.add_argument("--host", default=os.getenv("MYSQL_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MYSQL_PORT", 3306)))
    parser.add_argument("--database", default=os.getenv("MYSQL_DATABASE", "OOOO"))
    parser.add_argument("--user", default=os.getenv("MYSQL_USER", "root"))
    parser.add_argument("--password", default=os.getenv("MYSQL_PASSWORD", ""))
    args = parser.parse_args()

    if not os.path.exists(INIT_SQL):
        print(f"❌ init-db.sql 未找到: {INIT_SQL}")
        sys.exit(1)

    conn = mysql.connector.connect(
        host=args.host, port=args.port, database=args.database,
        user=args.user, password=args.password, connect_timeout=10,
        use_pure=True,  # 纯 Python 实现，避免 C 扩展 multi-statement 状态问题
    )
    cur = conn.cursor()

    # 1. 建表（幂等）
    sql_text = open(INIT_SQL, encoding="utf-8").read()
    tables = extract_create_tables(sql_text)
    print(f"发现 {len(tables)} 个 CREATE TABLE 语句")
    for stmt in tables:
        name = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", stmt, re.I).group(1)
        try:
            cur.execute(stmt)
            print(f"  ✅ 表 {name} 就绪")
        except Exception as e:
            print(f"  ❌ 表 {name} 失败: {e}")
    conn.commit()

    # 2. 列级检查（幂等补列）
    for table, cols in COLUMN_CHECKS.items():
        for col in cols:
            cur.execute(
                """SELECT COUNT(*) FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
                (args.database, table, col),
            )
            if cur.fetchone()[0] == 0:
                try:
                    cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col}` DECIMAL(10, 3) NULL")
                    print(f"  ➕ 表 {table} 补列 {col}")
                except Exception as e:
                    print(f"  ❌ 表 {table} 补列 {col} 失败: {e}")
    conn.commit()

    # 3. 报告表清单
    cur.execute("SHOW TABLES")
    all_tables = sorted(r[0] for r in cur.fetchall())
    print(f"\n当前数据库 {args.database} 共 {len(all_tables)} 张表:")
    for t in all_tables:
        cur.execute(f"SELECT COUNT(*) FROM `{t}`")
        print(f"  - {t}: {cur.fetchone()[0]} 行")

    conn.close()
    print("\n✅ 迁移完成（幂等，可重复运行）")


if __name__ == "__main__":
    main()
