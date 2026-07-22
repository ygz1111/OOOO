"""
智能电网负荷预测 - 数据处理模块
第四步：特征构造与筛选

功能：
  1. 气象衍生特征：
     - humidity_index: 湿度指标 (Dry_Bulb - Dew_Point)
     - cooling_degree: 制冷度日 max(0, Dry_Bulb - 18°C)
     - heating_degree: 供暖度日 max(0, 18°C - Dry_Bulb)
     - temp_range_24h: 过去24小时温度变化范围

  2. 滞后特征 (Lag Features)：
     - load_lag_1h:   前1小时负荷
     - load_lag_24h:  前24小时（昨天同时刻）负荷
     - load_lag_168h: 前168小时（上周同时刻）负荷
     - temp_lag_24h:  前24小时温度
     - load_lag_48h:  前48小时（前天同时刻）负荷

  3. 滑动窗口特征 (Rolling Window Features)：
     - load_rolling_mean_24h:  过去24小时负荷均值
     - load_rolling_std_24h:   过去24小时负荷标准差
     - load_rolling_mean_168h: 过去168小时(1周)负荷均值
     - temp_rolling_mean_24h:  过去24小时温度均值
     - temp_rolling_max_24h:   过去24小时温度最高值
     - temp_rolling_min_24h:   过去24小时温度最低值

  4. 特征筛选：
     - 确定预测目标: System_Load (实际系统负荷)
     - 筛选最终输入特征列表
     - 删除电价类特征（避免数据泄露，因为实时预测时电价不可知）

注意：
  - 滞后和滑动窗口特征会产生前 N 行的 NaN，需要删除这些行
  - 滑动窗口使用 shift(1) 确保只使用过去数据，不含当前时刻
"""

import pandas as pd
import numpy as np
import os
import pickle

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(PROJECT_ROOT, "processed")

# 预测目标
TARGET = "System_Load"

# 基准温度（用于度日计算）
# 新英格兰地区供暖/制冷基准温度通常取 18°C (65°F)
BASE_TEMP_C = 18.0


def load_step3_data():
    """加载第三步的输出"""
    fpath = os.path.join(PROCESSED_DIR, "step3_time_features.pkl")
    with open(fpath, "rb") as f:
        df = pickle.load(f)
    print(f"[加载] {fpath} ({len(df)} 行, {df.shape[1]} 列)")
    return df


def add_weather_derived_features(df):
    """
    构造气象衍生特征。

    1. humidity_index (湿度指标):
       Dry_Bulb - Dew_Point，差值越小表示湿度越高。
       当差值为0时，相对湿度为100%。

    2. cooling_degree (制冷度日):
       max(0, Dry_Bulb - 18°C)
       当温度高于18°C时，制冷需求开始增加。

    3. heating_degree (供暖度日):
       max(0, 18°C - Dry_Bulb)
       当温度低于18°C时，供暖需求开始增加。

    这两个特征直接反映了温度对电力负荷的非线性影响：
    负荷在极端高温和极端低温时都会升高（制冷/供暖），
    而在温和温度（~18°C）时最低。
    """
    print("\n[特征] 构造气象衍生特征...")

    # 湿度指标
    df["humidity_index"] = df["Dry_Bulb"] - df["Dew_Point"]
    print(f"  humidity_index: [{df['humidity_index'].min():.1f}, {df['humidity_index'].max():.1f}]")

    # 制冷度日
    df["cooling_degree"] = np.maximum(0, df["Dry_Bulb"] - BASE_TEMP_C)
    cooling_hours = (df["cooling_degree"] > 0).sum()
    print(f"  cooling_degree: 非零小时数={cooling_hours} ({cooling_hours/len(df)*100:.1f}%)")

    # 供暖度日
    df["heating_degree"] = np.maximum(0, BASE_TEMP_C - df["Dry_Bulb"])
    heating_hours = (df["heating_degree"] > 0).sum()
    print(f"  heating_degree: 非零小时数={heating_hours} ({heating_hours/len(df)*100:.1f}%)")

    return df


def add_lag_features(df):
    """
    构造滞后特征。

    滞后特征是时间序列预测中最重要的特征之一。
    电力负荷具有强烈的日周期性和周周期性，
    因此前24小时（昨天）和前168小时（上周）的负荷是最强的预测因子。

    使用 shift(1) 确保使用的是"过去"的数据，不包含当前时刻。
    """
    print("\n[特征] 构造滞后特征...")

    # 负荷滞后特征
    lag_configs = [
        (TARGET, 1, "load_lag_1h"),       # 前1小时
        (TARGET, 24, "load_lag_24h"),     # 前24小时（昨天同时刻）
        (TARGET, 48, "load_lag_48h"),     # 前48小时（前天同时刻）
        (TARGET, 168, "load_lag_168h"),   # 前168小时（上周同时刻）
    ]

    for source_col, lag, new_col in lag_configs:
        df[new_col] = df[source_col].shift(lag)
        print(f"  {new_col} = {source_col}.shift({lag})")

    # 温度滞后特征
    temp_lag_configs = [
        ("Dry_Bulb", 24, "temp_lag_24h"),   # 前24小时温度
        ("Dry_Bulb", 168, "temp_lag_168h"),  # 上周同时刻温度
    ]

    for source_col, lag, new_col in temp_lag_configs:
        df[new_col] = df[source_col].shift(lag)
        print(f"  {new_col} = {source_col}.shift({lag})")

    return df


def add_rolling_features(df):
    """
    构造滑动窗口特征。

    滑动窗口特征捕捉近期趋势和波动性。
    使用 shift(1) 确保窗口不包含当前时刻（避免数据泄露）。

    窗口大小选择：
      - 24h: 捕捉日内趋势和波动
      - 168h: 捕捉周趋势
    """
    print("\n[特征] 构造滑动窗口特征...")

    # 先 shift(1) 再 rolling，确保窗口只含过去数据
    # 负荷滑动窗口
    df["load_rolling_mean_24h"] = df[TARGET].shift(1).rolling(window=24).mean()
    df["load_rolling_std_24h"] = df[TARGET].shift(1).rolling(window=24).std()
    df["load_rolling_mean_168h"] = df[TARGET].shift(1).rolling(window=168).mean()
    df["load_rolling_min_24h"] = df[TARGET].shift(1).rolling(window=24).min()
    df["load_rolling_max_24h"] = df[TARGET].shift(1).rolling(window=24).max()
    print(f"  load_rolling_mean_24h, load_rolling_std_24h, load_rolling_mean_168h")
    print(f"  load_rolling_min_24h, load_rolling_max_24h")

    # 温度滑动窗口
    df["temp_rolling_mean_24h"] = df["Dry_Bulb"].shift(1).rolling(window=24).mean()
    df["temp_rolling_max_24h"] = df["Dry_Bulb"].shift(1).rolling(window=24).max()
    df["temp_rolling_min_24h"] = df["Dry_Bulb"].shift(1).rolling(window=24).min()
    print(f"  temp_rolling_mean_24h, temp_rolling_max_24h, temp_rolling_min_24h")

    return df


def add_load_change_features(df):
    """
    构造负荷变化率特征。

    这些特征捕捉负荷的动态变化趋势：
      - load_diff_1h: 与前1小时的差值（短期变化）
      - load_diff_24h: 与前24小时的差值（日间变化）
      - load_pct_change_24h: 24小时变化率
    """
    print("\n[特征] 构造负荷变化特征...")

    df["load_diff_1h"] = df[TARGET].diff(1)
    df["load_diff_24h"] = df[TARGET].diff(24)
    df["load_pct_change_24h"] = df[TARGET].pct_change(periods=24)
    print(f"  load_diff_1h, load_diff_24h, load_pct_change_24h")

    return df


def drop_nan_rows(df):
    """
    删除由滞后/滑动窗口产生的 NaN 行。

    最大窗口为 168h (1周)，因此前 168 行会产生 NaN。
    同时 shift(1).rolling(168) 需要 169 行才能产生第一个非 NaN 值。
    所以需要删除前 168+1 = 169 行。

    但为了精确，我们直接删除所有包含 NaN 的行。
    """
    print("\n[特征] 删除 NaN 行...")

    before_count = len(df)
    df = df.dropna()
    after_count = len(df)

    dropped = before_count - after_count
    print(f"  删除前: {before_count} 行")
    print(f"  删除后: {after_count} 行")
    print(f"  删除: {dropped} 行 ({dropped/before_count*100:.2f}%)")
    print(f"  剩余数据时间范围: {df.index.min()} ~ {df.index.max()}")

    return df


def select_final_features(df):
    """
    筛选最终输入特征。

    筛选原则：
      1. 保留时间特征（正弦/余弦编码 + 布尔 + 季节）
      2. 保留气象特征（温度 + 衍生特征）
      3. 保留滞后/滑动窗口特征
      4. 排除电价类特征（DA_LMP, RT_LMP 等）：
         原因：在实际负荷预测场景中，电价本身也是需要预测的变量，
         使用未来电价预测负荷会造成数据泄露。
      5. 排除调频市场特征（Reg_Service_Price 等）：
         原因：同上，且与负荷的直接关系较弱。
      6. 排除 DA_Demand, RT_Demand：
         原因：这些也是"需求"变量，与 System_Load 高度相关，
         使用它们预测 System_Load 本质上是同义反复。
      7. 排除原始整数时间特征（hour, day_of_week 等）：
         原因：已通过正弦/余弦编码表达，保留整数列会造成冗余。

    预测目标: System_Load
    """
    print("\n[特征] 筛选最终特征...")

    # 预测目标
    target = TARGET

    # 要排除的列
    exclude_cols = {
        # 电价类（数据泄露风险）
        "DA_LMP", "DA_EC", "DA_CC", "DA_MLC",
        "RT_LMP", "RT_EC", "RT_CC", "RT_MLC",
        # 调频市场（与负荷关系间接）
        "Reg_Service_Price", "Reg_Capacity_Price",
        "Min_5min_RSP", "Max_5min_RSP",
        "Min_5min_RCP", "Max_5min_RCP",
        # 需求类（与目标高度相关，同义反复）
        "DA_Demand", "RT_Demand",
        # 原始整数时间特征（已有正余弦编码替代）
        "hour", "day_of_week", "day_of_year", "month", "week", "quarter",
        # dst_flag（夏令时标记，预测价值低）
        "dst_flag",
        # 目标列本身
        target,
    }

    # 最终特征列表 = 所有列 - 排除列 - 目标列
    feature_cols = [col for col in df.columns if col not in exclude_cols]

    print(f"\n  预测目标: {target}")
    print(f"\n  输入特征 ({len(feature_cols)} 个):")
    for i, col in enumerate(feature_cols):
        print(f"    [{i:2d}] {col}")

    print(f"\n  排除的列 ({len(exclude_cols)} 个):")
    for col in sorted(exclude_cols):
        print(f"    - {col}")

    return feature_cols, target


def save_step4_data(df, feature_cols, target):
    """保存第四步结果"""
    # 保存完整数据
    fpath = os.path.join(PROCESSED_DIR, "step4_engineered_data.pkl")
    with open(fpath, "wb") as f:
        pickle.dump(df, f)
    print(f"\n[保存] {fpath} ({len(df)} 行, {df.shape[1]} 列)")

    # 保存特征配置
    config = {
        "feature_cols": feature_cols,
        "target": target,
        "all_columns": list(df.columns),
    }
    fpath = os.path.join(PROCESSED_DIR, "step4_feature_config.pkl")
    with open(fpath, "wb") as f:
        pickle.dump(config, f)
    print(f"[保存] {fpath}")

    # 保存特征+目标的子集（便于后续使用）
    model_data = df[feature_cols + [target]].copy()
    fpath = os.path.join(PROCESSED_DIR, "step4_model_data.pkl")
    with open(fpath, "wb") as f:
        pickle.dump(model_data, f)
    print(f"[保存] {fpath} ({len(model_data)} 行, {len(model_data.columns)} 列)")


# ============================================================================
# 主流程：执行第四步特征构造
# ============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("第四步：特征构造与筛选")
    print("=" * 70)

    # 1. 加载第三步数据
    df = load_step3_data()

    # 2. 气象衍生特征
    df = add_weather_derived_features(df)

    # 3. 滞后特征
    df = add_lag_features(df)

    # 4. 滑动窗口特征
    df = add_rolling_features(df)

    # 5. 负荷变化特征
    df = add_load_change_features(df)

    # 6. 删除 NaN 行
    df = drop_nan_rows(df)

    # 7. 特征筛选
    feature_cols, target = select_final_features(df)

    # 8. 保存
    save_step4_data(df, feature_cols, target)

    # 9. 概览
    print("\n" + "=" * 70)
    print("特征构造后数据概览")
    print("=" * 70)
    print(f"完整数据形状: {df.shape}")
    print(f"模型数据形状: ({len(df)}, {len(feature_cols) + 1}) [特征+目标]")
    print(f"预测目标: {target}")
    print(f"输入特征数: {len(feature_cols)}")

    # 显示模型数据的前3行
    model_data = df[feature_cols + [target]]
    print(f"\n模型数据前3行:")
    print(model_data.head(3).to_string())

    # 检查 NaN
    nan_count = model_data.isnull().sum().sum()
    print(f"\nNaN 总数: {nan_count}")

    print("\n[第四步完成]")
