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
    CONSTRAINT valid_cloud_cover CHECK (cloud_cover >= 0 AND cloud_cover <= 100)
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
    pv_estimation_mw DECIMAL(10, 3),
    wind_estimation_mw DECIMAL(10, 3),
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
    
    CONSTRAINT valid_forecast CHECK (load_forecast_mw >= 0)
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
    resolved_at TIMESTAMP WITH TIME ZONE,
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
    wind_estimation_mw,
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

-- =====================================================
-- 数据库迁移：为已有的 load_predictions 表补充 wind_estimation_mw 列
-- (仅对已存在的表生效，新部署已在 CREATE TABLE 中包含)
-- =====================================================
DROP PROCEDURE IF EXISTS _add_wind_column;
DELIMITER //
CREATE PROCEDURE _add_wind_column()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'load_predictions'
          AND COLUMN_NAME = 'wind_estimation_mw'
    ) THEN
        ALTER TABLE load_predictions ADD COLUMN wind_estimation_mw DECIMAL(10, 3) AFTER pv_estimation_mw;
    END IF;
END //
DELIMITER ;
CALL _add_wind_column();
DROP PROCEDURE IF EXISTS _add_wind_column;

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