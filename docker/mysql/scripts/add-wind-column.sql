-- =====================================================
-- 迁移脚本：为 load_predictions 表添加 wind_estimation_mw 列
-- 用途：在已有数据库上执行，补充风电估算字段
-- 执行方式：
--   docker exec -i oooooo-mysql mysql -uroot -proot smartgrid < docker/mysql/scripts/add-wind-column.sql
--   或在 MySQL 客户端中直接执行
-- =====================================================

USE smartgrid;

-- 安全添加列（如果不存在）
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
        SELECT 'wind_estimation_mw 列添加成功' AS message;
    ELSE
        SELECT 'wind_estimation_mw 列已存在，跳过' AS message;
    END IF;
END //
DELIMITER ;
CALL _add_wind_column();
DROP PROCEDURE IF EXISTS _add_wind_column;

-- 更新 today_predictions 视图（如果存在）
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

SELECT '迁移完成' AS message;
