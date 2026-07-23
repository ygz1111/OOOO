-- ============================================================================
-- 智能电网负荷预测系统 - 数据库初始化脚本
-- ============================================================================

-- 启用 TimescaleDB 扩展
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================================================
-- 气象数据表
-- ============================================================================
CREATE TABLE IF NOT EXISTS weather_data (
    time        TIMESTAMPTZ NOT NULL,
    location    VARCHAR(50) NOT NULL,
    latitude    FLOAT,
    longitude  FLOAT,
    temperature_2m          FLOAT,
    dew_point_2m            FLOAT,
    relative_humidity_2m    FLOAT,
    wind_speed_10m          FLOAT,
    cloud_cover             FLOAT,
    shortwave_radiation     FLOAT,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

-- 转为 hypertable (按时间分区)
SELECT create_hypertable('weather_data', 'time', if_not_exists => TRUE);

-- 索引
CREATE INDEX IF NOT EXISTS idx_weather_time ON weather_data (time DESC);
CREATE INDEX IF NOT EXISTS idx_weather_location ON weather_data (location, time DESC);

-- ============================================================================
-- 负荷预测结果表
-- ============================================================================
CREATE TABLE IF NOT EXISTS load_predictions (
    id              SERIAL,
    time            TIMESTAMPTZ NOT NULL,
    forecast_hour   INT NOT NULL,
    load_forecast_mw    FLOAT,
    pv_estimation_mw    FLOAT,
    net_load_mw         FLOAT,
    model_ensemble      VARCHAR(100),
    confidence         FLOAT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, time)
);

SELECT create_hypertable('load_predictions', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_predictions_time ON load_predictions (time DESC);

-- ============================================================================
-- 系统状态日志表
-- ============================================================================
CREATE TABLE IF NOT EXISTS system_metrics (
    time            TIMESTAMPTZ NOT NULL,
    service_name    VARCHAR(50),
    cpu_percent     FLOAT,
    memory_mb       FLOAT,
    inference_count INT,
    avg_time_ms     FLOAT,
    status          VARCHAR(20)
);

SELECT create_hypertable('system_metrics', 'time', if_not_exists => TRUE);

-- ============================================================================
-- 储能调度记录
-- ============================================================================
CREATE TABLE IF NOT EXISTS storage_dispatch (
    time            TIMESTAMPTZ NOT NULL,
    charge_mw       FLOAT,
    discharge_mw    FLOAT,
    soc_percent     FLOAT,
    revenue_usd     FLOAT
);

SELECT create_hypertable('storage_dispatch', 'time', if_not_exists => TRUE);

-- 完成提示
\echo '✅ 数据库初始化完成'
