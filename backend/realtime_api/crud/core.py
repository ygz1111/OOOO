"""
智能电网负荷预测系统 - 数据库CRUD操作

提供针对各表的增删改查操作：
- weather_data: 气象数据操作
- load_predictions: 预测结果操作
- model_performance: 模型性能操作
- api_request_logs: API日志操作
- system_metrics: 系统监控指标操作
- cache_performance: 缓存性能操作
- performance_alerts: 性能预警操作

作者: 毕业设计项目
"""

import uuid
import logging
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from realtime_api.database import db_manager
from realtime_api.utils.iso_ne_intervals import ACTUAL_REGION, ACTUAL_SOURCE, actual_label_sql

# 配置日志
logger = logging.getLogger("crud")


class WeatherDataCRUD:
    """气象数据操作"""

    @staticmethod
    async def insert_weather_data(
        timestamp: datetime,
        location: str,
        temperature_2m: Optional[float] = None,
        dew_point_2m: Optional[float] = None,
        relative_humidity_2m: Optional[float] = None,
        wind_speed_10m: Optional[float] = None,
        wind_direction_10m: Optional[float] = None,
        wind_gusts_10m: Optional[float] = None,
        cloud_cover: Optional[float] = None,
        shortwave_radiation: Optional[float] = None,
        direct_radiation: Optional[float] = None,
        diffuse_radiation: Optional[float] = None,
        data_quality_score: float = 0.95,
        is_validated: bool = False,
        data_source: str = 'openmeteo',
        latitude: float = 42.36,
        longitude: float = -71.06
    ) -> int:
        """插入气象数据"""
        # ON DUPLICATE KEY UPDATE + (location, timestamp) 唯一键:
        # 同一站点同一时刻重复写入时更新气象值（幂等, 避免重复膨胀）
        sql = """
        INSERT INTO weather_data (
            timestamp, location, temperature_2m, dew_point_2m,
            relative_humidity_2m, wind_speed_10m, wind_direction_10m,
            wind_gusts_10m, cloud_cover, shortwave_radiation, direct_radiation,
            diffuse_radiation, data_quality_score, is_validated, data_source,
            latitude, longitude
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            temperature_2m = VALUES(temperature_2m),
            dew_point_2m = VALUES(dew_point_2m),
            relative_humidity_2m = VALUES(relative_humidity_2m),
            wind_speed_10m = VALUES(wind_speed_10m),
            wind_direction_10m = VALUES(wind_direction_10m),
            wind_gusts_10m = VALUES(wind_gusts_10m),
            cloud_cover = VALUES(cloud_cover),
            shortwave_radiation = VALUES(shortwave_radiation),
            direct_radiation = VALUES(direct_radiation),
            diffuse_radiation = VALUES(diffuse_radiation),
            data_quality_score = VALUES(data_quality_score),
            is_validated = VALUES(is_validated),
            data_source = VALUES(data_source),
            latitude = VALUES(latitude),
            longitude = VALUES(longitude)
        """
        params = (
            timestamp, location, temperature_2m, dew_point_2m,
            relative_humidity_2m, wind_speed_10m, wind_direction_10m,
            wind_gusts_10m, cloud_cover, shortwave_radiation, direct_radiation,
            diffuse_radiation, data_quality_score, is_validated, data_source,
            latitude, longitude
        )

        try:
            insert_id = await db_manager.execute_sql_insert(sql, params)
            logger.info(f"成功插入气象数据 - ID: {insert_id}, 位置: {location}, 时间: {timestamp}")
            return insert_id
        except Exception as e:
            logger.error(f"插入气象数据失败: {str(e)}")
            raise

    @staticmethod
    async def get_weather_by_location_and_time(
        location: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """按位置和时间范围查询气象数据"""
        sql = """
        SELECT id, timestamp, location, temperature_2m, relative_humidity_2m,
               wind_speed_10m, cloud_cover, shortwave_radiation,
               data_quality_score, is_validated
        FROM weather_data
        WHERE location = %s AND timestamp BETWEEN %s AND %s
        ORDER BY timestamp DESC
        """

        try:
            result = await db_manager.execute_sql(sql, (location, start_time, end_time))
            return result
        except Exception as e:
            logger.error(f"查询气象数据失败: {str(e)}")
            raise

    @staticmethod
    async def get_latest_weather_data(location: str, limit: int = 24) -> List[Dict[str, Any]]:
        """获取最新的气象数据"""
        sql = """
        SELECT id, timestamp, location, temperature_2m, relative_humidity_2m,
               wind_speed_10m, cloud_cover, shortwave_radiation,
               data_quality_score, is_validated
        FROM weather_data
        WHERE location = %s AND data_quality_score >= 0.9
        ORDER BY timestamp DESC
        LIMIT %s
        """

        try:
            return await db_manager.execute_sql(sql, (location, limit))
        except Exception as e:
            logger.error(f"查询最新气象数据失败: {str(e)}")
            raise


class LoadPredictionsCRUD:
    """负荷预测结果操作"""

    @staticmethod
    async def insert_prediction(
        prediction_timestamp: datetime,
        target_timestamp: datetime,
        load_forecast_mw: float,
        pv_estimation_mw: Optional[float] = None,
        net_load_mw: Optional[float] = None,
        confidence_lower_mw: Optional[float] = None,
        confidence_upper_mw: Optional[float] = None,
        model_type: str = 'ensemble',
        model_weights: Optional[Dict[str, Any]] = None,
        inference_time_ms: Optional[float] = None,
        cache_hit: bool = False,
        data_source: Optional[str] = None,
        prediction_id: Optional[str] = None
    ) -> int:
        """插入预测结果

        Args:
            prediction_id: 本次预测请求的唯一标识 (UUID)，
                           同一次预测的 24 条记录共享同一个 ID
        """
        model_weights_json = json.dumps(model_weights) if model_weights else None

        # INSERT IGNORE + (prediction_id, target_timestamp) 唯一键:
        # 同一预测请求的同一目标时刻重复插入时静默跳过, 避免重复数据膨胀
        sql = """
        INSERT IGNORE INTO load_predictions (
            prediction_id, prediction_timestamp, target_timestamp, load_forecast_mw,
            pv_estimation_mw, net_load_mw, confidence_lower_mw,
            confidence_upper_mw, model_type, model_weights,
            inference_time_ms, cache_hit, data_source
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        params = (
            prediction_id, prediction_timestamp, target_timestamp, load_forecast_mw,
            pv_estimation_mw, net_load_mw, confidence_lower_mw,
            confidence_upper_mw, model_type, model_weights_json,
            inference_time_ms, cache_hit, data_source
        )

        try:
            insert_id = await db_manager.execute_sql_insert(sql, params)
            logger.info(f"成功插入负荷预测 - ID: {insert_id}, 目标时间: {target_timestamp}, "
                       f"预测负荷: {load_forecast_mw}MW")
            return insert_id
        except Exception as e:
            logger.error(f"插入负荷预测失败: {str(e)}")
            raise

    @staticmethod
    async def get_predictions_by_time_range(
        start_time: datetime,
        end_time: datetime,
        model_type: Optional[str] = None,
        limit: Optional[int] = None,
        order_desc: bool = False,
        dedupe_target: bool = False,
        causal_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """按时间范围查询预测结果

        Args:
            limit:  最多返回的记录数 (None = 不限制)
            order_desc:  True 时按时间降序 (最新在前)，默认 False 升序
            dedupe_target: True 时按 target_timestamp 去重，每个目标时刻只保留
                最新一次预测（prediction_timestamp 最大，其次 id 最大）。
                2026-08 修复：同一 target_timestamp 可能因多次预测请求存在多条记录，
                统计端点若不去重会把同一小时的真实值重复计数，导致 MAE/MAPE 失真。
            causal_only: True 时排除目标时刻之后才生成的记录。这样的记录不是
                可用于在线评估的真实预测，不能参与历史误差统计。
        """
        order_clause = "ORDER BY target_timestamp DESC" if order_desc else "ORDER BY target_timestamp ASC"
        limit_clause = f"LIMIT {int(limit)}" if limit is not None else ""

        where = "target_timestamp BETWEEN %s AND %s"
        if model_type:
            where += " AND model_type = %s"
        if causal_only:
            where += " AND prediction_timestamp < target_timestamp"

        # Never evaluate TF hour-ending zonal forecasts against legacy system
        # load/hour-start labels. Keep legacy rows intact, join verified labels.
        alias = "t" if dedupe_target else "load_predictions"
        actual_label = actual_label_sql(alias)
        _cols = (
            "id, prediction_id, prediction_timestamp, target_timestamp, "
            "load_forecast_mw, pv_estimation_mw, net_load_mw, "
            "confidence_lower_mw, confidence_upper_mw, model_type, "
            "inference_time_ms, cache_hit, data_source, created_at, "
            f"{actual_label} AS actual_load_mw"
        )

        if dedupe_target:
            sql = f"""
            SELECT {_cols}
            FROM (
                SELECT lp.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY target_timestamp
                           ORDER BY prediction_timestamp DESC, id DESC
                       ) AS __rn
                FROM load_predictions lp
                WHERE {where}
            ) t
            WHERE __rn = 1
            {order_clause}
            {limit_clause}
            """
        else:
            sql = f"""
            SELECT {_cols}
            FROM load_predictions
            WHERE {where}
            {order_clause}
            {limit_clause}
            """

        if model_type:
            params = (start_time, end_time, model_type)
        else:
            params = (start_time, end_time)

        try:
            return await db_manager.execute_sql(sql, params)
        except Exception as e:
            logger.error(f"查询预测结果失败: {str(e)}")
            raise

    @staticmethod
    async def get_latest_predictions(limit: int = 24) -> List[Dict[str, Any]]:
        """获取最新的有效在线预测结果。"""
        sql = f"""
        SELECT id, prediction_id, prediction_timestamp, target_timestamp,
               load_forecast_mw, pv_estimation_mw, net_load_mw,
               confidence_lower_mw, confidence_upper_mw, model_type,
               inference_time_ms, cache_hit, data_source, created_at,
               {actual_label_sql()} AS actual_load_mw
        FROM load_predictions
        WHERE prediction_timestamp < target_timestamp
        ORDER BY prediction_timestamp DESC, target_timestamp DESC
        LIMIT %s
        """

        try:
            return await db_manager.execute_sql(sql, (limit,))
        except Exception as e:
            logger.error(f"查询最新预测结果失败: {str(e)}")
            raise

    @staticmethod
    async def get_predictions_by_prediction_id(prediction_id: str) -> List[Dict[str, Any]]:
        """按预测ID查询"""
        sql = """
        SELECT id, prediction_id, prediction_timestamp, target_timestamp,
               load_forecast_mw, pv_estimation_mw, net_load_mw,
               confidence_lower_mw, confidence_upper_mw, model_type,
               model_weights, inference_time_ms, cache_hit, data_source, created_at
        FROM load_predictions
        WHERE prediction_id = %s
        ORDER BY target_timestamp ASC
        """

        try:
            result = await db_manager.execute_sql(sql, (prediction_id,))
            for row in result:
                if row.get('model_weights'):
                    row['model_weights'] = json.loads(row['model_weights'])
            return result
        except Exception as e:
            logger.error(f"按预测ID查询失败: {str(e)}")
            raise


class ModelPerformanceCRUD:
    """模型性能记录操作"""

    @staticmethod
    async def insert_performance(
        model_name: str,
        model_version: Optional[str] = None,
        total_inferences: int = 0,
        successful_inferences: int = 0,
        failed_inferences: int = 0,
        average_inference_time_ms: Optional[float] = None,
        mae: Optional[float] = None,
        rmse: Optional[float] = None,
        mape: Optional[float] = None,
        gpu_memory_used_mb: Optional[float] = None,
        cpu_utilization_percent: Optional[float] = None,
        batch_size: int = 1,
        device: str = 'cuda'
    ) -> int:
        """插入模型性能记录"""
        sql = """
        INSERT INTO model_performance (
            model_name, model_version, total_inferences, successful_inferences,
            failed_inferences, average_inference_time_ms, mae, rmse, mape,
            gpu_memory_used_mb, cpu_utilization_percent, batch_size, device
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        params = (
            model_name, model_version, total_inferences, successful_inferences,
            failed_inferences, average_inference_time_ms, mae, rmse, mape,
            gpu_memory_used_mb, cpu_utilization_percent, batch_size, device
        )

        try:
            insert_id = await db_manager.execute_sql_insert(sql, params)
            logger.info(f"成功插入模型性能记录 - ID: {insert_id}, 模型: {model_name}, "
                       f"推理总数: {total_inferences}")
            return insert_id
        except Exception as e:
            logger.error(f"插入模型性能记录失败: {str(e)}")
            raise

    @staticmethod
    async def get_performance_by_model(model_name: str, hours: int = 24) -> List[Dict[str, Any]]:
        """按模型名称查询性能记录"""
        # 修复：使用应用层 eastern_now_hour 而非 MySQL NOW()，确保时区一致且整点对齐
        from realtime_api.services.container import eastern_now_hour
        from datetime import timedelta
        cutoff = eastern_now_hour() - timedelta(hours=hours)
        sql = """
        SELECT id, timestamp, model_name, model_version, total_inferences,
               successful_inferences, failed_inferences, average_inference_time_ms,
               mae, rmse, mape, gpu_memory_used_mb, cpu_utilization_percent,
               batch_size, device
        FROM model_performance
        WHERE model_name = %s AND timestamp >= %s
        ORDER BY timestamp DESC
        """

        try:
            return await db_manager.execute_sql(sql, (model_name, cutoff))
        except Exception as e:
            logger.error(f"查询模型性能记录失败: {str(e)}")
            raise


class APILogsCRUD:
    """API请求日志操作"""

    @staticmethod
    async def insert_log(
        request_id: str,
        endpoint: str,
        method: str,
        status_code: Optional[int] = None,
        response_time_ms: Optional[float] = None,
        request_size_bytes: Optional[int] = None,
        response_size_bytes: Optional[int] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> int:
        """插入API请求日志"""
        sql = """
        INSERT INTO api_request_logs (
            request_id, endpoint, method, status_code, response_time_ms,
            request_size_bytes, response_size_bytes, client_ip, user_agent, error_message
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        params = (
            request_id, endpoint, method, status_code, response_time_ms,
            request_size_bytes, response_size_bytes, client_ip, user_agent, error_message
        )

        try:
            insert_id = await db_manager.execute_sql_insert(sql, params)
            logger.debug(f"成功插入API日志 - ID: {insert_id}, 端点: {endpoint}, 状态码: {status_code}")
            return insert_id
        except Exception as e:
            logger.error(f"插入API日志失败: {str(e)}")
            raise

    @staticmethod
    async def get_logs_by_endpoint(endpoint: str, hours: int = 24, limit: int = 100) -> List[Dict[str, Any]]:
        """按端点查询日志"""
        # 修复：使用应用层 eastern_now_hour 而非 MySQL NOW()，确保时区一致且整点对齐
        from realtime_api.services.container import eastern_now_hour
        from datetime import timedelta
        cutoff = eastern_now_hour() - timedelta(hours=hours)
        sql = """
        SELECT id, request_id, timestamp, endpoint, method, status_code,
               response_time_ms, request_size_bytes, response_size_bytes,
               client_ip, error_message
        FROM api_request_logs
        WHERE endpoint = %s AND timestamp >= %s
        ORDER BY timestamp DESC
        LIMIT %s
        """

        try:
            return await db_manager.execute_sql(sql, (endpoint, cutoff, limit))
        except Exception as e:
            logger.error(f"查询API日志失败: {str(e)}")
            raise


class SystemMetricsCRUD:
    """系统监控指标操作"""

    @staticmethod
    async def insert_metrics(
        cpu_percent: Optional[float] = None,
        cpu_count: Optional[int] = None,
        memory_percent: Optional[float] = None,
        memory_used_gb: Optional[float] = None,
        memory_available_gb: Optional[float] = None,
        gpu_available: bool = False,
        gpu_memory_used_mb: Optional[float] = None,
        gpu_memory_total_mb: Optional[float] = None,
        gpu_utilization_percent: Optional[float] = None,
        gpu_temperature_c: Optional[float] = None,
        network_bytes_sent: Optional[int] = None,
        network_bytes_recv: Optional[int] = None,
        disk_usage_percent: Optional[float] = None,
        process_count: Optional[int] = None,
        active_connections: Optional[int] = None
    ) -> int:
        """插入系统监控指标"""
        sql = """
        INSERT INTO system_metrics (
            cpu_percent, cpu_count, memory_percent, memory_used_gb,
            memory_available_gb, gpu_available, gpu_memory_used_mb,
            gpu_memory_total_mb, gpu_utilization_percent, gpu_temperature_c,
            network_bytes_sent, network_bytes_recv, disk_usage_percent,
            process_count, active_connections
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        params = (
            cpu_percent, cpu_count, memory_percent, memory_used_gb,
            memory_available_gb, gpu_available, gpu_memory_used_mb,
            gpu_memory_total_mb, gpu_utilization_percent, gpu_temperature_c,
            network_bytes_sent, network_bytes_recv, disk_usage_percent,
            process_count, active_connections
        )

        try:
            insert_id = await db_manager.execute_sql_insert(sql, params)
            logger.debug(f"成功插入系统监控指标 - ID: {insert_id}")
            return insert_id
        except Exception as e:
            logger.error(f"插入系统监控指标失败: {str(e)}")
            raise

    @staticmethod
    async def get_metrics(hours: int = 24, limit: int = 100) -> List[Dict[str, Any]]:
        """获取系统监控指标"""
        # 修复：使用应用层 eastern_now_hour 而非 MySQL NOW()，确保时区一致且整点对齐
        from realtime_api.services.container import eastern_now_hour
        from datetime import timedelta
        cutoff = eastern_now_hour() - timedelta(hours=hours)
        sql = """
        SELECT id, timestamp, cpu_percent, memory_percent, gpu_available,
               gpu_memory_used_mb, gpu_utilization_percent, disk_usage_percent,
               active_connections
        FROM system_metrics
        WHERE timestamp >= %s
        ORDER BY timestamp DESC
        LIMIT %s
        """

        try:
            return await db_manager.execute_sql(sql, (cutoff, limit))
        except Exception as e:
            logger.error(f"查询系统监控指标失败: {str(e)}")
            raise


class CachePerformanceCRUD:
    """缓存性能操作"""

    @staticmethod
    async def insert_cache_metrics(
        cache_hits: int = 0,
        cache_misses: int = 0,
        cache_hit_ratio: Optional[float] = None,
        cache_memory_used_mb: Optional[float] = None,
        cache_keys_count: Optional[int] = None,
        avg_cache_hit_time_ms: Optional[float] = None,
        avg_cache_miss_time_ms: Optional[float] = None
    ) -> int:
        """插入缓存性能数据"""
        sql = """
        INSERT INTO cache_performance (
            cache_hits, cache_misses, cache_hit_ratio, cache_memory_used_mb,
            cache_keys_count, avg_cache_hit_time_ms, avg_cache_miss_time_ms
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """

        params = (
            cache_hits, cache_misses, cache_hit_ratio, cache_memory_used_mb,
            cache_keys_count, avg_cache_hit_time_ms, avg_cache_miss_time_ms
        )

        try:
            insert_id = await db_manager.execute_sql_insert(sql, params)
            logger.debug(f"成功插入缓存性能数据 - ID: {insert_id}, 命中率: {cache_hit_ratio}")
            return insert_id
        except Exception as e:
            logger.error(f"插入缓存性能数据失败: {str(e)}")
            raise


class PerformanceAlertsCRUD:
    """性能预警操作"""

    @staticmethod
    async def insert_alert(
        alert_type: str,
        metric_name: str,
        current_value: Optional[float] = None,
        threshold: Optional[float] = None,
        message: str = '',
        severity: int = 3
    ) -> int:
        """插入性能预警"""
        sql = """
        INSERT INTO performance_alerts (
            alert_type, metric_name, current_value, threshold, message, severity
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """

        params = (alert_type, metric_name, current_value, threshold, message, severity)

        try:
            insert_id = await db_manager.execute_sql_insert(sql, params)
            logger.warning(f"创建性能预警 - ID: {insert_id}, "
                          f"类型: {alert_type}, 指标: {metric_name}, 消息: {message}")
            return insert_id
        except Exception as e:
            logger.error(f"插入性能预警失败: {str(e)}")
            raise

    @staticmethod
    async def resolve_alert(alert_id: int, resolved_by: str = 'system') -> bool:
        """解决预警"""
        sql = """
        UPDATE performance_alerts
        SET resolved = TRUE, resolved_at = NOW(), resolved_by = %s
        WHERE id = %s AND resolved = FALSE
        """

        try:
            result = await db_manager.execute_sql(sql, (resolved_by, alert_id))
            return True
        except Exception as e:
            logger.error(f"解决预警失败: {str(e)}")
            raise


class ActualLoadDataCRUD:
    """实际负荷数据操作 (用于预测准确性对比)"""

    @staticmethod
    async def insert_actual_load(
        timestamp: datetime,
        actual_load_mw: float,
        region: str = 'NewEngland',
        data_source: str = 'iso_ne'
    ) -> int:
        """插入实际负荷数据

        使用 INSERT IGNORE 避免重复时间戳导致的错误
        """
        sql = """
        INSERT IGNORE INTO actual_load_data (
            timestamp, actual_load_mw, region, data_source
        ) VALUES (%s, %s, %s, %s)
        """
        params = (timestamp, actual_load_mw, region, data_source)

        try:
            insert_id = await db_manager.execute_sql_insert(sql, params)
            if insert_id:
                logger.info(f"成功插入实际负荷数据 - ID: {insert_id}, 时间: {timestamp}, 负荷: {actual_load_mw}MW")
            return insert_id
        except Exception as e:
            logger.error(f"插入实际负荷数据失败: {str(e)}")
            raise

    @staticmethod
    async def get_actual_load_by_time_range(
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """只读与当前模型口径一致的、完整采样的小时结束负荷。"""
        sql = """
        SELECT id, timestamp, actual_load_mw, region, data_source, created_at
        FROM actual_load_data
        WHERE timestamp BETWEEN %s AND %s
          AND region = %s AND data_source = %s
        ORDER BY timestamp ASC
        """
        try:
            return await db_manager.execute_sql(sql, (start_time, end_time, ACTUAL_REGION, ACTUAL_SOURCE))
        except Exception as e:
            logger.error(f"查询实际负荷数据失败: {str(e)}")
            raise

    @staticmethod
    async def get_time_bounds() -> Dict[str, Any]:
        """查询真实负荷数据的可用时间范围（任意日期回测的日期选择器约束）"""
        sql = """
        SELECT MIN(timestamp) AS earliest, MAX(timestamp) AS latest
        FROM actual_load_data
        WHERE region = %s AND data_source = %s
        """
        try:
            rows = await db_manager.execute_sql(sql, (ACTUAL_REGION, ACTUAL_SOURCE))
        except Exception as e:
            logger.error(f"查询实际负荷时间范围失败: {str(e)}")
            raise
        if rows and rows[0]:
            return {"earliest": rows[0].get("earliest"), "latest": rows[0].get("latest")}
        return {"earliest": None, "latest": None}

    # NOTE: 原 backfill_predictions_actual() 已删除 —— 它曾用 ±2% 随机噪声伪造"实际负荷"数据，
    # 污染预测准确性统计。实际负荷只能来自真实数据源（如 ISO New England API），
    # 不能用模型预测值+噪声近似。后台任务 _periodic_actual_load_backfill 同步移除。
