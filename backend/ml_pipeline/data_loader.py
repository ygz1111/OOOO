"""
智能电网负荷预测 - 数据处理模块
第一步：数据加载与合并

功能：
  1. 从 2023/2024/2025 三个 Excel 文件中读取 ISO NE CA (系统级) 数据
  2. 同时加载 8 个区域 Sheet 数据备用
  3. 纵向合并三年数据，添加 year 列标记来源
  4. 输出合并后的统一 DataFrame
"""

import pandas as pd
import numpy as np
import os
import sys
import pickle

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "datas")
PROCESSED_DIR = os.path.join(PROJECT_ROOT, "processed")

# 数据文件列表
FILES = [
    "2023_smd_hourly.xlsx",
    "2024_smd_hourly.xlsx",
    "2025_smd_hourly.xlsx",
]

# 区域 Sheet 名称（不含 Notes 和 ISO NE CA）
REGION_SHEETS = ["ME", "NH", "VT", "CT", "RI", "SEMA", "WCMA", "NEMA"]

# ISO NE CA Sheet 名
SYSTEM_SHEET = "ISO NE CA"


def load_system_data():
    """
    加载 ISO NE CA (系统级汇总) 数据，合并三年。

    ISO NE CA Sheet 包含 21 列，比区域 Sheet 多 7 列：
      System_Load, Reg_Service_Price, Reg_Capacity_Price,
      Min_5min_RSP, Max_5min_RSP, Min_5min_RCP, Max_5min_RCP

    Returns:
        pd.DataFrame: 合并后的系统级数据，行数 = 8760 + 8784 + 8760 = 26304
    """
    dfs = []
    for fname in FILES:
        fpath = os.path.join(DATA_DIR, fname)
        year = int(fname[:4])
        print(f"[加载] {fname} -> Sheet: {SYSTEM_SHEET}")

        df = pd.read_excel(fpath, sheet_name=SYSTEM_SHEET)
        df["year"] = year  # 添加来源年份标记
        print(f"  形状: {df.shape}, 日期范围: {df['Date'].min()} ~ {df['Date'].max()}")
        dfs.append(df)

    # 纵向拼接
    combined = pd.concat(dfs, ignore_index=True)
    print(f"\n[合并完成] ISO NE CA 总行数: {len(combined)}")
    print(f"  列数: {combined.shape[1]}")
    print(f"  日期范围: {combined['Date'].min()} ~ {combined['Date'].max()}")
    print(f"  列名: {list(combined.columns)}")

    return combined


def load_region_data(region_name):
    """
    加载单个区域的三年数据并合并。

    区域 Sheet 包含 14 列（不含 System_Load 和调频市场价格）。

    Args:
        region_name: 区域名称，如 'ME', 'CT' 等

    Returns:
        pd.DataFrame: 合并后的区域数据
    """
    dfs = []
    for fname in FILES:
        fpath = os.path.join(DATA_DIR, fname)
        year = int(fname[:4])
        df = pd.read_excel(fpath, sheet_name=region_name)
        df["year"] = year
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)
    return combined


def load_all_regions():
    """
    加载全部 8 个区域的数据，返回字典。

    Returns:
        dict: {区域名: DataFrame}
    """
    region_data = {}
    for region in REGION_SHEETS:
        print(f"[加载] 区域: {region}")
        region_data[region] = load_region_data(region)
        print(f"  行数: {len(region_data[region])}")
    return region_data


def save_intermediate(df, filename):
    """保存中间结果到 processed 目录（pickle 格式，保留数据类型）"""
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    fpath = os.path.join(PROCESSED_DIR, filename)
    with open(fpath, "wb") as f:
        pickle.dump(df, f)
    print(f"[保存] {fpath} ({len(df)} 行)")


# ============================================================================
# 主流程：执行第一步数据加载
# ============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("第一步：数据加载与合并")
    print("=" * 70)

    # 1. 加载并合并 ISO NE CA 系统级数据
    system_df = load_system_data()

    # 2. 加载全部区域数据（备用）
    region_data = load_all_regions()

    # 3. 保存中间结果
    save_intermediate(system_df, "step1_system_data.pkl")
    save_intermediate(region_data, "step1_region_data.pkl")

    # 4. 验证数据完整性
    print("\n" + "=" * 70)
    print("数据完整性验证")
    print("=" * 70)

    # 验证行数
    expected_rows = 8760 + 8784 + 8760
    assert len(system_df) == expected_rows, \
        f"行数不匹配: 期望 {expected_rows}, 实际 {len(system_df)}"
    print(f"[OK] 系统数据行数验证: {len(system_df)} == {expected_rows}")

    # 验证每列非空
    null_cols = system_df.isnull().sum()
    null_cols = null_cols[null_cols > 0]
    if len(null_cols) == 0:
        print("[OK] 无缺失值")
    else:
        print(f"[WARNING] 存在缺失值: \n{null_cols}")

    # 验证日期范围连续
    for year in [2023, 2024, 2025]:
        year_data = system_df[system_df["year"] == year]
        date_min = year_data["Date"].min()
        date_max = year_data["Date"].max()
        print(f"  {year}年: {date_min.date()} ~ {date_max.date()}, {len(year_data)} 行")

    # 查看 Hr_End 类型差异（这是第二步要处理的）
    print("\n[信息] Hr_End 类型检查:")
    for year in [2023, 2024, 2025]:
        year_data = system_df[system_df["year"] == year]
        print(f"  {year}年: dtype={year_data['Hr_End'].dtype}, "
              f"示例值={year_data['Hr_End'].iloc[:3].tolist()}")

    print("\n[第一步完成] 数据已加载并保存到 processed/ 目录")
