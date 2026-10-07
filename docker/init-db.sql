-- 智能电网负荷预测系统 - MySQL数据库初始化脚本
-- 创建数据库表结构、索引和初始数据
-- 用于MySQL数据库OOOO


-- =====================================================
-- 1. 气象数据表
-- =====================================================
CREATE TABLE IF NOT EXISTS weather_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    location VARCHAR(100) NOT NULL,
    latitude DECIMAL(10, 8) DEFAULT 42.36,
    longitude DECIMAL(11, 8) DEFAULT -71.06,
    
    -- 主要气象参数
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
    
    -- 数据质量标识
    data_quality_score DECIMAL(3, 2) DEFAULT 0.95,
    is_validated BOOLEAN DEFAULT FALSE,
    
    -- 元数据
    data_source VARCHAR(50) DEFAULT 'openmeteo',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    CONSTRAINT valid_humidity CHECK (relative_humidity_2m >= 0 AND relative_humidity_2m <= 100),
    CONSTRAINT valid_cloud_cover CHECK (cloud_cover >= 0 AND cloud_cover <= 100),
    -- 唯一键: 同一站点同一时刻只保留一条气象记录（配合幂等写入, 避免重复膨胀）
    UNIQUE KEY uq_weather_location_timestamp (location, timestamp)
);

-- 气象数据索引
CREATE INDEX idx_weather_timestamp ON weather_data(timestamp);
CREATE INDEX idx_weather_location ON weather_data(location);
CREATE INDEX idx_weather_location_timestamp ON weather_data(location, timestamp);
CREATE INDEX idx_weather_quality ON weather_data(data_quality_score);

-- =====================================================
-- 2. 负荷预测结果表
-- =====================================================
CREATE TABLE IF NOT EXISTS load_predictions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    prediction_id CHAR(36) DEFAULT (UUID()),
    prediction_timestamp DATETIME NOT NULL,
    target_timestamp DATETIME NOT NULL,
    
    -- 预测值
    load_forecast_mw DECIMAL(10, 3),
    actual_load_mw DECIMAL(10, 3) NULL,
    pv_estimation_mw DECIMAL(10, 3),
    net_load_mw DECIMAL(10, 3),
    
    -- 置信区间
    confidence_lower_mw DECIMAL(10, 3),
    confidence_upper_mw DECIMAL(10, 3),
    
    -- 模型信息
    model_type VARCHAR(50) DEFAULT 'ensemble',
    model_weights JSON,
    
    -- 性能指标
    inference_time_ms DECIMAL(10, 3),
    cache_hit BOOLEAN DEFAULT false,
    data_source VARCHAR(50),
    
    -- 元数据
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT valid_forecast CHECK (load_forecast_mw >= 0),
    -- 唯一键: 同一次预测(prediction_id)的同一目标时刻只保留一条记录
    UNIQUE KEY uq_prediction_target (prediction_id, target_timestamp)
);

-- 负荷预测索引
CREATE INDEX idx_predictions_prediction_timestamp ON load_predictions(prediction_timestamp);
CREATE INDEX idx_predictions_target_timestamp ON load_predictions(target_timestamp);
CREATE INDEX idx_predictions_model_type ON load_predictions(model_type);

-- =====================================================
-- 3. 模型性能记录表
-- =====================================================
CREATE TABLE IF NOT EXISTS model_performance (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- 模型信息
    model_name VARCHAR(100) NOT NULL,
    model_version VARCHAR(50),
    
    -- 性能指标
    total_inferences INTEGER DEFAULT 0,
    successful_inferences INTEGER DEFAULT 0,
    failed_inferences INTEGER DEFAULT 0,
    average_inference_time_ms DECIMAL(10, 3),
    
    -- 准确性指标
    mae DECIMAL(10, 3),
    rmse DECIMAL(10, 3),
    mape DECIMAL(6, 4),
    
    -- 资源使用
    gpu_memory_used_mb DECIMAL(10, 2),
    cpu_utilization_percent DECIMAL(5, 2),
    
    -- 元数据
    batch_size INTEGER DEFAULT 1,
    device VARCHAR(20) DEFAULT 'cuda'
);

-- 模型性能索引
CREATE INDEX idx_model_performance_timestamp ON model_performance(timestamp);
CREATE INDEX idx_model_performance_model ON model_performance(model_name);

-- =====================================================
-- 4. API请求日志表
-- =====================================================
CREATE TABLE IF NOT EXISTS api_request_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    request_id CHAR(36) DEFAULT (UUID()),
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- 请求信息
    endpoint VARCHAR(200) NOT NULL,
    method VARCHAR(10) NOT NULL,
    status_code INTEGER,
    
    -- 性能指标
    response_time_ms DECIMAL(10, 3),
    request_size_bytes INTEGER,
    response_size_bytes INTEGER,
    
    -- 客户端信息
    client_ip VARCHAR(50),
    user_agent VARCHAR(500),
    
    -- 错误信息
    error_message TEXT
);

-- API日志索引
CREATE INDEX idx_api_logs_timestamp ON api_request_logs(timestamp);
CREATE INDEX idx_api_logs_endpoint ON api_request_logs(endpoint);
CREATE INDEX idx_api_logs_status ON api_request_logs(status_code);

-- 认证模块 API 访问日志（auth_crud.log_api_access）
CREATE TABLE IF NOT EXISTS api_access_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    session_id VARCHAR(64) NULL,
    method VARCHAR(10) NOT NULL,
    url VARCHAR(2048) NOT NULL,
    query_params VARCHAR(1024) NULL,
    request_body_hash VARCHAR(64) NULL,
    client_ip VARCHAR(64) NOT NULL,
    user_agent VARCHAR(512) NULL,
    status_code INT NOT NULL,
    response_time_ms INT NULL,
    request_size_bytes INT NULL,
    response_size_bytes INT NULL,
    error_message VARCHAR(1024) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_api_access_created (created_at),
    INDEX idx_api_access_status (status_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- 认证与权限表（与 realtime_api/crud/auth_crud.py 保持一致）
-- =====================================================
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(100) NULL,
    department VARCHAR(100) NULL,
    phone VARCHAR(30) NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_verified BOOLEAN DEFAULT FALSE,
    failed_login_attempts INT DEFAULT 0,
    last_login_at DATETIME NULL,
    password_changed_at DATETIME NULL,
    created_by INT NULL,
    updated_by INT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    description VARCHAR(255) NULL,
    level INT NOT NULL DEFAULT 1,
    is_system_role BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_by INT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS permissions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NULL,
    code VARCHAR(100) NOT NULL UNIQUE,
    description TEXT NULL,
    category VARCHAR(50) NULL,
    resource VARCHAR(50) NULL,
    action VARCHAR(50) NULL,
    is_system_permission BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    role_id INT NOT NULL,
    granted_by INT NULL,
    granted_reason VARCHAR(255) NULL,
    granted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NULL,
    UNIQUE KEY uk_user_role (user_id, role_id),
    KEY idx_user_roles_role (role_id),
    CONSTRAINT fk_user_roles_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_user_roles_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS role_permissions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    role_id INT NOT NULL,
    permission_id INT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_role_permission (role_id, permission_id),
    KEY idx_role_permissions_permission (permission_id),
    CONSTRAINT fk_role_permissions_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
    CONSTRAINT fk_role_permissions_permission FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS login_histories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    login_ip VARCHAR(50) NULL,
    user_agent VARCHAR(500) NULL,
    login_method VARCHAR(30) DEFAULT 'password',
    is_success BOOLEAN DEFAULT TRUE,
    failure_reason VARCHAR(255) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_login_histories_user (user_id),
    KEY idx_login_histories_created (created_at),
    CONSTRAINT fk_login_histories_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    session_id VARCHAR(36) NOT NULL UNIQUE,
    jwt_token TEXT NULL,
    refresh_token TEXT NULL,
    client_ip VARCHAR(50) NULL,
    user_agent VARCHAR(500) NULL,
    platform VARCHAR(50) DEFAULT 'web',
    expires_at DATETIME NULL,
    last_activity DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    revoked_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_user_sessions_user (user_id),
    KEY idx_user_sessions_active_expiry (is_active, expires_at),
    CONSTRAINT fk_user_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS operation_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    session_id VARCHAR(64) NULL,
    operation_type VARCHAR(50) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id VARCHAR(100) NULL,
    description VARCHAR(500) NOT NULL,
    details JSON NULL,
    is_success BOOLEAN DEFAULT TRUE,
    error_message TEXT NULL,
    client_ip VARCHAR(64) NULL,
    user_agent VARCHAR(512) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_operation_logs_user (user_id),
    KEY idx_operation_logs_created (created_at),
    KEY idx_operation_logs_type (operation_type, resource_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 新库必须至少包含注册流程依赖的默认角色和基础权限。
INSERT IGNORE INTO roles (name, description, level, is_system_role) VALUES
('超级管理员', '拥有系统全部权限', 100, TRUE),
('管理员', '系统管理权限', 80, TRUE),
('分析师', '预测与分析权限', 50, TRUE),
('普通用户', '基础查看与预测权限', 10, TRUE);

INSERT IGNORE INTO permissions
    (code, name, description, category, resource, action, is_system_permission)
VALUES
('prediction:view', '查看预测', '查看负荷、电价和光伏预测', 'PREDICTION', 'PREDICTION', 'READ', TRUE),
('prediction:create', '执行预测', '发起预测请求', 'PREDICTION', 'PREDICTION', 'CREATE', TRUE),
('weather:view', '查看气象', '查看气象监测数据', 'WEATHER', 'WEATHER', 'READ', TRUE),
('system:view', '查看系统状态', '查看模型与系统运行状态', 'SYSTEM', 'SYSTEM', 'READ', TRUE),
('analytics:view', '查看分析', '查看历史分析与回测', 'ANALYTICS', 'ANALYTICS', 'READ', TRUE),
('user:manage', '用户管理', '管理用户账户', 'AUTH', 'USER', 'MANAGE', TRUE),
('role:manage', '角色管理', '管理角色和权限', 'AUTH', 'ROLE', 'MANAGE', TRUE);

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name IN ('超级管理员', '管理员');

INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name IN ('分析师', '普通用户')
  AND p.code IN (
      'prediction:view', 'prediction:create', 'weather:view',
      'system:view', 'analytics:view'
  );

-- =====================================================
-- 5. 系统监控指标表
-- =====================================================
CREATE TABLE IF NOT EXISTS system_metrics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- CPU指标
    cpu_percent DECIMAL(5, 2),
    cpu_count INTEGER,
    
    -- 内存指标
    memory_percent DECIMAL(5, 2),
    memory_used_gb DECIMAL(6, 3),
    memory_available_gb DECIMAL(6, 3),
    
    -- GPU指标
    gpu_available BOOLEAN DEFAULT false,
    gpu_memory_used_mb DECIMAL(10, 2),
    gpu_memory_total_mb DECIMAL(10, 2),
    gpu_utilization_percent DECIMAL(5, 2),
    gpu_temperature_c DECIMAL(5, 2),
    
    -- 网络指标
    network_bytes_sent BIGINT,
    network_bytes_recv BIGINT,
    
    -- 磁盘指标
    disk_usage_percent DECIMAL(5, 2),
    
    -- 进程信息
    process_count INTEGER,
    active_connections INTEGER
);

-- 系统指标索引
CREATE INDEX idx_system_metrics_timestamp ON system_metrics(timestamp);

-- =====================================================
-- 6. 缓存性能表
-- =====================================================
CREATE TABLE IF NOT EXISTS cache_performance (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- 缓存指标
    cache_hits BIGINT DEFAULT 0,
    cache_misses BIGINT DEFAULT 0,
    cache_hit_ratio DECIMAL(6, 5),
    
    -- 内存使用
    cache_memory_used_mb DECIMAL(10, 2),
    cache_keys_count INTEGER,
    
    -- 性能
    avg_cache_hit_time_ms DECIMAL(10, 3),
    avg_cache_miss_time_ms DECIMAL(10, 3)
);

-- =====================================================
-- 7. 性能预警表
-- =====================================================
CREATE TABLE IF NOT EXISTS performance_alerts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- 预警信息
    alert_type VARCHAR(20) NOT NULL, -- 'critical', 'warning', 'info'
    metric_name VARCHAR(100) NOT NULL,
    current_value DECIMAL(10, 3),
    threshold DECIMAL(10, 3),
    
    -- 预警内容
    message TEXT,
    severity INTEGER DEFAULT 3, -- 1-5
    
    -- 处理状态
    resolved BOOLEAN DEFAULT false,
    resolved_at TIMESTAMP NULL,
    resolved_by VARCHAR(100)
);

-- 性能预警索引
CREATE INDEX idx_alerts_timestamp ON performance_alerts(timestamp);
CREATE INDEX idx_alerts_type ON performance_alerts(alert_type);
CREATE INDEX idx_alerts_resolved ON performance_alerts(resolved);

-- =====================================================
-- 视图定义
-- =====================================================

-- 最新气象数据视图
DROP VIEW IF EXISTS latest_weather_data;
CREATE VIEW latest_weather_data AS
SELECT 
    location,
    timestamp,
    temperature_2m,
    relative_humidity_2m,
    wind_speed_10m,
    cloud_cover,
    shortwave_radiation,
    data_quality_score
FROM weather_data
WHERE DATE(timestamp) = CURDATE()
ORDER BY location, timestamp DESC;

-- 今日预测结果视图
DROP VIEW IF EXISTS today_predictions;
CREATE VIEW today_predictions AS
SELECT
    prediction_timestamp,
    target_timestamp,
    load_forecast_mw,
    pv_estimation_mw,
    net_load_mw,
    model_type,
    inference_time_ms
FROM load_predictions
WHERE DATE(prediction_timestamp) = CURDATE()
ORDER BY target_timestamp;

-- 系统健康状态视图
DROP VIEW IF EXISTS system_health;
CREATE VIEW system_health AS
SELECT
    timestamp,
    cpu_percent,
    memory_percent,
    gpu_memory_used_mb,
    gpu_utilization_percent
FROM system_metrics
WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
ORDER BY timestamp DESC
LIMIT 100;

-- 认证模块查询视图
DROP VIEW IF EXISTS user_permissions_view;
CREATE VIEW user_permissions_view AS
SELECT DISTINCT
    u.id AS user_id,
    u.username,
    p.code
FROM users u
JOIN user_roles ur ON ur.user_id = u.id
JOIN role_permissions rp ON rp.role_id = ur.role_id
JOIN permissions p ON p.id = rp.permission_id
WHERE u.is_active = TRUE
  AND (ur.expires_at IS NULL OR ur.expires_at > NOW());

DROP VIEW IF EXISTS active_sessions_view;
CREATE VIEW active_sessions_view AS
SELECT
    s.id,
    s.session_id,
    s.user_id,
    u.username,
    s.client_ip,
    s.platform,
    s.last_activity,
    s.expires_at,
    TIMESTAMPDIFF(MINUTE, s.last_activity, NOW()) AS idle_minutes
FROM user_sessions s
JOIN users u ON u.id = s.user_id
WHERE s.is_active = TRUE
  AND s.revoked_at IS NULL
  AND u.is_active = TRUE
  AND s.expires_at > UTC_TIMESTAMP();

DROP VIEW IF EXISTS login_stats_view;
CREATE VIEW login_stats_view AS
SELECT
    u.id AS user_id,
    u.username,
    MAX(CASE WHEN lh.is_success = TRUE THEN lh.created_at END) AS last_login,
    COUNT(CASE WHEN lh.is_success = TRUE THEN 1 END) AS total_logins,
    COUNT(CASE WHEN lh.is_success = FALSE THEN 1 END) AS failed_attempts
FROM users u
LEFT JOIN login_histories lh ON lh.user_id = u.id
GROUP BY u.id, u.username;

-- =====================================================
-- 数据库迁移：补充唯一键（避免重复插入膨胀）
-- (仅对已存在的表生效，新部署已在 CREATE TABLE 中包含)
-- 先删除重复行（保留 id 最小的一条），再添加唯一键
-- =====================================================
DROP PROCEDURE IF EXISTS _add_unique_keys;
DELIMITER //
CREATE PROCEDURE _add_unique_keys()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'weather_data'
          AND INDEX_NAME = 'uq_weather_location_timestamp'
    ) THEN
        DELETE w1 FROM weather_data w1
        JOIN weather_data w2
          ON w1.location = w2.location AND w1.timestamp = w2.timestamp AND w1.id > w2.id;
        ALTER TABLE weather_data ADD UNIQUE KEY uq_weather_location_timestamp (location, timestamp);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'load_predictions'
          AND INDEX_NAME = 'uq_prediction_target'
    ) THEN
        DELETE p1 FROM load_predictions p1
        JOIN load_predictions p2
          ON p1.prediction_id = p2.prediction_id AND p1.target_timestamp = p2.target_timestamp AND p1.id > p2.id;
        ALTER TABLE load_predictions ADD UNIQUE KEY uq_prediction_target (prediction_id, target_timestamp);
    END IF;
END //
DELIMITER ;
CALL _add_unique_keys();
DROP PROCEDURE IF EXISTS _add_unique_keys;

-- =====================================================
-- 实际负荷表 (ISO-NE 真实数据, 用于预测准确性对比/回测)
-- 注: 历史版本缺失该建表语句, 仅靠手工建表; 此处补齐
-- =====================================================
CREATE TABLE IF NOT EXISTS actual_load_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    actual_load_mw DECIMAL(12, 3) NOT NULL,
    region VARCHAR(50) DEFAULT 'NewEngland',
    data_source VARCHAR(50) DEFAULT 'iso_ne',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- 唯一键: 同一区域同一时刻只保留一条真实负荷（配合 INSERT IGNORE 幂等）
    UNIQUE KEY uq_actual_load_time (timestamp, region)
);

CREATE INDEX idx_actual_load_timestamp ON actual_load_data(timestamp);

-- =====================================================
-- 初始数据插入
-- =====================================================

-- 插入示例气象数据
INSERT INTO weather_data (timestamp, location, temperature_2m, relative_humidity_2m, wind_speed_10m, cloud_cover, shortwave_radiation)
VALUES
    (NOW(), 'Boston', 25.5, 65.0, 8.5, 30, 800),
    (DATE_SUB(NOW(), INTERVAL 1 HOUR), 'Boston', 24.8, 68.0, 9.2, 35, 750),
    (NOW(), 'Hartford', 24.2, 70.0, 7.8, 40, 720);

-- =====================================================
-- MySQL用户权限示例（可选）
-- =====================================================

-- CREATE USER IF NOT EXISTS 'smartgrid_readonly'@'%' IDENTIFIED BY 'readonly_password';
-- GRANT SELECT ON OOOO.* TO 'smartgrid_readonly'@'%';

-- CREATE USER IF NOT EXISTS 'smartgrid_readwrite'@'%' IDENTIFIED BY 'readwrite_password';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON OOOO.* TO 'smartgrid_readwrite'@'%';

-- 输出完成信息
SELECT 'Database initialization completed successfully!' AS status;
