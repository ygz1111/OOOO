"""
智能电网负荷预测 - 数据处理模块
第三步：时间特征工程

功能：
  1. 从 DatetimeIndex 中提取时间特征（hour, day_of_week, day_of_year, month 等）
  2. 对周期性特征进行正弦/余弦编码，保持周期连续性
  3. 构造布尔特征（is_weekend, is_holiday）
  4. 构造季节特征
  5. 删除原始 Date 和 Hr_End 列（信息已提取到新特征中）

正弦/余弦编码原理：
  对于周期为 T 的特征 x，编码为：
    sin(2π * x / T)  和  cos(2π * x / T)
  这样能保证 x=0 和 x=T-1 在编码空间中相邻（而不是相距最远）。
"""

import pandas as pd
import numpy as np
import os
import pickle

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(PROJECT_ROOT, "processed")

# 美国法定假日列表（2023-2025）
# 用于构造 is_holiday 特征
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
}


def load_step2_data():
    """加载第二步的输出"""
    fpath = os.path.join(PROCESSED_DIR, "step2_cleaned_data.pkl")
    with open(fpath, "rb") as f:
        df = pickle.load(f)
    print(f"[加载] {fpath} ({len(df)} 行, {df.shape[1]} 列)")
    return df


def extract_time_features(df):
    """
    从 DatetimeIndex 中提取时间特征。

    提取的特征：
      - hour: 小时 (0-23)
      - day_of_week: 星期几 (0=周一, 6=周日)
      - day_of_year: 年内第几天 (1-366)
      - month: 月份 (1-12)
      - week: 年内第几周 (1-53)
      - quarter: 季度 (1-4)
    """
    print("\n[特征] 提取时间特征...")

    idx = df.index

    # 基本时间特征
    df["hour"] = idx.hour               # 0-23
    df["day_of_week"] = idx.dayofweek   # 0=Monday, 6=Sunday
    df["day_of_year"] = idx.dayofyear   # 1-366
    df["month"] = idx.month             # 1-12
    df["week"] = idx.isocalendar().week.astype(int)  # 1-53
    df["quarter"] = idx.quarter         # 1-4

    print(f"  hour: [{df['hour'].min()}, {df['hour'].max()}]")
    print(f"  day_of_week: [{df['day_of_week'].min()}, {df['day_of_week'].max()}] (0=Mon, 6=Sun)")
    print(f"  day_of_year: [{df['day_of_year'].min()}, {df['day_of_year'].max()}]")
    print(f"  month: [{df['month'].min()}, {df['month'].max()}]")
    print(f"  week: [{df['week'].min()}, {df['week'].max()}]")
    print(f"  quarter: [{df['quarter'].min()}, {df['quarter'].max()}]")

    return df


def cyclical_encode(df, col, period, prefix=None):
    """
    对周期性特征进行正弦/余弦编码。

    Args:
        df: DataFrame
        col: 列名
        period: 周期长度（如 hour 的周期为 24）
        prefix: 编码后列名前缀（默认使用原列名）

    Returns:
        添加了 sin/cos 编码列的 DataFrame
    """
    if prefix is None:
        prefix = col

    sin_col = f"{prefix}_sin"
    cos_col = f"{prefix}_cos"

    df[sin_col] = np.sin(2 * np.pi * df[col] / period)
    df[cos_col] = np.cos(2 * np.pi * df[col] / period)

    return df


def add_cyclical_features(df):
    """
    对所有周期性时间特征进行正弦/余弦编码。

    编码方案：
      - hour (周期24): hour_sin, hour_cos
      - day_of_week (周期7): dow_sin, dow_cos
      - day_of_year (周期365): doy_sin, doy_cos
      - month (周期12): month_sin, month_cos
      - week (周期52): week_sin, week_cos

    注意：day_of_year 在闰年为366天，使用365作为周期近似（误差可忽略）
    """
    print("\n[特征] 正弦/余弦编码...")

    # 小时 (周期=24)
    df = cyclical_encode(df, "hour", period=24, prefix="hour")
    print(f"  hour -> hour_sin, hour_cos (period=24)")

    # 星期几 (周期=7)
    df = cyclical_encode(df, "day_of_week", period=7, prefix="dow")
    print(f"  day_of_week -> dow_sin, dow_cos (period=7)")

    # 年内第几天 (周期=365，闰年用365近似)
    df = cyclical_encode(df, "day_of_year", period=365, prefix="doy")
    print(f"  day_of_year -> doy_sin, doy_cos (period=365)")

    # 月份 (周期=12)
    df = cyclical_encode(df, "month", period=12, prefix="month")
    print(f"  month -> month_sin, month_cos (period=12)")

    # 周数 (周期=52)
    df = cyclical_encode(df, "week", period=52, prefix="week")
    print(f"  week -> week_sin, week_cos (period=52)")

    return df


def add_boolean_features(df):
    """
    构造布尔特征：
      - is_weekend: 是否周末 (周六或周日)
      - is_holiday: 是否美国法定假日
    """
    print("\n[特征] 构造布尔特征...")

    # 是否周末
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    weekend_count = df["is_weekend"].sum()
    print(f"  is_weekend: {weekend_count} 个周末小时 ({weekend_count/len(df)*100:.1f}%)")

    # 是否假日
    holiday_dates = set(US_HOLIDAYS)
    df["is_holiday"] = df.index.normalize().isin(
        [pd.Timestamp(d) for d in holiday_dates]
    ).astype(int)
    holiday_count = df["is_holiday"].sum()
    print(f"  is_holiday: {holiday_count} 个假日小时 ({holiday_count/len(df)*100:.1f}%)")

    return df


def add_season_feature(df):
    """
    构造季节特征。

    新英格兰地区季节划分：
      - 冬季 (12, 1, 2): 供暖高峰
      - 春季 (3, 4, 5): 过渡期
      - 夏季 (6, 7, 8): 制冷高峰
      - 秋季 (9, 10, 11): 过渡期

    编码方式：one-hot 编码（4个布尔列）
    """
    print("\n[特征] 构造季节特征...")

    def get_season(month):
        if month in (12, 1, 2):
            return "winter"
        elif month in (3, 4, 5):
            return "spring"
        elif month in (6, 7, 8):
            return "summer"
        else:
            return "fall"

    df["season"] = df["month"].apply(get_season)

    # One-hot 编码
    season_dummies = pd.get_dummies(df["season"], prefix="season", dtype=int)
    df = pd.concat([df, season_dummies], axis=1)

    for col in season_dummies.columns:
        print(f"  {col}: {df[col].sum()} 小时 ({df[col].sum()/len(df)*100:.1f}%)")

    # 删除字符串列 season
    df = df.drop(columns=["season"])

    return df


def clean_up_columns(df):
    """
    清理不再需要的列：
      - Date: 原始日期列，信息已提取到时间特征中
      - Hr_End: 原始小时列，已通过 hour 特征提取
      - Dry_Bulb_F, Dew_Point_F: 原始华氏度列，摄氏度已足够
      - 原始整数时间列（hour, day_of_week, day_of_year, month, week, quarter）
        保留它们用于分析，但标记为不参与归一化的类别特征

    注意：保留原始整数列是因为某些模型（如树模型）可以直接使用它们，
    且它们对可视化分析有帮助。
    """
    print("\n[特征] 清理列...")

    cols_to_drop = ["Date", "Hr_End", "Dry_Bulb_F", "Dew_Point_F"]
    for col in cols_to_drop:
        if col in df.columns:
            df = df.drop(columns=[col])
            print(f"  删除: {col}")

    return df


def save_step3_data(df):
    """保存第三步结果"""
    fpath = os.path.join(PROCESSED_DIR, "step3_time_features.pkl")
    with open(fpath, "wb") as f:
        pickle.dump(df, f)
    print(f"\n[保存] {fpath} ({len(df)} 行, {df.shape[1]} 列)")

    # 保存特征列表
    feature_info = {
        "target": ["RT_Demand", "System_Load"],
        "original_numeric": [
            "DA_Demand", "DA_LMP", "DA_EC", "DA_CC", "DA_MLC",
            "RT_LMP", "RT_EC", "RT_CC", "RT_MLC",
            "Dry_Bulb", "Dew_Point",
            "Reg_Service_Price", "Reg_Capacity_Price",
            "Min_5min_RSP", "Max_5min_RSP", "Min_5min_RCP", "Max_5min_RCP",
        ],
        "time_features_int": ["hour", "day_of_week", "day_of_year", "month", "week", "quarter"],
        "time_features_cyclical": [
            "hour_sin", "hour_cos", "dow_sin", "dow_cos",
            "doy_sin", "doy_cos", "month_sin", "month_cos",
            "week_sin", "week_cos",
        ],
        "boolean_features": ["is_weekend", "is_holiday", "dst_flag"],
        "season_features": ["season_fall", "season_spring", "season_summer", "season_winter"],
    }
    fpath = os.path.join(PROCESSED_DIR, "step3_feature_info.pkl")
    with open(fpath, "wb") as f:
        pickle.dump(feature_info, f)
    print(f"[保存] {fpath}")


# ============================================================================
# 主流程：执行第三步时间特征工程
# ============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("第三步：时间特征工程")
    print("=" * 70)

    # 1. 加载第二步数据
    df = load_step2_data()

    # 2. 提取时间特征
    df = extract_time_features(df)

    # 3. 正弦/余弦编码
    df = add_cyclical_features(df)

    # 4. 布尔特征
    df = add_boolean_features(df)

    # 5. 季节特征
    df = add_season_feature(df)

    # 6. 清理列
    df = clean_up_columns(df)

    # 7. 保存
    save_step3_data(df)

    # 8. 概览
    print("\n" + "=" * 70)
    print("特征工程后数据概览")
    print("=" * 70)
    print(f"形状: {df.shape}")
    print(f"\n所有列名 ({len(df.columns)}):")
    for i, col in enumerate(df.columns):
        print(f"  [{i:2d}] {col:30s} dtype={df[col].dtype}")

    print(f"\n前3行 (部分列):")
    display_cols = ["hour", "hour_sin", "hour_cos", "day_of_week", "dow_sin", "dow_cos",
                    "is_weekend", "is_holiday", "season_winter", "Dry_Bulb", "RT_Demand"]
    display_cols = [c for c in display_cols if c in df.columns]
    print(df[display_cols].head(3).to_string())

    print("\n[第三步完成]")
