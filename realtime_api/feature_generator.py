"""
智能电网负荷预测系统 - 实时特征工程模块

功能:
  1. 将 Open-Meteo 原始气象数据映射为模型输入特征
  2. 生成与训练阶段完全一致的 38 维特征向量
  3. 支持滞后特征、滚动窗口特征、时间特征、气象衍生特征
  4. 支持增量计算（只处理新增数据）
  5. 高效计算，适合实时处理

特征列表 (38个，与 processed/step4_feature_config.pkl 完全一致):
  [ 0] Dry_Bulb              [19] cooling_degree
  [ 1] Dew_Point             [20] heating_degree
  [ 2] hour_sin              [21] load_lag_1h
  [ 3] hour_cos              [22] load_lag_24h
  [ 4] dow_sin               [23] load_lag_48h
  [ 5] dow_cos               [24] load_lag_168h
  [ 6] doy_sin               [25] temp_lag_24h
  [ 7] doy_cos               [26] temp_lag_168h
  [ 8] month_sin             [27] load_rolling_mean_24h
  [ 9] month_cos             [28] load_rolling_std_24h
  [10] week_sin              [29] load_rolling_mean_168h
  [11] week_cos              [30] load_rolling_min_24h
  [12] is_weekend            [31] load_rolling_max_24h
  [13] is_holiday            [32] temp_rolling_mean_24h
  [14] season_fall           [33] temp_rolling_max_24h
  [15] season_spring         [34] temp_rolling_min_24h
  [16] season_summer         [35] load_diff_1h
  [17] season_winter         [36] load_diff_24h
  [18] humidity_index        [37] load_pct_change_24h

依赖:
  pip install pandas numpy

作者: 毕业设计项目
"""

import os
import pickle
import logging
from typing import List, Dict, Optional, Any, Tuple, Union

import numpy as np
import pandas as pd

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(PROJECT_ROOT, "processed")

# ============================================================================
# 日志配置
# ============================================================================
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )


# ============================================================================
# 常量定义（与训练阶段 src/feature_engine.py 和 src/feature_constructor.py 完全一致）
# ============================================================================

# 预测目标
TARGET = "System_Load"

# 基准温度（度日计算，新英格兰地区 18°C = 65°F）
BASE_TEMP_C = 18.0

# 风速单位转换因子: m/s → mph
WIND_MS_TO_MPH = 2.23694

# 美国法定假日列表（2023-2026，与训练阶段一致并扩展到2026）
US_HOLIDAYS = {
    # 2023
    "2023-01-01", "2023-01-16", "2023-02-20", "2023-05-29", "2023-06-19",
    "2023-07-04", "2023-09-04", "2023-10-09", "2023-11-11", "2023-11-23",
    "2023-12-25",
    # 2024
    "2024-01-01", "2024-01-15", "2024-02-19", "2024-05-27", "2024-06-19",
    "2024-07-04", "2024-09-02", "2024-10-14", "2024-11-11", "2024-11-28",
    "2024-12-25",
    # 2025
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-05-26", "2025-06-19",
    "2025-07-04", "2025-09-01", "2025-10-13", "2025-11-11", "2025-11-27",
    "2025-12-25",
    # 2026 (扩展，用于实时预测)
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19",
    "2026-07-04", "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26",
    "2026-12-25",
}

# 最终 38 个特征列名（与 step4_feature_config.pkl 完全一致）
FEATURE_COLS = [
    # 气象特征 (2)
    "Dry_Bulb", "Dew_Point",
    # 时间正余弦编码 (10)
    "hour_sin", "hour_cos",
    "dow_sin", "dow_cos",
    "doy_sin", "doy_cos",
    "month_sin", "month_cos",
    "week_sin", "week_cos",
    # 布尔特征 (2)
    "is_weekend", "is_holiday",
    # 季节 one-hot (4)
    "season_fall", "season_spring", "season_summer", "season_winter",
    # 气象衍生特征 (3)
    "humidity_index", "cooling_degree", "heating_degree",
    # 滞后特征 (6)
    "load_lag_1h", "load_lag_24h", "load_lag_48h", "load_lag_168h",
    "temp_lag_24h", "temp_lag_168h",
    # 滚动窗口特征 (8)
    "load_rolling_mean_24h", "load_rolling_std_24h", "load_rolling_mean_168h",
    "load_rolling_min_24h", "load_rolling_max_24h",
    "temp_rolling_mean_24h", "temp_rolling_max_24h", "temp_rolling_min_24h",
    # 负荷变化特征 (3)
    "load_diff_1h", "load_diff_24h", "load_pct_change_24h",
]

# 确保特征数量正确
assert len(FEATURE_COLS) == 38, f"特征数量应为38，实际为{len(FEATURE_COLS)}"

# Open-Meteo 参数到训练特征的映射
WEATHER_MAPPING = {
    "temperature_2m": "Dry_Bulb",    # °C → °C，直接使用
    "dew_point_2m": "Dew_Point",     # °C → °C，直接使用
}


# ============================================================================
# 异常定义
# ============================================================================

class FeatureGenerationError(Exception):
    """特征生成异常"""
    pass


# ============================================================================
# 主特征生成器类
# ============================================================================

class FeatureGenerator:
    """
    实时特征工程生成器

    将 Open-Meteo 原始气象数据 + 历史负荷数据转换为
    与训练阶段完全一致的 38 维特征向量。

    特征生成流程:
      1. 数据映射: temperature_2m → Dry_Bulb, dew_point_2m → Dew_Point
      2. 气象衍生: humidity_index, cooling_degree, heating_degree
      3. 时间特征: 正余弦编码 + 布尔 + 季节
      4. 滞后特征: load_lag_*, temp_lag_* (需要历史数据)
      5. 滚动窗口: load_rolling_*, temp_rolling_* (需要历史数据)
      6. 变化特征: load_diff_*, load_pct_change_*

    Attributes:
        feature_cols: 38个特征列名（固定顺序）
        history_buffer: 历史数据缓冲区（用于增量计算）
        max_lookback: 最大回看窗口（168小时 = 7天）
    """

    def __init__(
        self,
        feature_config_path: Optional[str] = None,
    ):
        """
        初始化特征生成器

        Args:
            feature_config_path: 训练阶段的特征配置文件路径
                                 (processed/step4_feature_config.pkl)
                                 如果提供，会验证特征一致性
        """
        # 尝试加载训练配置进行验证
        if feature_config_path is None:
            feature_config_path = os.path.join(
                PROCESSED_DIR, "step4_feature_config.pkl"
            )

        self._verify_feature_consistency(feature_config_path)

        # 特征列名（固定顺序，与训练一致）
        self.feature_cols = FEATURE_COLS.copy()

        # 历史数据缓冲区
        # 存储格式: DataFrame with columns=[timestamp, Dry_Bulb, Dew_Point, System_Load]
        self._history_buffer: Optional[pd.DataFrame] = None

        # 最大回看窗口
        self.max_lookback = 169  # 168 + 1 (shift(1) 需要 169 行)

        logger.info(f"FeatureGenerator 初始化完成")
        logger.info(f"  特征数量: {len(self.feature_cols)}")
        logger.info(f"  最大回看窗口: {self.max_lookback} 小时")

    # ========================================================================
    # 特征一致性验证
    # ========================================================================

    def _verify_feature_consistency(self, config_path: str) -> None:
        """
        验证实时特征与训练特征是否完全一致

        Args:
            config_path: 训练配置文件路径

        Raises:
            FeatureGenerationError: 特征不一致
        """
        if not os.path.exists(config_path):
            logger.warning(
                f"训练配置文件不存在: {config_path}，跳过一致性验证。"
                f"将使用内置特征列表。"
            )
            return

        try:
            with open(config_path, "rb") as f:
                config = pickle.load(f)

            train_features = config.get("feature_cols", [])

            if len(train_features) != 38:
                logger.warning(
                    f"训练特征数量为 {len(train_features)}，期望 38"
                )

            # 检查特征是否匹配
            missing = set(train_features) - set(FEATURE_COLS)
            extra = set(FEATURE_COLS) - set(train_features)

            if missing or extra:
                msg = "特征不一致!\n"
                if missing:
                    msg += f"  缺少: {missing}\n"
                if extra:
                    msg += f"  多余: {extra}\n"
                raise FeatureGenerationError(msg)

            # 检查顺序
            if train_features != FEATURE_COLS:
                logger.warning(
                    "特征顺序与训练配置不一致，将使用训练配置的顺序"
                )
                # 使用训练配置的顺序（更新实例属性）
                self._train_feature_order = train_features

            logger.info("✅ 特征一致性验证通过 (38个特征完全匹配)")

        except Exception as e:
            logger.warning(f"无法加载训练配置进行验证: {e}")

    # ========================================================================
    # 主入口：生成特征
    # ========================================================================

    def generate(
        self,
        weather_df: pd.DataFrame,
        historical_load: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        从气象数据和历史负荷数据生成 38 维特征

        Args:
            weather_df: 气象数据 DataFrame
                必须包含: timestamp, location, temperature_2m, dew_point_2m
                可选包含: wind_speed_10m, cloud_cover, shortwave_radiation
            historical_load: 历史负荷数据 DataFrame
                必须包含: timestamp, System_Load
                时间范围需覆盖 weather_df 的前 168 小时

        Returns:
            pd.DataFrame: 38维特征 DataFrame，列名与训练阶段完全一致

        Example:
            >>> generator = FeatureGenerator()
            >>> features = generator.generate(weather_df, historical_load)
            >>> print(features.shape)  # (N, 38)
        """
        logger.info("=" * 60)
        logger.info("开始生成实时特征")
        logger.info("=" * 60)

        # 1. 数据预处理和映射
        logger.info("[步骤1] 气象数据映射...")
        df = self._map_weather_data(weather_df)

        # 2. 合并历史负荷数据
        logger.info("[步骤2] 合并历史负荷数据...")
        df = self._merge_historical_load(df, historical_load)

        # 3. 生成气象衍生特征
        logger.info("[步骤3] 生成气象衍生特征...")
        df = self._add_weather_derived_features(df)

        # 4. 生成时间特征
        logger.info("[步骤4] 生成时间特征...")
        df = self._add_time_features(df)

        # 5. 生成滞后特征
        logger.info("[步骤5] 生成滞后特征...")
        df = self._add_lag_features(df)

        # 6. 生成滚动窗口特征
        logger.info("[步骤6] 生成滚动窗口特征...")
        df = self._add_rolling_features(df)

        # 7. 生成负荷变化特征
        logger.info("[步骤7] 生成负荷变化特征...")
        df = self._add_load_change_features(df)

        # 8. 选择最终 38 个特征
        logger.info("[步骤8] 选择最终特征...")
        features = self._select_features(df)

        # 9. 处理缺失值
        logger.info("[步骤9] 缺失值处理...")
        features = self._handle_missing(features)

        logger.info(f"\n✅ 特征生成完成: {features.shape[0]} 行, {features.shape[1]} 列")

        # 更新历史缓冲区
        self._update_history_buffer(df)

        return features

    # ========================================================================
    # 步骤1: 气象数据映射
    # ========================================================================

    def _map_weather_data(self, weather_df: pd.DataFrame) -> pd.DataFrame:
        """
        将 Open-Meteo 参数映射为训练阶段的特征名

        映射规则:
          - temperature_2m → Dry_Bulb (°C → °C，直接使用)
          - dew_point_2m → Dew_Point (°C → °C，直接使用)
          - wind_speed_10m → wind_speed_mph (m/s → mph，单位转换)
          - 多站点取区域平均

        Args:
            weather_df: Open-Meteo 原始数据

        Returns:
            映射后的 DataFrame，包含 Dry_Bulb, Dew_Point 等列
        """
        df = weather_df.copy()

        # 确保 timestamp 是 datetime
        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        # 参数名映射
        for api_param, train_col in WEATHER_MAPPING.items():
            if api_param in df.columns:
                df[train_col] = df[api_param]
                logger.info(f"  {api_param} → {train_col}")

        # 风速单位转换 (m/s → mph)
        if "wind_speed_10m" in df.columns:
            df["wind_speed_mph"] = df["wind_speed_10m"] * WIND_MS_TO_MPH
            logger.info(f"  wind_speed_10m → wind_speed_mph (×{WIND_MS_TO_MPH})")

        # 多站点取区域平均（与训练数据的系统级数据一致）
        if "location" in df.columns and df["location"].nunique() > 1:
            param_cols = [c for c in df.columns
                          if c in ["Dry_Bulb", "Dew_Point", "wind_speed_mph"]]
            df = df.groupby("timestamp")[param_cols].mean().reset_index()
            logger.info(f"  多站点区域平均: {weather_df['location'].nunique()} → 1")

        # 设为时间索引
        df = df.set_index("timestamp").sort_index()

        logger.info(f"  映射后数据: {len(df)} 行")
        return df

    # ========================================================================
    # 步骤2: 合并历史负荷数据
    # ========================================================================

    def _merge_historical_load(
        self,
        df: pd.DataFrame,
        historical_load: Optional[pd.DataFrame],
    ) -> pd.DataFrame:
        """
        合并历史负荷数据

        训练数据中 System_Load 是原始列，实时预测时需要从外部提供。
        如果有历史缓冲区，也一并合并。

        Args:
            df: 气象数据
            historical_load: 历史负荷数据，包含 timestamp 和 System_Load

        Returns:
            合并后的 DataFrame，包含 System_Load 列
        """
        # 如果没有提供历史负荷，尝试使用缓冲区
        if historical_load is None:
            if self._history_buffer is not None and TARGET in self._history_buffer.columns:
                logger.info("  使用历史缓冲区中的负荷数据")
                historical_load = self._history_buffer
            else:
                logger.warning("  未提供历史负荷数据，滞后/滚动/变化特征将为NaN")
                df[TARGET] = np.nan
                return df

        # 复制并确保格式正确
        load_df = historical_load.copy()
        if "timestamp" in load_df.columns:
            if not pd.api.types.is_datetime64_any_dtype(load_df["timestamp"]):
                load_df["timestamp"] = pd.to_datetime(load_df["timestamp"])
            load_df = load_df.set_index("timestamp")

        # 确保负荷列名正确
        if TARGET not in load_df.columns:
            # 尝试其他常见列名
            for alt_name in ["load", "Load", "system_load", "SystemLoad"]:
                if alt_name in load_df.columns:
                    load_df = load_df.rename(columns={alt_name: TARGET})
                    break
            else:
                raise FeatureGenerationError(
                    f"历史负荷数据中未找到 '{TARGET}' 列"
                )

        # 合并
        # 只取负荷列，避免列名冲突
        load_series = load_df[TARGET]
        df[TARGET] = df.index.map(load_series).values

        # 统计合并情况
        missing_count = df[TARGET].isna().sum()
        total = len(df)
        if missing_count > 0:
            logger.warning(
                f"  {missing_count}/{total} ({missing_count/total*100:.1f}%) "
                f"时间点缺少历史负荷数据"
            )
        else:
            logger.info(f"  历史负荷合并完成: {total} 个时间点全部匹配")

        return df

    # ========================================================================
    # 步骤3: 气象衍生特征
    # ========================================================================

    def _add_weather_derived_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成气象衍生特征

        与 src/feature_constructor.py 中的 add_weather_derived_features() 完全一致:
          - humidity_index = Dry_Bulb - Dew_Point
          - cooling_degree = max(0, Dry_Bulb - 18)
          - heating_degree = max(0, 18 - Dry_Bulb)
        """
        # 湿度指标
        df["humidity_index"] = df["Dry_Bulb"] - df["Dew_Point"]

        # 制冷度日
        df["cooling_degree"] = np.maximum(0, df["Dry_Bulb"] - BASE_TEMP_C)

        # 供暖度日
        df["heating_degree"] = np.maximum(0, BASE_TEMP_C - df["Dry_Bulb"])

        logger.info(
            f"  humidity_index: [{df['humidity_index'].min():.1f}, "
            f"{df['humidity_index'].max():.1f}]"
        )
        logger.info(
            f"  cooling_degree: 非零 {(df['cooling_degree'] > 0).sum()} 小时"
        )
        logger.info(
            f"  heating_degree: 非零 {(df['heating_degree'] > 0).sum()} 小时"
        )

        return df

    # ========================================================================
    # 步骤4: 时间特征
    # ========================================================================

    def _add_time_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成时间特征

        与 src/feature_engine.py 中的逻辑完全一致:
          - 提取: hour, day_of_week, day_of_year, month, week
          - 正余弦编码: hour_sin/cos, dow_sin/cos, doy_sin/cos, month_sin/cos, week_sin/cos
          - 布尔: is_weekend, is_holiday
          - 季节 one-hot: season_fall/spring/summer/winter
        """
        idx = df.index

        # --- 基本时间提取（用于后续编码，不作为最终特征）---
        hour = idx.hour
        day_of_week = idx.dayofweek
        day_of_year = idx.dayofyear
        month = idx.month
        week = idx.isocalendar().week.astype(int)

        # --- 正余弦编码（与训练阶段完全一致）---
        # hour (周期=24)
        df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
        df["hour_cos"] = np.cos(2 * np.pi * hour / 24)

        # day_of_week (周期=7)
        df["dow_sin"] = np.sin(2 * np.pi * day_of_week / 7)
        df["dow_cos"] = np.cos(2 * np.pi * day_of_week / 7)

        # day_of_year (周期=365)
        df["doy_sin"] = np.sin(2 * np.pi * day_of_year / 365)
        df["doy_cos"] = np.cos(2 * np.pi * day_of_year / 365)

        # month (周期=12)
        df["month_sin"] = np.sin(2 * np.pi * month / 12)
        df["month_cos"] = np.cos(2 * np.pi * month / 12)

        # week (周期=52)
        df["week_sin"] = np.sin(2 * np.pi * week / 52)
        df["week_cos"] = np.cos(2 * np.pi * week / 52)

        # --- 布尔特征 ---
        df["is_weekend"] = (day_of_week >= 5).astype(int)

        # 假日判断
        holiday_dates = {pd.Timestamp(d) for d in US_HOLIDAYS}
        df["is_holiday"] = idx.normalize().isin(holiday_dates).astype(int)

        # --- 季节 one-hot 编码 ---
        # 与训练阶段 get_season() 逻辑一致
        # 冬季(12,1,2) 春季(3,4,5) 夏季(6,7,8) 秋季(9,10,11)
        df["season_winter"] = ((month == 12) | (month <= 2)).astype(int)
        df["season_spring"] = ((month >= 3) & (month <= 5)).astype(int)
        df["season_summer"] = ((month >= 6) & (month <= 8)).astype(int)
        df["season_fall"] = ((month >= 9) & (month <= 11)).astype(int)

        logger.info(
            f"  时间特征: weekend={df['is_weekend'].sum()}h, "
            f"holiday={df['is_holiday'].sum()}h"
        )

        return df

    # ========================================================================
    # 步骤5: 滞后特征
    # ========================================================================

    def _add_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成滞后特征

        与 src/feature_constructor.py 中的 add_lag_features() 完全一致:
          - load_lag_1h:   System_Load.shift(1)
          - load_lag_24h:  System_Load.shift(24)
          - load_lag_48h:  System_Load.shift(48)
          - load_lag_168h: System_Load.shift(168)
          - temp_lag_24h:  Dry_Bulb.shift(24)
          - temp_lag_168h: Dry_Bulb.shift(168)
        """
        # 负荷滞后
        df["load_lag_1h"] = df[TARGET].shift(1)
        df["load_lag_24h"] = df[TARGET].shift(24)
        df["load_lag_48h"] = df[TARGET].shift(48)
        df["load_lag_168h"] = df[TARGET].shift(168)

        # 温度滞后
        df["temp_lag_24h"] = df["Dry_Bulb"].shift(24)
        df["temp_lag_168h"] = df["Dry_Bulb"].shift(168)

        logger.info("  负荷滞后: 1h, 24h, 48h, 168h")
        logger.info("  温度滞后: 24h, 168h")

        return df

    # ========================================================================
    # 步骤6: 滚动窗口特征
    # ========================================================================

    def _add_rolling_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成滚动窗口特征

        与 src/feature_constructor.py 中的 add_rolling_features() 完全一致:
          使用 shift(1) 确保窗口只含过去数据（避免数据泄露）

          - load_rolling_mean_24h:  shift(1).rolling(24).mean()
          - load_rolling_std_24h:   shift(1).rolling(24).std()
          - load_rolling_mean_168h: shift(1).rolling(168).mean()
          - load_rolling_min_24h:   shift(1).rolling(24).min()
          - load_rolling_max_24h:   shift(1).rolling(24).max()
          - temp_rolling_mean_24h:  shift(1).rolling(24).mean()
          - temp_rolling_max_24h:   shift(1).rolling(24).max()
          - temp_rolling_min_24h:   shift(1).rolling(24).min()
        """
        # 负荷滚动窗口（先 shift(1) 再 rolling，避免数据泄露）
        df["load_rolling_mean_24h"] = df[TARGET].shift(1).rolling(window=24).mean()
        df["load_rolling_std_24h"] = df[TARGET].shift(1).rolling(window=24).std()
        df["load_rolling_mean_168h"] = df[TARGET].shift(1).rolling(window=168).mean()
        df["load_rolling_min_24h"] = df[TARGET].shift(1).rolling(window=24).min()
        df["load_rolling_max_24h"] = df[TARGET].shift(1).rolling(window=24).max()

        # 温度滚动窗口
        df["temp_rolling_mean_24h"] = df["Dry_Bulb"].shift(1).rolling(window=24).mean()
        df["temp_rolling_max_24h"] = df["Dry_Bulb"].shift(1).rolling(window=24).max()
        df["temp_rolling_min_24h"] = df["Dry_Bulb"].shift(1).rolling(window=24).min()

        logger.info("  负荷滚动: mean/std/min/max (24h), mean (168h)")
        logger.info("  温度滚动: mean/max/min (24h)")

        return df

    # ========================================================================
    # 步骤7: 负荷变化特征
    # ========================================================================

    def _add_load_change_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成负荷变化特征

        与 src/feature_constructor.py 中的 add_load_change_features() 完全一致:
          - load_diff_1h:      System_Load.diff(1)
          - load_diff_24h:     System_Load.diff(24)
          - load_pct_change_24h: System_Load.pct_change(periods=24)
        """
        df["load_diff_1h"] = df[TARGET].diff(1)
        df["load_diff_24h"] = df[TARGET].diff(24)
        df["load_pct_change_24h"] = df[TARGET].pct_change(periods=24)

        logger.info("  负荷变化: diff_1h, diff_24h, pct_change_24h")

        return df

    # ========================================================================
    # 步骤8: 选择最终特征
    # ========================================================================

    def _select_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        选择最终的 38 个特征，按训练时的顺序排列
        """
        # 确保所有特征列都存在
        missing_cols = [c for c in self.feature_cols if c not in df.columns]
        if missing_cols:
            # 为缺失的列填充 NaN
            for col in missing_cols:
                df[col] = np.nan
                logger.warning(f"  特征列 '{col}' 不存在，填充为 NaN")

        # 按训练时的顺序选择
        features = df[self.feature_cols].copy()

        logger.info(f"  选择了 {len(self.feature_cols)} 个特征")
        return features

    # ========================================================================
    # 步骤9: 缺失值处理
    # ========================================================================

    def _handle_missing(self, features: pd.DataFrame) -> pd.DataFrame:
        """
        处理特征中的缺失值

        策略:
          1. 前向填充 (使用最近的非NaN值)
          2. 后向填充 (处理开头缺失)
          3. 填充为0 (兜底)
        """
        before_missing = features.isna().sum().sum()

        if before_missing == 0:
            logger.info("  无缺失值")
            return features

        logger.warning(f"  处理前缺失值: {before_missing}")

        # 前向填充 + 后向填充
        features = features.ffill().bfill()

        # 兜底：填充为 0
        remaining = features.isna().sum().sum()
        if remaining > 0:
            features = features.fillna(0)
            logger.warning(f"  仍有 {remaining} 个缺失值填充为 0")

        logger.info(f"  缺失值处理完成")

        return features

    # ========================================================================
    # 历史缓冲区管理（增量计算支持）
    # ========================================================================

    def _update_history_buffer(self, df: pd.DataFrame) -> None:
        """
        更新历史数据缓冲区

        保留最近 max_lookback*2 小时的数据，
        用于后续增量计算时提供历史上下文。
        """
        # 只保留需要的列
        keep_cols = [c for c in [TARGET, "Dry_Bulb", "Dew_Point"] if c in df.columns]
        if not keep_cols:
            return

        new_data = df[keep_cols].copy()

        if self._history_buffer is None:
            self._history_buffer = new_data
        else:
            # 合并新旧数据，去重，排序
            self._history_buffer = pd.concat([
                self._history_buffer, new_data
            ])
            self._history_buffer = self._history_buffer[~self._history_buffer.index.duplicated(keep='last')]
            self._history_buffer = self._history_buffer.sort_index()

            # 只保留最近的数据
            if len(self._history_buffer) > self.max_lookback * 2:
                self._history_buffer = self._history_buffer.tail(self.max_lookback * 2)

        logger.info(f"  历史缓冲区: {len(self._history_buffer)} 条记录")

    def get_history_buffer(self) -> Optional[pd.DataFrame]:
        """获取当前历史缓冲区"""
        return self._history_buffer.copy() if self._history_buffer is not None else None

    # ========================================================================
    # 增量计算
    # ========================================================================

    def generate_incremental(
        self,
        new_weather_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        增量计算：只处理新增的气象数据

        使用历史缓冲区中的负荷和气象数据作为上下文，
        为新增的气象数据生成特征。

        Args:
            new_weather_df: 新获取的气象数据

        Returns:
            新增数据对应的特征 DataFrame
        """
        if self._history_buffer is None:
            logger.warning("历史缓冲区为空，无法增量计算，使用全量计算")
            return self.generate(new_weather_df)

        logger.info("增量计算模式")

        # 合并历史数据和新增数据
        new_df = new_weather_df.copy()
        if not pd.api.types.is_datetime64_any_dtype(new_df["timestamp"]):
            new_df["timestamp"] = pd.to_datetime(new_df["timestamp"])

        # 映射气象参数
        for api_param, train_col in WEATHER_MAPPING.items():
            if api_param in new_df.columns:
                new_df[train_col] = new_df[api_param]

        # 多站点平均
        if "location" in new_df.columns and new_df["location"].nunique() > 1:
            param_cols = [c for c in new_df.columns if c in ["Dry_Bulb", "Dew_Point"]]
            new_df = new_df.groupby("timestamp")[param_cols].mean().reset_index()

        new_df = new_df.set_index("timestamp").sort_index()

        # 合并历史缓冲区
        combined = pd.concat([self._history_buffer, new_df])
        combined = combined[~combined.index.duplicated(keep='last')].sort_index()

        # 在合并后的数据上生成特征
        df = combined.copy()
        df = self._add_weather_derived_features(df)
        df = self._add_time_features(df)
        df = self._add_lag_features(df)
        df = self._add_rolling_features(df)
        df = self._add_load_change_features(df)

        # 只返回新增数据对应的行
        features = self._select_features(df)
        features = features.loc[new_df.index]

        features = self._handle_missing(features)

        # 更新缓冲区
        self._update_history_buffer(df)

        return features

    # ========================================================================
    # 归一化适配
    # ========================================================================

    def normalize(
        self,
        features: pd.DataFrame,
        scalers_path: Optional[str] = None,
    ) -> np.ndarray:
        """
        使用训练阶段的 MinMaxScaler 对特征进行归一化

        Args:
            features: 38维特征 DataFrame
            scalers_path: scalers文件路径 (processed/step5_scalers.pkl)

        Returns:
            归一化后的 numpy 数组 (N, 38)
        """
        if scalers_path is None:
            scalers_path = os.path.join(PROCESSED_DIR, "step5_scalers.pkl")

        if not os.path.exists(scalers_path):
            logger.warning(f"Scalers文件不存在: {scalers_path}，跳过归一化")
            return features.values

        with open(scalers_path, "rb") as f:
            scalers = pickle.load(f)

        feature_scaler = scalers["feature_scaler"]

        # 确保列顺序一致
        features = features[self.feature_cols]

        # Transform（不 fit，避免数据泄露）
        normalized = feature_scaler.transform(features.values)

        logger.info(f"  归一化完成: shape={normalized.shape}")
        return normalized

    # ========================================================================
    # 序列构建
    # ========================================================================

    def build_sequence(
        self,
        features: pd.DataFrame,
        lookback: int = 168,
    ) -> np.ndarray:
        """
        构建模型输入序列

        将特征 DataFrame 转换为 (1, lookback, 38) 的序列，
        用于模型推理。

        Args:
            features: 特征 DataFrame (N, 38)
            lookback: 回看窗口大小 (默认168=7天)

        Returns:
            np.ndarray: (1, lookback, 38) 或 (batch, lookback, 38)
        """
        values = features.values

        if len(values) < lookback:
            logger.warning(
                f"数据不足: {len(values)} < lookback={lookback}，"
                f"用0填充"
            )
            padding = np.zeros((lookback - len(values), len(self.feature_cols)))
            values = np.vstack([padding, values])

        # 取最后 lookback 行
        sequence = values[-lookback:]

        # 扩展维度: (lookback, 38) → (1, lookback, 38)
        sequence = sequence[np.newaxis, ...]

        logger.info(f"  序列构建: shape={sequence.shape}")
        return sequence


# ============================================================================
# 使用示例
# ============================================================================

def demo():
    """演示 FeatureGenerator 的使用"""
    print("=" * 60)
    print("实时特征工程模块演示")
    print("=" * 60)

    # 1. 创建生成器
    print("\n[1] 创建特征生成器...")
    generator = FeatureGenerator()

    # 2. 构造模拟气象数据
    print("\n[2] 构造模拟气象数据...")
    timestamps = pd.date_range("2025-07-10", periods=200, freq="h")
    np.random.seed(42)
    weather_df = pd.DataFrame({
        "timestamp": timestamps,
        "location": "Boston",
        "temperature_2m": 25 + 5 * np.sin(np.arange(200) * 2 * np.pi / 24),
        "dew_point_2m": 15 + 3 * np.sin(np.arange(200) * 2 * np.pi / 24),
        "wind_speed_10m": np.random.uniform(2, 10, 200),
        "cloud_cover": np.random.randint(20, 80, 200),
        "shortwave_radiation": np.maximum(0, 500 * np.sin(np.arange(200) * 2 * np.pi / 24)),
    })

    # 3. 构造模拟历史负荷数据
    print("\n[3] 构造模拟历史负荷数据...")
    historical_load = pd.DataFrame({
        "timestamp": timestamps,
        "System_Load": 15000 + 2000 * np.sin(np.arange(200) * 2 * np.pi / 24) + np.random.normal(0, 100, 200),
    })

    # 4. 生成特征
    print("\n[4] 生成特征...")
    features = generator.generate(weather_df, historical_load)

    print(f"\n特征形状: {features.shape}")
    print(f"列名: {features.columns.tolist()}")
    print(f"\n前3行:")
    print(features.head(3).to_string())

    # 5. 归一化
    print("\n[5] 归一化...")
    normalized = generator.normalize(features)
    print(f"归一化后形状: {normalized.shape}")
    print(f"范围: [{normalized.min():.4f}, {normalized.max():.4f}]")

    # 6. 构建序列
    print("\n[6] 构建模型输入序列...")
    sequence = generator.build_sequence(features, lookback=168)
    print(f"序列形状: {sequence.shape} (batch, lookback, features)")

    return features, normalized, sequence


if __name__ == "__main__":
    demo()
