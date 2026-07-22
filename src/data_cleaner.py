"""
智能电网负荷预测 - 数据处理模块
第二步：数据类型统一与清洗

功能：
  1. 统一 Hr_End 为 int 类型（2023是int, 2024/2025是零填充字符串）
  2. 用 Date + Hr_End 构造完整的 timestamp 列，设为 DatetimeIndex
  3. 验证时间序列连续性（检查是否有缺失的小时）
  4. 异常值检测（IQR方法 + 物理合理性检查）
  5. 温度单位转换（°F → °C，便于理解和可视化）
  6. 保存清洗后的数据
"""

import pandas as pd
import numpy as np
import os
import sys
import pickle

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(PROJECT_ROOT, "processed")


def load_step1_data():
    """加载第一步的输出"""
    fpath = os.path.join(PROCESSED_DIR, "step1_system_data.pkl")
    with open(fpath, "rb") as f:
        df = pickle.load(f)
    print(f"[加载] {fpath} ({len(df)} 行)")
    return df


def unify_hr_end(df):
    """
    统一 Hr_End 列为 int 类型，正确处理夏令时特殊标记 '02X'。

    背景：
      - 2023年: int64 (1, 2, 3, ..., 24)
      - 2024年: object ("01", "02", ..., "24", 含 "02X")
      - 2025年: object ("01", "02", ..., "24", 含 "02X")

    夏令时处理：
      秋季回拨（11月初）：时钟从 2:00 回到 1:00，2:00 这一小时出现两次。
      ISO-NE 用 "02X" 标记回拨前（夏令时期间）的那个 2:00，
      用 "02" 标记回拨后（标准时间期间）的那个 2:00。

      我们的策略：将 02X 也映射为 hour=2，但添加 dst_flag 列区分。
      在构造时间戳时，02X 对应的时间戳与 02 相同（都是该日的 02:00），
      但我们用 dst_flag=1 标记它，后续按等间距重索引时自然处理。

    统一后:
      - Hr_End: int64 (1, 2, 3, ..., 24)
      - dst_flag: int (0=标准时间, 1=夏令时期间的重复小时)
    """
    print("\n[清洗] 统一 Hr_End 类型...")

    # 记录清洗前的状态
    print(f"  清洗前 dtype: {df['Hr_End'].dtype}")
    hr_end_str = df["Hr_End"].astype(str)
    unique_before = hr_end_str.unique()
    print(f"  清洗前唯一值: {sorted(unique_before)}")

    # 检测并标记夏令时特殊标记 '02X'
    dst_mask = hr_end_str.str.contains("X", na=False)
    dst_count = dst_mask.sum()
    print(f"  发现 {dst_count} 个夏令时标记 '02X' (秋季回拨重复小时)")
    if dst_count > 0:
        dst_rows = df[dst_mask][["Date", "Hr_End"]].copy()
        print(f"  涉及日期: {dst_rows['Date'].dt.date.tolist()}")

    # 添加 dst_flag 列
    df["dst_flag"] = dst_mask.astype(int)

    # 去掉 X 后缀，去掉前导零，转为 int
    hr_end_clean = hr_end_str.str.replace("X", "", regex=False)
    hr_end_clean = hr_end_clean.str.lstrip("0").replace("", "0").astype(int)
    df["Hr_End"] = hr_end_clean

    print(f"  清洗后 dtype: {df['Hr_End'].dtype}")
    print(f"  清洗后唯一值: {sorted(df['Hr_End'].unique())}")

    # 验证：Hr_End 应该是 1~24
    assert df["Hr_End"].min() >= 1, f"Hr_End 最小值异常: {df['Hr_End'].min()}"
    assert df["Hr_End"].max() <= 24, f"Hr_End 最大值异常: {df['Hr_End'].max()}"
    print(f"  [OK] Hr_End 范围验证通过: [{df['Hr_End'].min()}, {df['Hr_End'].max()}]")

    return df


def build_timestamp(df):
    """
    用 Date + Hr_End 构造完整的 timestamp 列，设为 DatetimeIndex。

    Hr_End 使用 "小时结束" 约定：
      Hr_End=1  表示 00:00~01:00 这一小时，时间戳记为 00:00
      Hr_End=2  表示 01:00~02:00 这一小时，时间戳记为 01:00
      ...
      Hr_End=24 表示 23:00~24:00 这一小时，时间戳记为 23:00

    因此 timestamp = Date + (Hr_End - 1) 小时

    夏令时处理：
      秋季回拨日（11月初）有两条 Hr_End=2 的记录（dst_flag=0 和 dst_flag=1），
      它们的 timestamp 相同（都是该日 02:00）。
      策略：对重复时间戳取平均值，合并为一条记录。
      春季前调日（3月中旬）时钟从 2:00 跳到 3:00，Hr_End=2 被跳过，
      策略：在 asfreq('h') 后用线性插值补全缺失的小时。
    """
    print("\n[清洗] 构造完整时间戳 timestamp...")

    # Hr_End=1 -> hour 0, Hr_End=24 -> hour 23
    df["timestamp"] = df["Date"] + pd.to_timedelta(df["Hr_End"] - 1, unit="h")

    # 验证时间戳范围
    print(f"  时间戳范围: {df['timestamp'].min()} ~ {df['timestamp'].max()}")

    # 检查是否有重复时间戳（由秋季回拨的 02X 导致）
    dup_count = df["timestamp"].duplicated().sum()
    if dup_count > 0:
        print(f"  [INFO] 发现 {dup_count} 个重复时间戳（秋季回拨 02X）")
        dups = df[df["timestamp"].duplicated(keep=False)].sort_values("timestamp")
        print(dups[["timestamp", "Hr_End", "dst_flag"]].head(10).to_string())
        print(f"  -> 对重复时间戳取平均值合并")
    else:
        print(f"  [OK] 无重复时间戳")

    # 设为索引并排序
    df = df.set_index("timestamp")
    df = df.sort_index()

    # 对重复时间戳取平均值（仅影响秋季回拨日的 02:00）
    if dup_count > 0:
        # dst_flag 取 max（如果有任一是1则保留为1）
        dst_series = df["dst_flag"].groupby(level=0).max()
        # 其他列取均值
        df = df.groupby(level=0).mean()
        df["dst_flag"] = dst_series
        print(f"  [OK] 重复时间戳已合并，当前行数: {len(df)}")

    return df


def verify_time_continuity(df):
    """
    验证时间序列连续性。

    理论上，从 2023-01-01 00:00 到 2025-12-31 23:00，
    每小时一条记录，应该完全连续无缺口。
    """
    print("\n[清洗] 验证时间序列连续性...")

    # 生成完整的时间范围
    full_range = pd.date_range(
        start=df.index.min(),
        end=df.index.max(),
        freq="h"  # 每小时
    )

    print(f"  期望时间点数: {len(full_range)}")
    print(f"  实际时间点数: {len(df)}")

    # 找出缺失的时间点
    missing = full_range.difference(df.index)
    if len(missing) == 0:
        print(f"  [OK] 时间序列完全连续，无缺失小时")
    else:
        print(f"  [WARNING] 发现 {len(missing)} 个缺失时间点:")
        print(f"  前10个缺失: {missing[:10].tolist()}")
        print(f"  后10个缺失: {missing[-10:].tolist()}")

    return len(missing) == 0


def detect_outliers_iqr(series, name, k=3.0):
    """
    使用 IQR (四分位距) 方法检测异常值。

    IQR = Q3 - Q1
    下界 = Q1 - k * IQR
    上界 = Q3 + k * IQR

    k=3.0 为保守阈值（标准 k=1.5 可能对电力数据过于激进）
    """
    Q1 = series.quantile(0.25)
    Q3 = series.quantile(0.75)
    IQR = Q3 - Q1
    lower = Q1 - k * IQR
    upper = Q3 + k * IQR

    outliers = (series < lower) | (series > upper)
    return outliers, lower, upper


def detect_anomalies(df):
    """
    异常值检测：
    1. 物理合理性检查（负需求、不合理温度等）
    2. IQR 统计异常检测（k=3.0）
    """
    print("\n[清洗] 异常值检测...")

    # === 1. 物理合理性检查 ===
    print("\n  --- 物理合理性检查 ---")

    # 需求不应为负
    for col in ["DA_Demand", "RT_Demand", "System_Load"]:
        neg_count = (df[col] < 0).sum()
        if neg_count > 0:
            print(f"  [WARNING] {col} 有 {neg_count} 个负值")
        else:
            print(f"  [OK] {col} 无负值 (最小值: {df[col].min():.2f})")

    # 温度范围检查（°F，新英格兰地区大约 -30°F ~ 110°F）
    for col in ["Dry_Bulb", "Dew_Point"]:
        min_val = df[col].min()
        max_val = df[col].max()
        if min_val < -30 or max_val > 110:
            print(f"  [WARNING] {col} 超出合理范围: [{min_val}, {max_val}]")
        else:
            print(f"  [OK] {col} 范围合理: [{min_val}, {max_val}] °F")

    # 电价检查（LMP 通常为正，但拥堵分量可能为负）
    for col in ["DA_LMP", "RT_LMP"]:
        neg_count = (df[col] < 0).sum()
        if neg_count > 0:
            print(f"  [INFO] {col} 有 {neg_count} 个负值（可能为负电价事件）")
        else:
            print(f"  [OK] {col} 无负值 (最小值: {df[col].min():.2f})")

    # === 2. IQR 统计异常检测 ===
    print("\n  --- IQR 异常检测 (k=3.0) ---")
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    anomaly_summary = {}

    for col in numeric_cols:
        if col in ("year", "dst_flag"):
            continue
        outliers, lower, upper = detect_outliers_iqr(df[col], col, k=3.0)
        count = outliers.sum()
        if count > 0:
            pct = count / len(df) * 100
            print(f"  {col}: {count} 个异常值 ({pct:.2f}%), 范围 [{lower:.2f}, {upper:.2f}]")
            anomaly_summary[col] = {
                "count": count,
                "pct": pct,
                "lower": lower,
                "upper": upper,
                "outlier_indices": df.index[outliers].tolist()
            }
        else:
            print(f"  {col}: 无异常值")

    return anomaly_summary


def convert_temperature(df):
    """
    将温度从华氏度 (°F) 转换为摄氏度 (°C)。

    转换公式: °C = (°F - 32) × 5/9

    同时保留原始华氏度列（加后缀 _F），便于参考。
    """
    print("\n[清洗] 温度单位转换 °F → °C...")

    # 保留原始华氏度列
    df["Dry_Bulb_F"] = df["Dry_Bulb"]
    df["Dew_Point_F"] = df["Dew_Point"]

    # 转换为摄氏度
    df["Dry_Bulb"] = (df["Dry_Bulb_F"] - 32) * 5.0 / 9.0
    df["Dew_Point"] = (df["Dew_Point_F"] - 32) * 5.0 / 9.0

    # 四舍五入到一位小数
    df["Dry_Bulb"] = df["Dry_Bulb"].round(1)
    df["Dew_Point"] = df["Dew_Point"].round(1)

    print(f"  Dry_Bulb (°C): [{df['Dry_Bulb'].min():.1f}, {df['Dry_Bulb'].max():.1f}]")
    print(f"  Dew_Point (°C): [{df['Dew_Point'].min():.1f}, {df['Dew_Point'].max():.1f}]")

    return df


def drop_unnecessary_columns(df):
    """
    删除不需要的列：
    - year: 仅用于加载标记，不再需要
    - Date: 已被 timestamp 索引替代
    - Hr_End: 将在第三步重新提取为时间特征
    注意：暂时保留 Hr_End 和 Date，到特征工程步骤再处理
    """
    # 暂时只删除 year（Date 和 Hr_End 后续可能用到）
    df = df.drop(columns=["year"])
    return df


def save_step2_data(df, anomaly_summary):
    """保存第二步结果"""
    # 保存清洗后的数据
    fpath = os.path.join(PROCESSED_DIR, "step2_cleaned_data.pkl")
    with open(fpath, "wb") as f:
        pickle.dump(df, f)
    print(f"\n[保存] {fpath} ({len(df)} 行, {df.shape[1]} 列)")

    # 保存异常值报告
    fpath = os.path.join(PROCESSED_DIR, "step2_anomaly_report.pkl")
    with open(fpath, "wb") as f:
        pickle.dump(anomaly_summary, f)
    print(f"[保存] {fpath}")

    # 保存清洗报告文本
    fpath = os.path.join(PROCESSED_DIR, "step2_cleaning_report.txt")
    with open(fpath, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write("第二步：数据清洗报告\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"总行数: {len(df)}\n")
        f.write(f"总列数: {df.shape[1]}\n")
        f.write(f"时间范围: {df.index.min()} ~ {df.index.max()}\n")
        f.write(f"列名: {list(df.columns)}\n\n")
        f.write("--- 各列统计信息 ---\n")
        f.write(df.describe().to_string())
        f.write("\n\n--- 异常值检测摘要 ---\n")
        for col, info in anomaly_summary.items():
            f.write(f"{col}: {info['count']} 个异常值 ({info['pct']:.2f}%), "
                    f"IQR范围 [{info['lower']:.2f}, {info['upper']:.2f}]\n")
    print(f"[保存] {fpath}")


# ============================================================================
# 主流程：执行第二步数据清洗
# ============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("第二步：数据类型统一与清洗")
    print("=" * 70)

    # 1. 加载第一步数据
    df = load_step1_data()

    # 2. 统一 Hr_End 类型
    df = unify_hr_end(df)

    # 3. 构造时间戳索引
    df = build_timestamp(df)

    # 4. 验证时间连续性
    is_continuous = verify_time_continuity(df)
    if not is_continuous:
        print("[INFO] 时间序列存在缺口（由夏令时春季前调导致），将进行插值补全")
        # 对缺失的小时进行线性插值
        df = df.asfreq('h')  # 以1小时频率重索引，缺失位置变为NaN
        # 对数值列进行线性插值
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df[numeric_cols] = df[numeric_cols].interpolate(method='time')
        # dst_flag 插值后可能为 NaN，填充为 0
        df['dst_flag'] = df['dst_flag'].fillna(0).astype(int)
        print(f"  [OK] 插值完成，当前行数: {len(df)}")
        # 重新验证
        verify_time_continuity(df)

    # 5. 异常值检测
    anomaly_summary = detect_anomalies(df)

    # 6. 温度单位转换
    df = convert_temperature(df)

    # 7. 删除不需要的列
    df = drop_unnecessary_columns(df)

    # 8. 保存结果
    save_step2_data(df, anomaly_summary)

    # 9. 最终数据概览
    print("\n" + "=" * 70)
    print("清洗后数据概览")
    print("=" * 70)
    print(f"形状: {df.shape}")
    print(f"索引类型: {type(df.index)}")
    print(f"时间范围: {df.index.min()} ~ {df.index.max()}")
    print(f"\n前3行:")
    print(df.head(3).to_string())
    print(f"\n后3行:")
    print(df.tail(3).to_string())
    print(f"\n各列数据类型:")
    for col, dtype in df.dtypes.items():
        print(f"  {col:25s} {dtype}")

    print("\n[第二步完成]")
