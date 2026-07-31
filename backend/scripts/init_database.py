#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库初始化脚本 - 一键创建数据库和所有表结构

用法:
    python init_database.py
"""

import os
import sys
import mysql.connector
from mysql.connector import Error as MySQLError

# 从 application.yaml 读取配置（或直接使用默认值）
DB_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'port': int(os.getenv('MYSQL_PORT', 3306)),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', '315131'),
    'database': os.getenv('MYSQL_DATABASE', 'OOOO'),
}

# 如果没有环境变量，尝试从 YAML 读取
if not os.getenv('MYSQL_PASSWORD'):
    try:
        import yaml
        yaml_path = os.path.join(os.path.dirname(__file__), 'config', 'application.yaml')
        if os.path.exists(yaml_path):
            with open(yaml_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
            db_cfg = cfg.get('database', {})
            DB_CONFIG['host'] = db_cfg.get('host', DB_CONFIG['host'])
            DB_CONFIG['port'] = db_cfg.get('port', DB_CONFIG['port'])
            DB_CONFIG['user'] = db_cfg.get('user', DB_CONFIG['user'])
            DB_CONFIG['password'] = db_cfg.get('password', DB_CONFIG['password'])
            DB_CONFIG['database'] = db_cfg.get('database', DB_CONFIG['database'])
            print(f"✅ 从 application.yaml 读取数据库配置成功")
    except ImportError:
        print("⚠️  PyYAML 未安装，使用默认配置")

# 连接参数 (只含 connect() 需要的)
DB_CONNECT_PARAMS = {
    'host': str(DB_CONFIG['host']),
    'port': int(DB_CONFIG['port']),
    'user': str(DB_CONFIG['user']),
    'password': str(DB_CONFIG['password']),
    'use_pure': True,  # 避免 C 扩展在 Python 3.12 上的兼容性问题
}

DATABASE_NAME = DB_CONFIG['database']

# ============================================================
# SQL 建表语句
# ============================================================

CREATE_DATABASE_SQL = f"""
CREATE DATABASE IF NOT EXISTS `{DATABASE_NAME}`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;
"""

TABLES_SQL = [
    # 1. 气象数据表
    """
    CREATE TABLE IF NOT EXISTS weather_data (
        id INT AUTO_INCREMENT PRIMARY KEY,
        timestamp DATETIME NOT NULL,
        location VARCHAR(100) NOT NULL,
        latitude DECIMAL(10, 8) DEFAULT 42.36,
        longitude DECIMAL(11, 8) DEFAULT -71.06,
        temperature_2m DECIMAL(6, 2),
        dew_point_2m DECIMAL(6, 2),
        relative_humidity_2m DECIMAL(5, 2),
        wind_speed_10m DECIMAL(6, 2),
        wind_direction_10m DECIMAL(6, 2),
        wind_gusts_10m DECIMAL(6, 2),
        cloud_cover DECIMAL(5, 2),
        shortwave_radiation DECIMAL(8, 2),
        direct_radiation DECIMAL(8, 2),
        diffuse_radiation DECIMAL(8, 2),
        data_quality_score DECIMAL(3, 2) DEFAULT 0.95,
        is_validated BOOLEAN DEFAULT FALSE,
        data_source VARCHAR(50) DEFAULT 'openmeteo',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT valid_humidity CHECK (relative_humidity_2m >= 0 AND relative_humidity_2m <= 100),
        CONSTRAINT valid_cloud_cover CHECK (cloud_cover >= 0 AND cloud_cover <= 100)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    "CREATE INDEX IF NOT EXISTS idx_weather_timestamp ON weather_data(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_weather_location ON weather_data(location);",
    "CREATE INDEX IF NOT EXISTS idx_weather_location_timestamp ON weather_data(location, timestamp);",

    # 2. 负荷预测结果表 (核心表!)
    """
    CREATE TABLE IF NOT EXISTS load_predictions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        prediction_id CHAR(36) DEFAULT (UUID()),
        prediction_timestamp DATETIME NOT NULL,
        target_timestamp DATETIME NOT NULL,
        load_forecast_mw DECIMAL(10, 3),
        pv_estimation_mw DECIMAL(10, 3),
        net_load_mw DECIMAL(10, 3),
        confidence_lower_mw DECIMAL(10, 3),
        confidence_upper_mw DECIMAL(10, 3),
        model_type VARCHAR(50) DEFAULT 'ensemble',
        model_weights JSON,
        inference_time_ms DECIMAL(10, 3),
        cache_hit BOOLEAN DEFAULT false,
        data_source VARCHAR(50),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT valid_forecast CHECK (load_forecast_mw >= 0)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    "CREATE INDEX IF NOT EXISTS idx_predictions_prediction_timestamp ON load_predictions(prediction_timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_predictions_target_timestamp ON load_predictions(target_timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_predictions_model_type ON load_predictions(model_type);",

    # 3. 模型性能记录表
    """
    CREATE TABLE IF NOT EXISTS model_performance (
        id INT AUTO_INCREMENT PRIMARY KEY,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        model_name VARCHAR(100) NOT NULL,
        model_version VARCHAR(50),
        total_inferences INTEGER DEFAULT 0,
        successful_inferences INTEGER DEFAULT 0,
        failed_inferences INTEGER DEFAULT 0,
        average_inference_time_ms DECIMAL(10, 3),
        mae DECIMAL(10, 3),
        rmse DECIMAL(10, 3),
        mape DECIMAL(6, 4),
        gpu_memory_used_mb DECIMAL(10, 2),
        cpu_utilization_percent DECIMAL(5, 2),
        batch_size INTEGER DEFAULT 1,
        device VARCHAR(20) DEFAULT 'cuda'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    "CREATE INDEX IF NOT EXISTS idx_model_performance_timestamp ON model_performance(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_model_performance_model ON model_performance(model_name);",

    # 4. API请求日志表
    """
    CREATE TABLE IF NOT EXISTS api_request_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        request_id CHAR(36) DEFAULT (UUID()),
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        endpoint VARCHAR(200) NOT NULL,
        method VARCHAR(10) NOT NULL,
        status_code INTEGER,
        response_time_ms DECIMAL(10, 3),
        request_size_bytes INTEGER,
        response_size_bytes INTEGER,
        client_ip VARCHAR(50),
        user_agent VARCHAR(500),
        error_message TEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    "CREATE INDEX IF NOT EXISTS idx_api_logs_timestamp ON api_request_logs(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_api_logs_endpoint ON api_request_logs(endpoint);",
    "CREATE INDEX IF NOT EXISTS idx_api_logs_status ON api_request_logs(status_code);",

    # 5. 系统监控指标表
    """
    CREATE TABLE IF NOT EXISTS system_metrics (
        id INT AUTO_INCREMENT PRIMARY KEY,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        cpu_percent DECIMAL(5, 2),
        cpu_count INTEGER,
        memory_percent DECIMAL(5, 2),
        memory_used_gb DECIMAL(6, 3),
        memory_available_gb DECIMAL(6, 3),
        gpu_available BOOLEAN DEFAULT false,
        gpu_memory_used_mb DECIMAL(10, 2),
        gpu_memory_total_mb DECIMAL(10, 2),
        gpu_utilization_percent DECIMAL(5, 2),
        gpu_temperature_c DECIMAL(5, 2),
        network_bytes_sent BIGINT,
        network_bytes_recv BIGINT,
        disk_usage_percent DECIMAL(5, 2),
        process_count INTEGER,
        active_connections INTEGER
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    "CREATE INDEX IF NOT EXISTS idx_system_metrics_timestamp ON system_metrics(timestamp);",

    # 6. 缓存性能表
    """
    CREATE TABLE IF NOT EXISTS cache_performance (
        id INT AUTO_INCREMENT PRIMARY KEY,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        cache_hits BIGINT DEFAULT 0,
        cache_misses BIGINT DEFAULT 0,
        cache_hit_ratio DECIMAL(6, 5),
        cache_memory_used_mb DECIMAL(10, 2),
        cache_keys_count INTEGER,
        avg_cache_hit_time_ms DECIMAL(10, 3),
        avg_cache_miss_time_ms DECIMAL(10, 3)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,

    # 7. 性能预警表
    """
    CREATE TABLE IF NOT EXISTS performance_alerts (
        id INT AUTO_INCREMENT PRIMARY KEY,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        alert_type VARCHAR(20) NOT NULL,
        metric_name VARCHAR(100) NOT NULL,
        current_value DECIMAL(10, 3),
        threshold DECIMAL(10, 3),
        message TEXT,
        severity INTEGER DEFAULT 3,
        resolved BOOLEAN DEFAULT false,
        resolved_at DATETIME NULL,
        resolved_by VARCHAR(100)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    "CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON performance_alerts(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_alerts_type ON performance_alerts(alert_type);",
    "CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON performance_alerts(resolved);",

    # 8. 用户表 (认证模块)
    """
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) UNIQUE NOT NULL,
        email VARCHAR(100) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(20) DEFAULT 'viewer',
        is_active BOOLEAN DEFAULT TRUE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,

    # 9. 实际负荷数据表 (用于准确性对比)
    """
    CREATE TABLE IF NOT EXISTS actual_load_data (
        id INT AUTO_INCREMENT PRIMARY KEY,
        timestamp DATETIME NOT NULL UNIQUE,
        actual_load_mw DECIMAL(10, 3) NOT NULL,
        region VARCHAR(50) DEFAULT 'NewEngland',
        data_source VARCHAR(50) DEFAULT 'iso_ne',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """,
    "CREATE INDEX IF NOT EXISTS idx_actual_load_timestamp ON actual_load_data(timestamp);",
]


def main():
    print("=" * 60)
    print("  智能电网负荷预测系统 - 数据库初始化")
    print("=" * 60)
    print(f"  主机: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print(f"  用户: {DB_CONFIG['user']}")
    print(f"  数据库: {DATABASE_NAME}")
    print("=" * 60)

    # Step 1: 连接 MySQL（不指定数据库），创建数据库
    print("\n[1/3] 创建数据库...")
    try:
        conn = mysql.connector.connect(**DB_CONNECT_PARAMS)
        cursor = conn.cursor()
        cursor.execute(CREATE_DATABASE_SQL)
        conn.commit()
        print(f"  \u2705 \u6570\u636e\u5e93 '{DATABASE_NAME}' \u5df2\u521b\u5efa\uff08\u6216\u5df2\u5b58\u5728\uff09")
        cursor.close()
        conn.close()
    except MySQLError as e:
        print(f"  ❌ 创建数据库失败: {e}")
        print(f"\n  请检查:")
        print(f"    1. MySQL 服务是否已启动")
        print(f"    2. 用户名/密码是否正确 (当前: {DB_CONFIG['user']}/****)")
        print(f"    3. 端口是否正确 (当前: {DB_CONFIG['port']})")
        sys.exit(1)

    # Step 2: 连接到目标数据库，创建所有表
    print(f"\n[2/3] 创建表结构 (共 {len(TABLES_SQL)} 条语句)...")
    try:
        conn = mysql.connector.connect(database=DATABASE_NAME, **DB_CONNECT_PARAMS)
        cursor = conn.cursor()
        success_count = 0
        for i, sql in enumerate(TABLES_SQL, 1):
            try:
                cursor.execute(sql)
                conn.commit()
                success_count += 1
            except MySQLError as e:
                # 某些 MySQL 版本不支持 CREATE INDEX IF NOT EXISTS，忽略重复索引错误
                if e.errno == 1061:  # Duplicate key name
                    pass
                else:
                    print(f"  ⚠️  语句 {i} 执行警告: {e}")
        cursor.close()
        conn.close()
        print(f"  ✅ 全部表结构创建完成 ({success_count}/{len(TABLES_SQL)} 条成功)")
    except MySQLError as e:
        print(f"  ❌ 创建表失败: {e}")
        sys.exit(1)

    # Step 3: 验证表结构
    print(f"\n[3/3] 验证表结构...")
    try:
        conn = mysql.connector.connect(database=DATABASE_NAME, **DB_CONNECT_PARAMS)
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        print(f"  ✅ 数据库 '{DATABASE_NAME}' 中共有 {len(tables)} 张表:")
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM `{table[0]}`")
            count = cursor.fetchone()[0]
            print(f"     - {table[0]:30s}  ({count} 条记录)")
        cursor.close()
        conn.close()
    except MySQLError as e:
        print(f"  ❌ 验证失败: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  ✅ 数据库初始化完成!")
    print("=" * 60)
    print(f"\n  下一步:")
    print(f"    1. 启动后端:  cd realtime_api && python -m uvicorn app:app --reload --port 8000")
    print(f"    2. 启动前端:  npm run dev")
    print(f"    3. 访问「负荷预测」页面，点击「刷新预测」按钮")
    print(f"    4. 回到「历史数据分析」页面查看记录\n")


if __name__ == '__main__':
    main()
