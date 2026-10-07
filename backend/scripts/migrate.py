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


def extract_create_views(sql_text: str):
    """提取规范视图，并改为可重复执行的 CREATE OR REPLACE VIEW。"""
    pattern = re.compile(
        r"CREATE\s+VIEW\s+(\w+)\s+AS\s+(.*?;)",
        re.IGNORECASE | re.DOTALL,
    )
    return [
        (name, f"CREATE OR REPLACE VIEW `{name}` AS {select_sql}")
        for name, select_sql in pattern.findall(sql_text)
    ]


# 关键列检查（历史迁移：某些列在旧部署的表中缺失）。
# 每一列必须携带与 docker/init-db.sql 一致的 SQL 类型，不能统一按数值列创建。
COLUMN_CHECKS = {
    "load_predictions": {
        "net_load_mw": "DECIMAL(10, 3) NULL",
        "actual_load_mw": "DECIMAL(10, 3) NULL",
        "data_source": "VARCHAR(50) NULL",
    },
    "weather_data": {},
    "model_performance": {},
    "roles": {
        "is_system_role": "BOOLEAN NOT NULL DEFAULT FALSE",
        "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
        "created_by": "INT NULL",
    },
    "permissions": {
        "resource": "VARCHAR(50) NULL",
        "action": "VARCHAR(50) NULL",
        "is_system_permission": "BOOLEAN NOT NULL DEFAULT FALSE",
    },
}

# 已下线功能的遗留列。仅删除风电估算结果，不影响负荷、价格、光伏和气象数据。
LEGACY_COLUMNS_TO_DROP = {
    "load_predictions": ["wind_estimation_mw"],
}


AUTH_SEED_STATEMENTS = [
    """
    INSERT INTO roles (name, description, level, is_system_role) VALUES
    ('超级管理员', '拥有系统全部权限', 100, TRUE),
    ('管理员', '系统管理权限', 80, TRUE),
    ('分析师', '预测与分析权限', 50, TRUE),
    ('普通用户', '基础查看与预测权限', 10, TRUE)
    ON DUPLICATE KEY UPDATE is_system_role = VALUES(is_system_role)
    """,
    """
    INSERT IGNORE INTO permissions
        (code, name, description, category, resource, action, is_system_permission)
    VALUES
    ('prediction:view', '查看预测', '查看负荷、电价和光伏预测', 'PREDICTION', 'PREDICTION', 'READ', TRUE),
    ('prediction:create', '执行预测', '发起预测请求', 'PREDICTION', 'PREDICTION', 'CREATE', TRUE),
    ('weather:view', '查看气象', '查看气象监测数据', 'WEATHER', 'WEATHER', 'READ', TRUE),
    ('system:view', '查看系统状态', '查看模型与系统运行状态', 'SYSTEM', 'SYSTEM', 'READ', TRUE),
    ('analytics:view', '查看分析', '查看历史分析与回测', 'ANALYTICS', 'ANALYTICS', 'READ', TRUE),
    ('user:manage', '用户管理', '管理用户账户', 'AUTH', 'USER', 'MANAGE', TRUE),
    ('role:manage', '角色管理', '管理角色和权限', 'AUTH', 'ROLE', 'MANAGE', TRUE)
    """,
    """
    INSERT IGNORE INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
    WHERE r.name IN ('超级管理员', '管理员')
    """,
    """
    INSERT IGNORE INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
    WHERE r.name IN ('分析师', '普通用户')
      AND p.code IN (
          'prediction:view', 'prediction:create', 'weather:view',
          'system:view', 'analytics:view'
      )
    """,
]


def main():
    parser = argparse.ArgumentParser(description="幂等数据库迁移")
    parser.add_argument("--host", default=os.getenv("MYSQL_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MYSQL_PORT", 3306)))
    parser.add_argument("--database", default=os.getenv("MYSQL_DATABASE", "OOOO"))
    parser.add_argument("--user", default=os.getenv("MYSQL_USER", "root"))
    parser.add_argument("--password", default=os.getenv("MYSQL_PASSWORD", ""))
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_]+", args.database):
        parser.error("database 仅允许字母、数字和下划线")

    if not os.path.exists(INIT_SQL):
        print(f"❌ init-db.sql 未找到: {INIT_SQL}")
        sys.exit(1)

    conn = mysql.connector.connect(
        host=args.host, port=args.port,
        user=args.user, password=args.password, connect_timeout=10,
        use_pure=True,  # 纯 Python 实现，避免 C 扩展 multi-statement 状态问题
    )
    cur = conn.cursor()
    failures = []

    # 新安装环境可能尚未创建数据库；先在服务级连接上幂等创建，再切换 schema。
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{args.database}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    cur.execute(f"USE `{args.database}`")

    # 1. 建表（幂等）
    with open(INIT_SQL, encoding="utf-8") as sql_file:
        sql_text = sql_file.read()
    tables = extract_create_tables(sql_text)
    print(f"发现 {len(tables)} 个 CREATE TABLE 语句")
    for stmt in tables:
        name = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", stmt, re.I).group(1)
        try:
            cur.execute(stmt)
            print(f"  ✅ 表 {name} 就绪")
        except Exception as e:
            print(f"  ❌ 表 {name} 失败: {e}")
            failures.append(f"创建表 {name}: {e}")
    conn.commit()

    # 2. 列级检查（幂等补列）
    for table, columns in COLUMN_CHECKS.items():
        for col, sql_type in columns.items():
            cur.execute(
                """SELECT COUNT(*) FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
                (args.database, table, col),
            )
            if cur.fetchone()[0] == 0:
                try:
                    cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col}` {sql_type}")
                    print(f"  ➕ 表 {table} 补列 {col}")
                except Exception as e:
                    print(f"  ❌ 表 {table} 补列 {col} 失败: {e}")
                    failures.append(f"表 {table} 补列 {col}: {e}")
    conn.commit()

    # 3. 补齐注册、登录和 RBAC 所需的基础角色/权限（幂等且不创建默认账号）。
    for index, statement in enumerate(AUTH_SEED_STATEMENTS, start=1):
        try:
            cur.execute(statement)
        except Exception as e:
            print(f"  ❌ 认证基础数据第 {index} 组写入失败: {e}")
            failures.append(f"认证基础数据第 {index} 组: {e}")
    conn.commit()

    # 4. 清理已下线功能的遗留列
    for table, cols in LEGACY_COLUMNS_TO_DROP.items():
        for col in cols:
            cur.execute(
                """SELECT COUNT(*) FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
                (args.database, table, col),
            )
            if cur.fetchone()[0] > 0:
                try:
                    cur.execute(f"ALTER TABLE `{table}` DROP COLUMN `{col}`")
                    print(f"  ➖ 表 {table} 删除遗留列 {col}")
                except Exception as e:
                    print(f"  ❌ 表 {table} 删除遗留列 {col} 失败: {e}")
                    failures.append(f"表 {table} 删除遗留列 {col}: {e}")
    conn.commit()

    # 5. 重建规范视图。旧版本视图可能仍引用已删除的 wind_estimation_mw，
    # DROP 列后若不刷新视图，任何查询都会报 MySQL 1356。
    for view_name, statement in extract_create_views(sql_text):
        try:
            cur.execute(statement)
            print(f"  ✅ 视图 {view_name} 已刷新")
        except Exception as e:
            print(f"  ❌ 视图 {view_name} 刷新失败: {e}")
            failures.append(f"刷新视图 {view_name}: {e}")
    conn.commit()

    # 6. 报告基础表清单；不对视图 COUNT，避免项目之外的失效旧视图干扰迁移。
    cur.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
    all_tables = sorted(r[0] for r in cur.fetchall())
    print(f"\n当前数据库 {args.database} 共 {len(all_tables)} 张基础表:")
    for t in all_tables:
        cur.execute(f"SELECT COUNT(*) FROM `{t}`")
        print(f"  - {t}: {cur.fetchone()[0]} 行")

    cur.close()
    conn.close()
    if failures:
        print(f"\n❌ 迁移未完整完成，共 {len(failures)} 项失败：")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\n✅ 迁移完成（幂等，可重复运行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
