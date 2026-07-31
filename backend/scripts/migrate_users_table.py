#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库迁移脚本 - 修复 users 表 schema 并创建 auth 相关表

问题:
  1. users 表使用 password_hash，但 auth_crud.py 期望 hashed_password
  2. users 表缺少 full_name, department, phone, created_by, failed_login_attempts,
     last_login_at, password_changed_at 等列
  3. auth 模块需要的 roles, user_roles, user_sessions, login_histories 等表不存在

用法:
    python scripts/migrate_users_table.py
"""

import os
import sys
import mysql.connector
from mysql.connector import Error as MySQLError
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

DB_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'port': int(os.getenv('MYSQL_PORT', 3306)),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', ''),
    'database': os.getenv('MYSQL_DATABASE', 'OOOO'),
    'use_pure': True,
}


def column_exists(cursor, table, column):
    """检查列是否存在"""
    cursor.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (column,))
    return cursor.fetchone() is not None


def table_exists(cursor, table):
    """检查表是否存在"""
    cursor.execute("SHOW TABLES LIKE %s", (table,))
    return cursor.fetchone() is not None


def main():
    print("=" * 60)
    print("  数据库迁移 - 修复 users 表 & 创建 auth 相关表")
    print("=" * 60)

    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()

    # ============================================================
    # 1. 修复 users 表
    # ============================================================
    print("\n[1/6] 修复 users 表结构...")

    # 1a. 重命名 password_hash -> hashed_password
    if column_exists(cursor, 'users', 'password_hash') and not column_exists(cursor, 'users', 'hashed_password'):
        cursor.execute("ALTER TABLE users CHANGE COLUMN password_hash hashed_password VARCHAR(255) NOT NULL")
        print("  -> 已重命名 password_hash -> hashed_password")
    else:
        print("  -> hashed_password 列已存在，跳过")

    # 1b. 添加缺失的列
    new_columns = [
        ("full_name", "VARCHAR(100) NULL"),
        ("department", "VARCHAR(100) NULL"),
        ("phone", "VARCHAR(30) NULL"),
        ("created_by", "INT NULL"),
        ("updated_by", "INT NULL"),
        ("failed_login_attempts", "INT DEFAULT 0"),
        ("last_login_at", "DATETIME NULL"),
        ("password_changed_at", "DATETIME NULL"),
        ("is_verified", "BOOLEAN DEFAULT FALSE"),
    ]

    for col_name, col_def in new_columns:
        if not column_exists(cursor, 'users', col_name):
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
            print(f"  -> 已添加列: {col_name} ({col_def})")
        else:
            print(f"  -> 列 {col_name} 已存在，跳过")

    conn.commit()
    print("  [OK] users 表修复完成")

    # ============================================================
    # 2. 创建 roles 表
    # ============================================================
    print("\n[2/6] 创建 roles 表...")
    if not table_exists(cursor, 'roles'):
        cursor.execute("""
            CREATE TABLE roles (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(50) UNIQUE NOT NULL,
                description VARCHAR(200),
                level INT DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_by INT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        # 插入默认角色
        cursor.execute("""
            INSERT INTO roles (name, description, level) VALUES
                ('超级管理员', '系统最高权限', 100),
                ('管理员', '系统管理权限', 80),
                ('分析师', '数据分析权限', 50),
                ('普通用户', '基本查看权限', 10)
        """)
        conn.commit()
        print("  [OK] roles 表创建完成 (含4个默认角色)")
    else:
        print("  -> roles 表已存在，跳过")

    # ============================================================
    # 3. 创建 user_roles 表
    # ============================================================
    print("\n[3/6] 创建 user_roles 表...")
    if not table_exists(cursor, 'user_roles'):
        cursor.execute("""
            CREATE TABLE user_roles (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                role_id INT NOT NULL,
                granted_by INT,
                granted_reason VARCHAR(200),
                granted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                UNIQUE KEY uk_user_role (user_id, role_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        conn.commit()
        print("  [OK] user_roles 表创建完成")
    else:
        print("  -> user_roles 表已存在，跳过")

    # ============================================================
    # 4. 创建 permissions 表
    # ============================================================
    print("\n[4/6] 创建 permissions 表...")
    if not table_exists(cursor, 'permissions'):
        cursor.execute("""
            CREATE TABLE permissions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                code VARCHAR(100) UNIQUE NOT NULL,
                name VARCHAR(200),
                description TEXT,
                category VARCHAR(50),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        # 插入默认权限
        cursor.execute("""
            INSERT INTO permissions (code, name, category) VALUES
                ('prediction:view', '查看预测', 'prediction'),
                ('prediction:create', '创建预测', 'prediction'),
                ('weather:view', '查看气象', 'weather'),
                ('system:view', '查看系统状态', 'system'),
                ('analytics:view', '查看分析', 'analytics'),
                ('user:manage', '用户管理', 'admin'),
                ('role:manage', '角色管理', 'admin')
        """)
        conn.commit()
        print("  [OK] permissions 表创建完成 (含7个默认权限)")
    else:
        print("  -> permissions 表已存在，跳过")

    # ============================================================
    # 5. 创建 role_permissions 表
    # ============================================================
    print("\n[5/6] 创建 role_permissions 表...")
    if not table_exists(cursor, 'role_permissions'):
        cursor.execute("""
            CREATE TABLE role_permissions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                role_id INT NOT NULL,
                permission_id INT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE,
                UNIQUE KEY uk_role_perm (role_id, permission_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        conn.commit()
        print("  [OK] role_permissions 表创建完成")
    else:
        print("  -> role_permissions 表已存在，跳过")

    # ============================================================
    # 6. 创建 user_sessions 和 login_histories 表
    # ============================================================
    print("\n[6/6] 创建 user_sessions 和 login_histories 表...")

    if not table_exists(cursor, 'user_sessions'):
        cursor.execute("""
            CREATE TABLE user_sessions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                session_id VARCHAR(36) UNIQUE NOT NULL,
                jwt_token TEXT,
                refresh_token TEXT,
                client_ip VARCHAR(50),
                user_agent VARCHAR(500),
                platform VARCHAR(50) DEFAULT 'web',
                is_active BOOLEAN DEFAULT TRUE,
                expires_at DATETIME,
                last_activity DATETIME DEFAULT CURRENT_TIMESTAMP,
                revoked_at DATETIME NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        conn.commit()
        print("  [OK] user_sessions 表创建完成")
    else:
        print("  -> user_sessions 表已存在，跳过")

    if not table_exists(cursor, 'login_histories'):
        cursor.execute("""
            CREATE TABLE login_histories (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT,
                login_ip VARCHAR(50),
                user_agent VARCHAR(500),
                login_method VARCHAR(30) DEFAULT 'password',
                is_success BOOLEAN DEFAULT TRUE,
                failure_reason VARCHAR(200),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        conn.commit()
        print("  [OK] login_histories 表创建完成")
    else:
        print("  -> login_histories 表已存在，跳过")

    # ============================================================
    # 创建视图 (如果不存在)
    # ============================================================
    print("\n[额外] 创建辅助视图...")

    # user_permissions_view
    try:
        cursor.execute("DROP VIEW IF EXISTS user_permissions_view")
        cursor.execute("""
            CREATE VIEW user_permissions_view AS
            SELECT DISTINCT
                u.id AS user_id,
                u.username,
                p.code
            FROM users u
            JOIN user_roles ur ON u.id = ur.user_id
            JOIN role_permissions rp ON ur.role_id = rp.role_id
            JOIN permissions p ON rp.permission_id = p.id
            WHERE u.is_active = TRUE
              AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
        """)
        print("  [OK] user_permissions_view 视图创建完成")
    except MySQLError as e:
        print(f"  [WARN] user_permissions_view 创建失败: {e}")

    # active_sessions_view
    try:
        cursor.execute("DROP VIEW IF EXISTS active_sessions_view")
        cursor.execute("""
            CREATE VIEW active_sessions_view AS
            SELECT
                s.id, s.session_id, s.user_id, u.username,
                s.client_ip, s.platform, s.last_activity, s.expires_at,
                TIMESTAMPDIFF(MINUTE, s.last_activity, NOW()) AS idle_minutes
            FROM user_sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.is_active = TRUE AND s.expires_at > NOW()
        """)
        print("  [OK] active_sessions_view 视图创建完成")
    except MySQLError as e:
        print(f"  [WARN] active_sessions_view 创建失败: {e}")

    # login_stats_view
    try:
        cursor.execute("DROP VIEW IF EXISTS login_stats_view")
        cursor.execute("""
            CREATE VIEW login_stats_view AS
            SELECT
                u.id AS user_id, u.username,
                MAX(CASE WHEN lh.is_success = 1 THEN lh.created_at END) AS last_login,
                COUNT(CASE WHEN lh.is_success = 1 THEN 1 END) AS total_logins,
                COUNT(CASE WHEN lh.is_success = 0 THEN 1 END) AS failed_attempts
            FROM users u
            LEFT JOIN login_histories lh ON u.id = lh.user_id
            GROUP BY u.id, u.username
        """)
        print("  [OK] login_stats_view 视图创建完成")
    except MySQLError as e:
        print(f"  [WARN] login_stats_view 创建失败: {e}")

    conn.commit()

    # ============================================================
    # 验证
    # ============================================================
    print("\n" + "=" * 60)
    print("迁移完成! 当前数据库表列表:")
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    for t in tables:
        cursor.execute(f"SELECT COUNT(*) FROM `{t[0]}`")
        count = cursor.fetchone()[0]
        print(f"  {t[0]:35s}  {count:>6} 行")

    # 验证 users 表结构
    print("\nusers 表结构:")
    cursor.execute("DESCRIBE users")
    for col in cursor.fetchall():
        print(f"  {col[0]:30s} {col[1]}")

    cursor.close()
    conn.close()
    print("\n[OK] 迁移脚本执行完成")


if __name__ == '__main__':
    main()
