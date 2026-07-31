"""
智能电网负荷预测系统 - 历史负荷数据提供器

从数据库 load_predictions 表中提取最近的预测负荷值，
作为 FeatureGenerator 所需的 historical_load 上下文。

FeatureGenerator 需要 168 小时（7天）的历史负荷数据来计算：
  - load_lag_1h / 24h / 48h / 168h
  - load_rolling_mean/std/min/max_24h
  - load_rolling_mean_168h
  - load_diff_1h / 24h
  - load_pct_change_24h

在没有 ISO-NE 实时 API 的情况下，使用数据库中最近的预测值作为近似。

作者: 毕业设计项目
"""

import logging
import os
import pickle
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import numpy as np

from realtime_api.database import db_manager
from realtime_api.crud import LoadPredictionsCRUD

logger = logging.getLogger(__name__)

# 训练数据路径（用于冷启动回退）
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
_TRAINING_DATA_PATH = os.path.join(_PROJECT_ROOT, "processed", "step1_system_data.pkl")


class HistoricalLoadProvider:
    """
    从数据库获取历史负荷数据

    策略:
      1. 查询 load_predictions 表中最近 7 天的 ensemble 预测
      2. 按 target_timestamp 去重（同一次预测有多条记录）
      3. 选取每个目标时间点的最新预测值
      4. 构建 DataFrame: [timestamp, System_Load]
    """

    LOOKBACK_HOURS = 200  # 168 + 余量，确保滚动窗口有足够数据

    @staticmethod
    async def get_historical_load(
        end_time: Optional[datetime] = None,
        hours: int = LOOKBACK_HOURS,
    ) -> Optional[pd.DataFrame]:
        """
        获取历史负荷数据

        Args:
            end_time: 截止时间（默认当前新英格兰时间）
            hours: 需要的小时数

        Returns:
            pd.DataFrame: 包含 timestamp 和 System_Load 列，或 None（无数据）
        """
        if end_time is None:
            from realtime_api.services.container import eastern_now
            end_time = eastern_now()

        # 截断到整点，确保与 Open-Meteo 整点天气数据和预测 target_timestamp 对齐
        end_time = end_time.replace(minute=0, second=0, microsecond=0)

        start_time = end_time - timedelta(hours=hours)

        try:
            # 查询最近的预测记录（按 target_timestamp 升序）
            predictions = await LoadPredictionsCRUD.get_predictions_by_time_range(
                start_time=start_time,
                end_time=end_time,
                model_type='ensemble',
            )

            if not predictions:
                logger.warning(
                    f"数据库中无历史预测数据 "
                    f"(范围: {start_time} ~ {end_time})，"
                    f"尝试使用训练数据作为冷启动回退"
                )
                return HistoricalLoadProvider._cold_start_fallback(end_time, hours)

            # 按 target_timestamp 分组，取每组的最新预测（prediction_timestamp 最大）
            df = pd.DataFrame(predictions)
            if 'target_timestamp' not in df.columns or 'load_forecast_mw' not in df.columns:
                logger.warning("历史预测数据缺少必要字段")
                return None

            # 确保 target_timestamp 是 datetime
            df['target_timestamp'] = pd.to_datetime(df['target_timestamp'])

            # 关键修复：截断到整点，确保与 Open-Meteo 整点天气数据对齐
            # 否则 df.index.map(load_series) 会因时间戳不匹配而返回 NaN
            df['target_timestamp'] = df['target_timestamp'].dt.floor('h')

            # 按 target_timestamp 分组，保留 prediction_timestamp 最新的记录
            if 'prediction_timestamp' in df.columns:
                df['prediction_timestamp'] = pd.to_datetime(df['prediction_timestamp'])
                df = df.sort_values('prediction_timestamp')
                df = df.drop_duplicates(subset='target_timestamp', keep='last')
            else:
                df = df.drop_duplicates(subset='target_timestamp', keep='last')

            # 按 target_timestamp 排序
            df = df.sort_values('target_timestamp')

            # 构建 FeatureGenerator 期望的格式
            result = pd.DataFrame({
                'timestamp': df['target_timestamp'],
                'System_Load': df['load_forecast_mw'].astype(float),
            })

            # 前向填充可能的缺失小时（确保时间连续）
            result = result.set_index('timestamp')
            full_range = pd.date_range(
                start=result.index.min(),
                end=result.index.max(),
                freq='h',
            )
            result = result.reindex(full_range)
            result = result.ffill().bfill()
            result = result.reset_index().rename(columns={'index': 'timestamp'})

            logger.info(
                f"历史负荷数据获取成功: {len(result)} 条记录, "
                f"范围: {result['timestamp'].min()} ~ {result['timestamp'].max()}"
            )

            return result

        except Exception as e:
            logger.error(f"获取历史负荷数据失败: {e}")
            return HistoricalLoadProvider._cold_start_fallback(end_time, hours)

    @staticmethod
    def _cold_start_fallback(
        end_time: Optional[datetime] = None,
        hours: int = LOOKBACK_HOURS,
    ) -> Optional[pd.DataFrame]:
        """
        冷启动回退：当数据库中无历史预测数据时，
        使用训练数据的最后 N 小时作为初始历史负荷。

        将训练数据的时间戳重新映射到当前时间段，
        使滞后/滚动特征能够正常计算。

        注意：这是近似值，随着系统运行积累真实预测数据后会被替代。
        """
        if end_time is None:
            from realtime_api.services.container import eastern_now
            end_time = eastern_now()

        # 截断到整点
        end_time = end_time.replace(minute=0, second=0, microsecond=0)

        try:
            if not os.path.exists(_TRAINING_DATA_PATH):
                logger.warning(f"训练数据文件不存在: {_TRAINING_DATA_PATH}，冷启动回退不可用")
                return None

            with open(_TRAINING_DATA_PATH, "rb") as f:
                train_df = pickle.load(f)

            if train_df is None or len(train_df) == 0:
                logger.warning("训练数据为空，冷启动回退不可用")
                return None

            # 取最后 N 小时的训练数据
            n = min(hours, len(train_df))
            tail_df = train_df.tail(n).copy()

            # 构建时间戳：从 end_time 往前推 n 小时
            new_timestamps = pd.date_range(
                end=end_time - timedelta(hours=1),
                periods=n,
                freq='h',
            )

            result = pd.DataFrame({
                'timestamp': new_timestamps,
                'System_Load': tail_df['System_Load'].astype(float).values,
            })

            logger.warning(
                f"[冷启动回退] 使用训练数据最后 {n} 小时作为历史负荷近似，"
                f"时间戳已重映射到 {result['timestamp'].min()} ~ {result['timestamp'].max()}。"
                f"随着系统运行积累真实预测数据后将被替代。"
            )

            return result

        except Exception as e:
            logger.error(f"冷启动回退失败: {e}")
            return None


__all__ = ['HistoricalLoadProvider']
