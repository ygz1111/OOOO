# -*- coding: utf-8 -*-
"""
数据处理脚本
============
对下载的原始数据进行清洗、异常值检测、合并，生成最终数据集。

处理步骤:
  1. 加载所有城市年份的原始 CSV
  2. 删除缺失值
  3. 异常值检测和修正
  4. 时间格式统一
  5. 多城市数据合并
  6. 生成 new_england_solar_dataset.csv
  7. 输出数据质量报告
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
from typing import List, Tuple

# ============================================================================
# 配置
# ============================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(SCRIPT_DIR, "raw")
PROCESSED_DIR = os.path.join(SCRIPT_DIR, "processed")
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# 最终输出的列顺序
FINAL_COLUMNS = [
    "timestamp", "latitude", "longitude", "city", "state",
    "temperature", "humidity", "wind_speed", "wind_direction",
    "pressure", "cloud_type", "cloud_low", "cloud_mid", "cloud_high",
    "precipitable_water", "ghi", "dni", "dhi",
    "direct_horizontal", "sunshine_duration",
    "year", "month", "day", "hour",
]

# 物理范围验证 (用于异常值检测)
VALIDATION_RANGES = {
    "ghi":              (0, 1400),      # W/m^2
    "dni":              (0, 1200),      # W/m^2
    "dhi":              (0, 800),       # W/m^2
    "direct_horizontal":(0, 1200),      # W/m^2
    "temperature":      (-40, 55),      # °C
    "humidity":         (0, 100),       # %
    "wind_speed":       (0, 60),        # m/s
    "wind_direction":   (0, 360),       # °
    "pressure":         (900, 1100),    # hPa
    "cloud_type":       (0, 100),       # %
    "cloud_low":        (0, 100),
    "cloud_mid":        (0, 100),
    "cloud_high":       (0, 100),
    "precipitable_water": (0, 50),      # mm
    "sunshine_duration": (0, 3600),     # s
}

# ============================================================================
# 日志
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(SCRIPT_DIR, "process.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================================
# 数据加载
# ============================================================================

# 坐标到城市映射 (新英格兰6州)
COORD_TO_CITY = {
    (42.3601, -71.0589): ("Boston", "MA"),       # Massachusetts
    (41.7658, -72.6734): ("Hartford", "CT"),     # Connecticut
    (41.8240, -71.4128): ("Providence", "RI"),   # Rhode Island
    (43.6591, -70.2568): ("Portland", "ME"),     # Maine
    (42.9956, -71.4548): ("Manchester", "NH"),  # New Hampshire
    (44.4759, -73.2121): ("Burlington", "VT"),  # Vermont
}


def coord_to_city(lat: float, lon: float) -> Tuple[str, str]:
    """根据经纬度匹配城市名"""
    for (clat, clon), (city, state) in COORD_TO_CITY.items():
        if abs(lat - clat) < 0.01 and abs(lon - clon) < 0.01:
            return city, state
    return "Unknown", "Unknown"


def load_all_raw_data() -> pd.DataFrame:
    """加载所有原始 CSV 文件并合并"""
    all_dfs = []
    csv_files = sorted([f for f in os.listdir(RAW_DIR) if f.endswith(".csv")])

    if not csv_files:
        raise FileNotFoundError(f"在 {RAW_DIR} 中未找到 CSV 文件!")

    logger.info(f"找到 {len(csv_files)} 个原始数据文件")

    for fname in csv_files:
        fpath = os.path.join(RAW_DIR, fname)
        df = pd.read_csv(fpath, parse_dates=["timestamp"])

        # 从文件名提取城市名
        city_name = fname.split("_")[0]

        # 添加 city 和 state 列
        lat = df["latitude"].iloc[0]
        lon = df["longitude"].iloc[0]
        city, state = coord_to_city(lat, lon)
        df["city"] = city
        df["state"] = state

        logger.info(f"  {fname}: {len(df)} 行, {df['timestamp'].min()} ~ {df['timestamp'].max()}, city={city}")
        all_dfs.append(df)

    combined = pd.concat(all_dfs, ignore_index=True)
    logger.info(f"合并后: {len(combined)} 行, {len(combined.columns)} 列")
    return combined


# ============================================================================
# 数据清洗
# ============================================================================

def check_and_clean_missing(df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    """缺失值检测和处理"""
    report = {"step": "缺失值处理", "details": {}}
    initial_count = len(df)

    # 统计各列缺失值
    missing_stats = df.isnull().sum()
    missing_cols = missing_stats[missing_stats > 0]

    report["details"]["initial_rows"] = initial_count
    report["details"]["missing_by_column"] = missing_cols.to_dict()

    if len(missing_cols) > 0:
        logger.info(f"  缺失值统计:")
        for col, cnt in missing_cols.items():
            pct = cnt / initial_count * 100
            logger.info(f"    {col}: {cnt} ({pct:.2f}%)")
            report["details"][f"{col}_missing"] = cnt
            report["details"][f"{col}_missing_pct"] = round(pct, 2)

        # 对数值列进行线性插值
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            if df[col].isnull().sum() > 0:
                df[col] = df[col].interpolate(method="linear", limit_direction="both")

        # 删除仍有缺失的行
        before_drop = len(df)
        df = df.dropna()
        after_drop = len(df)
        dropped = before_drop - after_drop
        logger.info(f"  插值后删除剩余缺失行: {dropped} 行")
        report["details"]["rows_after_interpolation"] = len(df)
        report["details"]["dropped_after_interpolation"] = dropped
    else:
        logger.info("  无缺失值")

    report["details"]["final_rows"] = len(df)
    report["details"]["total_dropped"] = initial_count - len(df)
    return df, report


def detect_and_fix_outliers(df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    """异常值检测和修正"""
    report = {"step": "异常值检测", "details": {}}
    total_outliers = 0

    logger.info("  物理范围验证:")
    for col, (min_val, max_val) in VALIDATION_RANGES.items():
        if col not in df.columns:
            continue

        # 检测超出范围的值
        mask = (df[col] < min_val) | (df[col] > max_val)
        outlier_count = mask.sum()

        if outlier_count > 0:
            pct = outlier_count / len(df) * 100
            logger.warning(f"    {col}: {outlier_count} 个异常值 "
                          f"(超出 [{min_val}, {max_val}]), {pct:.2f}%")
            report["details"][col] = {
                "count": int(outlier_count),
                "pct": round(pct, 4),
                "range": [min_val, max_val],
                "min_found": float(df[col].min()),
                "max_found": float(df[col].max()),
            }

            # 修正: 将超出范围的值截断到边界
            df.loc[df[col] < min_val, col] = min_val
            df.loc[df[col] > max_val, col] = max_val
            total_outliers += outlier_count
        else:
            report["details"][col] = {"count": 0}

    # 逻辑检查: GHI 应 >= DHI
    if "ghi" in df.columns and "dhi" in df.columns:
        bad_mask = df["ghi"] < df["dhi"]
        bad_count = bad_mask.sum()
        if bad_count > 0:
            logger.warning(f"    GHI < DHI: {bad_count} 行, 修正 DHI = GHI")
            df.loc[bad_mask, "dhi"] = df.loc[bad_mask, "ghi"]
            report["details"]["ghi_lt_dhi"] = int(bad_count)

    # 逻辑检查: GHI 应 >= direct_horizontal
    if "ghi" in df.columns and "direct_horizontal" in df.columns:
        bad_mask = df["ghi"] < df["direct_horizontal"]
        bad_count = bad_mask.sum()
        if bad_count > 0:
            logger.warning(f"    GHI < direct_horizontal: {bad_count} 行, 修正")
            df.loc[bad_mask, "direct_horizontal"] = df.loc[bad_mask, "ghi"] * 0.8
            report["details"]["ghi_lt_direct"] = int(bad_count)

    # 夜间辐射应为 0
    if "ghi" in df.columns and "hour" in df.columns:
        night_mask = (df["hour"] < 5) | (df["hour"] > 21)
        night_ghi = df.loc[night_mask, "ghi"]
        non_zero = (night_ghi > 5).sum()
        if non_zero > 0:
            logger.info(f"    夜间 GHI > 5 W/m^2: {non_zero} 行, 置零")
            df.loc[night_mask & (df["ghi"] > 5), "ghi"] = 0
            df.loc[night_mask & (df["dhi"] > 5), "dhi"] = 0
            df.loc[night_mask & (df["dni"] > 5), "dni"] = 0
            df.loc[night_mask & (df["direct_horizontal"] > 5), "direct_horizontal"] = 0
            report["details"]["night_ghi_nonzero"] = int(non_zero)

    logger.info(f"  总异常值修正: {total_outliers}")
    report["details"]["total_outliers"] = total_outliers
    return df, report


def remove_duplicates(df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    """去重"""
    report = {"step": "去重", "details": {}}
    before = len(df)

    # 按 timestamp + city 去重
    df = df.drop_duplicates(subset=["timestamp", "city"], keep="first")
    after = len(df)
    dropped = before - after

    if dropped > 0:
        logger.info(f"  删除重复行: {dropped} 行 (按 timestamp + city)")
    else:
        logger.info("  无重复行")

    report["details"] = {"before": before, "after": after, "dropped": dropped}
    return df, report


def sort_and_finalize(df: pd.DataFrame) -> pd.DataFrame:
    """排序和最终格式化"""
    # 按城市和时间排序
    df = df.sort_values(["city", "timestamp"]).reset_index(drop=True)

    # 确保所有列都存在
    for col in FINAL_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan

    # 选择最终列顺序
    df = df[FINAL_COLUMNS]
    return df


# ============================================================================
# 主流程
# ============================================================================

def main():
    print("=" * 60)
    print("数据处理: 清洗、去重、异常值检测、合并")
    print("=" * 60)

    # 1. 加载原始数据
    print("\n[1/6] 加载原始数据...")
    df = load_all_raw_data()

    # 2. 去重
    print("\n[2/6] 去重...")
    df, dup_report = remove_duplicates(df)

    # 3. 缺失值处理
    print("\n[3/6] 缺失值检测和处理...")
    df, missing_report = check_and_clean_missing(df)

    # 4. 异常值检测和修正
    print("\n[4/6] 异常值检测和修正...")
    df, outlier_report = detect_and_fix_outliers(df)

    # 5. 排序和格式化
    print("\n[5/6] 排序和格式化...")
    df = sort_and_finalize(df)

    # 6. 保存最终数据集
    print("\n[6/6] 保存最终数据集...")
    output_file = os.path.join(SCRIPT_DIR, "new_england_solar_dataset.csv")
    df.to_csv(output_file, index=False)
    file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
    print(f"  保存: {output_file}")
    print(f"  大小: {file_size_mb:.1f} MB")
    print(f"  行数: {len(df):,}")
    print(f"  列数: {len(df.columns)}")

    # 数据概览
    print("\n" + "=" * 60)
    print("数据概览")
    print("=" * 60)
    print(f"  城市数: {df['city'].nunique()}")
    print(f"  城市列表: {sorted(df['city'].unique())}")
    print(f"  年份范围: {df['year'].min()} - {df['year'].max()}")
    print(f"  时间范围: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
    print(f"  总行数: {len(df):,}")

    print(f"\n  各城市行数:")
    for city, count in df.groupby("city").size().items():
        print(f"    {city}: {count:,} 行")

    print(f"\n  各年份行数:")
    for year, count in df.groupby("year").size().items():
        print(f"    {year}: {count:,} 行")

    # 数值统计
    print(f"\n  关键变量统计:")
    stats_cols = ["ghi", "dni", "dhi", "temperature", "humidity", "wind_speed", "pressure"]
    stats = df[stats_cols].describe().round(2)
    print(stats.to_string())

    # 保存处理报告
    import json
    full_report = {
        "total_rows": len(df),
        "total_columns": len(df.columns),
        "cities": sorted(df["city"].unique().tolist()),
        "year_range": [int(df["year"].min()), int(df["year"].max())],
        "time_range": [str(df["timestamp"].min()), str(df["timestamp"].max())],
        "reports": [dup_report, missing_report, outlier_report],
    }
    report_file = os.path.join(REPORTS_DIR, "data_processing_report.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(full_report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  处理报告: {report_file}")

    print(f"\n[完成] 下一步: python solar_data/analyze_data.py")
    return df


if __name__ == "__main__":
    main()
