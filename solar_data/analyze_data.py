# -*- coding: utf-8 -*-
"""
数据分析脚本
============
对清洗后的光伏数据集进行统计分析、相关性分析、特征重要性分析。

输出:
  reports/statistical_report.txt       - 数据统计报告
  reports/correlation_matrix.csv       - 相关性矩阵
  reports/feature_importance.csv       - 特征重要性
  figures/                             - 可视化图表
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats as scipy_stats
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler

# ============================================================================
# 配置
# ============================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FIGURES_DIR = os.path.join(SCRIPT_DIR, "figures")
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")
os.makedirs(FIGURES_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# 图表样式
plt.rcParams.update({
    "figure.figsize": (12, 6),
    "figure.dpi": 150,
    "font.size": 11,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "axes.spines.top": False,
    "axes.spines.right": False,
})
sns.set_palette("husl")

# 数据文件
DATA_FILE = os.path.join(SCRIPT_DIR, "new_england_solar_dataset.csv")

# 分析用的数值特征
FEATURE_COLS = [
    "temperature", "humidity", "wind_speed", "wind_direction",
    "pressure", "cloud_type", "cloud_low", "cloud_mid", "cloud_high",
    "precipitable_water", "dni", "dhi", "direct_horizontal",
    "hour", "month",
]
TARGET_COL = "ghi"  # 以 GHI 为目标变量

# ============================================================================
# 日志
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ============================================================================
# 1. 数据统计报告
# ============================================================================

def generate_statistical_report(df: pd.DataFrame) -> str:
    """生成完整的统计报告"""
    lines = []
    lines.append("=" * 70)
    lines.append("新英格兰地区光伏发电数据集 - 统计报告")
    lines.append("=" * 70)
    lines.append("")

    # 基本信息
    lines.append("1. 数据集基本信息")
    lines.append("-" * 40)
    lines.append(f"  总行数: {len(df):,}")
    lines.append(f"  总列数: {len(df.columns)}")
    lines.append(f"  城市数: {df['city'].nunique()}")
    lines.append(f"  城市列表: {', '.join(sorted(df['city'].unique()))}")
    lines.append(f"  年份范围: {df['year'].min()} - {df['year'].max()}")
    lines.append(f"  时间范围: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
    lines.append(f"  时间分辨率: 1小时")
    lines.append("")

    # 各城市数据量
    lines.append("2. 各城市数据量")
    lines.append("-" * 40)
    city_stats = df.groupby("city").agg(
        rows=("ghi", "count"),
        ghi_mean=("ghi", "mean"),
        ghi_max=("ghi", "max"),
        temp_mean=("temperature", "mean"),
    ).round(2)
    for city, row in city_stats.iterrows():
        lines.append(f"  {city:12s}: {int(row['rows']):>6,} 行, "
                     f"GHI均值={row['ghi_mean']:.1f} W/m^2, "
                     f"GHI峰值={row['ghi_max']:.0f} W/m^2, "
                     f"温度均值={row['temp_mean']:.1f}°C")
    lines.append("")

    # 各年份数据量
    lines.append("3. 各年份数据量")
    lines.append("-" * 40)
    for year, count in df.groupby("year").size().items():
        lines.append(f"  {year}: {count:,} 行")
    lines.append("")

    # 数值变量统计
    lines.append("4. 数值变量描述统计")
    lines.append("-" * 40)
    numeric_cols = ["ghi", "dni", "dhi", "temperature", "humidity",
                    "wind_speed", "wind_direction", "pressure",
                    "cloud_type", "precipitable_water"]
    desc = df[numeric_cols].describe().round(2)
    lines.append(desc.to_string())
    lines.append("")

    # 缺失值检查
    lines.append("5. 缺失值检查")
    lines.append("-" * 40)
    missing = df.isnull().sum()
    missing = missing[missing > 0]
    if len(missing) > 0:
        for col, cnt in missing.items():
            lines.append(f"  {col}: {cnt} ({cnt/len(df)*100:.2f}%)")
    else:
        lines.append("  无缺失值 OK")
    lines.append("")

    # GHI 统计 (按月)
    lines.append("6. GHI 月度统计 (W/m^2)")
    lines.append("-" * 40)
    monthly_ghi = df.groupby("month")["ghi"].agg(["mean", "max", "std"]).round(1)
    for month, row in monthly_ghi.iterrows():
        lines.append(f"  {month:2d}月: 均值={row['mean']:6.1f}, "
                     f"峰值={row['max']:6.0f}, 标准差={row['std']:6.1f}")
    lines.append("")

    # GHI 统计 (按小时)
    lines.append("7. GHI 小时统计 (W/m^2)")
    lines.append("-" * 40)
    hourly_ghi = df.groupby("hour")["ghi"].agg(["mean", "max"]).round(1)
    for hour, row in hourly_ghi.iterrows():
        bar = "#" * int(row["mean"] / 20)
        lines.append(f"  {hour:02d}:00: 均值={row['mean']:6.1f}, "
                     f"峰值={row['max']:6.0f} {bar}")
    lines.append("")

    report_text = "\n".join(lines)

    # 保存报告
    report_file = os.path.join(REPORTS_DIR, "statistical_report.txt")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_text)
    logger.info(f"统计报告已保存: {report_file}")

    return report_text


# ============================================================================
# 2. 相关性分析
# ============================================================================

def correlation_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """相关性分析和可视化"""
    logger.info("进行相关性分析...")

    # 选择数值列
    corr_cols = [c for c in FEATURE_COLS + [TARGET_COL] if c in df.columns]
    corr_data = df[corr_cols].dropna()

    # 计算相关系数矩阵
    corr_matrix = corr_data.corr(method="pearson")
    corr_matrix = corr_matrix.round(3)

    # 保存相关性矩阵
    corr_file = os.path.join(REPORTS_DIR, "correlation_matrix.csv")
    corr_matrix.to_csv(corr_file)
    logger.info(f"相关性矩阵已保存: {corr_file}")

    # 绘制热力图
    fig, ax = plt.subplots(figsize=(14, 11))
    mask = np.triu(np.ones_like(corr_matrix, dtype=bool), k=1)
    sns.heatmap(
        corr_matrix, mask=mask, annot=True, fmt=".2f",
        cmap="RdYlBu_r", center=0, vmin=-1, vmax=1,
        square=True, linewidths=0.5, ax=ax,
        annot_kws={"size": 8},
    )
    ax.set_title("Feature Correlation Matrix (Pearson)", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig_file = os.path.join(FIGURES_DIR, "correlation_heatmap.png")
    plt.savefig(fig_file, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"相关性热力图已保存: {fig_file}")

    # GHI 与各特征的相关性排名
    ghi_corr = corr_matrix[TARGET_COL].drop(TARGET_COL).sort_values(key=abs, ascending=False)
    logger.info(f"\nGHI 相关性排名:")
    for feat, val in ghi_corr.items():
        logger.info(f"  {feat:25s}: {val:+.3f}")

    return corr_matrix


# ============================================================================
# 3. 特征重要性分析
# ============================================================================

def feature_importance_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """使用随机森林分析特征重要性"""
    logger.info("进行特征重要性分析 (Random Forest)...")

    # 准备数据
    feature_cols = [c for c in FEATURE_COLS if c in df.columns]
    data = df[feature_cols + [TARGET_COL]].dropna()

    X = data[feature_cols].values
    y = data[TARGET_COL].values

    # 标准化
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # 训练随机森林
    rf = RandomForestRegressor(n_estimators=100, max_depth=15, random_state=42, n_jobs=-1)
    rf.fit(X_scaled, y)

    # 特征重要性
    importance = pd.DataFrame({
        "feature": feature_cols,
        "importance": rf.feature_importances_,
    }).sort_values("importance", ascending=False)

    importance["importance_pct"] = (importance["importance"] * 100).round(2)
    importance["cumulative_pct"] = importance["importance_pct"].cumsum().round(2)

    # 保存
    imp_file = os.path.join(REPORTS_DIR, "feature_importance.csv")
    importance.to_csv(imp_file, index=False)
    logger.info(f"特征重要性已保存: {imp_file}")

    logger.info(f"\n特征重要性排名:")
    for _, row in importance.iterrows():
        bar = "#" * int(row["importance_pct"] * 2)
        logger.info(f"  {row['feature']:25s}: {row['importance_pct']:6.2f}% {bar}")

    # 绘制特征重要性图
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = plt.cm.viridis(np.linspace(0.2, 0.8, len(importance)))
    bars = ax.barh(importance["feature"][::-1], importance["importance_pct"][::-1],
                   color=colors[::-1], edgecolor="white", height=0.7)
    ax.set_xlabel("Importance (%)", fontsize=12)
    ax.set_title("Feature Importance for GHI Prediction (Random Forest)",
                 fontsize=14, fontweight="bold")
    # 在柱子上标注数值
    for bar, val in zip(bars, importance["importance_pct"][::-1]):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height()/2,
                f"{val:.1f}%", va="center", fontsize=9)
    plt.tight_layout()
    fig_file = os.path.join(FIGURES_DIR, "feature_importance.png")
    plt.savefig(fig_file, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"特征重要性图已保存: {fig_file}")

    return importance


# ============================================================================
# 4. 可视化
# ============================================================================

def plot_weather_distributions(df: pd.DataFrame) -> None:
    """气象变量分布图"""
    logger.info("生成气象变量分布图...")

    cols = ["temperature", "humidity", "wind_speed", "pressure",
            "cloud_type", "precipitable_water"]
    cols = [c for c in cols if c in df.columns]

    n = len(cols)
    ncols = 3
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(15, 4 * nrows))
    axes = axes.flatten() if n > 1 else [axes]

    for i, col in enumerate(cols):
        ax = axes[i]
        data = df[col].dropna()
        ax.hist(data, bins=60, color=plt.cm.Set2(i), edgecolor="white", alpha=0.8)
        ax.axvline(data.mean(), color="red", linestyle="--", linewidth=1.5,
                   label=f"Mean={data.mean():.1f}")
        ax.axvline(data.median(), color="blue", linestyle=":", linewidth=1.5,
                   label=f"Median={data.median():.1f}")
        ax.set_title(col, fontsize=12, fontweight="bold")
        ax.set_ylabel("Frequency")
        ax.legend(fontsize=9)

    # 隐藏多余的子图
    for j in range(i + 1, len(axes)):
        axes[j].set_visible(False)

    plt.suptitle("Weather Variable Distributions", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    fig_file = os.path.join(FIGURES_DIR, "weather_distributions.png")
    plt.savefig(fig_file, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"  保存: {fig_file}")

    # 辐射变量分布 (单独一张图)
    rad_cols = ["ghi", "dni", "dhi"]
    rad_cols = [c for c in rad_cols if c in df.columns]
    if rad_cols:
        fig, axes = plt.subplots(1, len(rad_cols), figsize=(5 * len(rad_cols), 4))
        if len(rad_cols) == 1:
            axes = [axes]
        for i, col in enumerate(rad_cols):
            ax = axes[i]
            data = df[col].dropna()
            # 只画白天 (GHI > 0)
            if col == "ghi":
                data = data[data > 0]
            ax.hist(data, bins=80, color=plt.cm.YlOrRd(0.6), edgecolor="white", alpha=0.8)
            ax.axvline(data.mean(), color="red", linestyle="--", linewidth=1.5,
                       label=f"Mean={data.mean():.1f}")
            ax.set_title(f"{col.upper()} Distribution (Daytime)", fontsize=12, fontweight="bold")
            ax.set_xlabel("W/m^2")
            ax.set_ylabel("Frequency")
            ax.legend(fontsize=9)
        plt.tight_layout()
        fig_file = os.path.join(FIGURES_DIR, "radiation_distributions.png")
        plt.savefig(fig_file, dpi=150, bbox_inches="tight")
        plt.close()
        logger.info(f"  保存: {fig_file}")


def plot_ghi_curves(df: pd.DataFrame) -> None:
    """GHI 变化曲线"""
    logger.info("生成 GHI 变化曲线...")

    # 1. 日内 GHI 曲线 (按月份分组)
    fig, ax = plt.subplots(figsize=(12, 6))
    monthly_hourly = df.groupby(["month", "hour"])["ghi"].mean().unstack(level=0)
    colors_month = plt.cm.tab10(np.linspace(0, 1, 12))
    for month in range(1, 13):
        if month in monthly_hourly.columns:
            ax.plot(monthly_hourly.index, monthly_hourly[month],
                    label=f"{month}月", color=colors_month[month-1], linewidth=1.5)
    ax.set_xlabel("Hour of Day", fontsize=12)
    ax.set_ylabel("GHI (W/m^2)", fontsize=12)
    ax.set_title("Average GHI Diurnal Cycle by Month", fontsize=14, fontweight="bold")
    ax.legend(ncol=4, fontsize=9, loc="upper center")
    ax.set_xlim(-0.5, 23.5)
    ax.set_xticks(range(0, 24, 2))
    plt.tight_layout()
    fig_file = os.path.join(FIGURES_DIR, "ghi_diurnal_by_month.png")
    plt.savefig(fig_file, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"  保存: {fig_file}")

    # 2. 城市间 GHI 对比 (日内曲线)
    fig, ax = plt.subplots(figsize=(10, 6))
    city_hourly = df.groupby(["city", "hour"])["ghi"].mean().unstack(level=0)
    for city in city_hourly.columns:
        ax.plot(city_hourly.index, city_hourly[city], label=city, linewidth=2)
    ax.set_xlabel("Hour of Day", fontsize=12)
    ax.set_ylabel("GHI (W/m^2)", fontsize=12)
    ax.set_title("Average GHI Diurnal Cycle by City", fontsize=14, fontweight="bold")
    ax.legend(fontsize=10)
    ax.set_xlim(-0.5, 23.5)
    ax.set_xticks(range(0, 24, 2))
    plt.tight_layout()
    fig_file = os.path.join(FIGURES_DIR, "ghi_diurnal_by_city.png")
    plt.savefig(fig_file, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"  保存: {fig_file}")

    # 3. 典型日 GHI 曲线 (选取夏季和冬季各一天)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    for ax, (season, date_str) in zip(axes, [("Summer", "2023-07-15"), ("Winter", "2023-01-15")]):
        day_data = df[df["timestamp"].dt.strftime("%Y-%m-%d") == date_str]
        if len(day_data) == 0:
            # 找最近的有效日期
            target_date = pd.to_datetime(date_str)
            df_dates = df["timestamp"].dt.normalize()
            closest = (df_dates - target_date).abs().min()
            if pd.notna(closest):
                closest_date = target_date + (df_dates - target_date).iloc[(df_dates - target_date).abs().values.argmin()]
                day_data = df[df["timestamp"].dt.strftime("%Y-%m-%d") == closest_date.strftime("%Y-%m-%d")]
                date_str = closest_date.strftime("%Y-%m-%d")

        for city in day_data["city"].unique():
            city_data = day_data[day_data["city"] == city].sort_values("hour")
            ax.plot(city_data["hour"], city_data["ghi"], label=city, linewidth=2, marker="o", markersize=3)
        ax.set_title(f"{season} Typical Day ({date_str})", fontsize=13, fontweight="bold")
        ax.set_xlabel("Hour of Day")
        ax.set_ylabel("GHI (W/m^2)")
        ax.legend(fontsize=9)
        ax.set_xlim(-0.5, 23.5)
        ax.set_xticks(range(0, 24, 2))
    plt.tight_layout()
    fig_file = os.path.join(FIGURES_DIR, "ghi_typical_day.png")
    plt.savefig(fig_file, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"  保存: {fig_file}")


def plot_annual_trends(df: pd.DataFrame) -> None:
    """年度太阳辐射趋势"""
    logger.info("生成年度趋势图...")

    # 1. 月均 GHI 趋势 (所有年份)
    fig, ax = plt.subplots(figsize=(14, 6))
    monthly = df.groupby(["year", "month"])["ghi"].mean().reset_index()
    for year in sorted(monthly["year"].unique()):
        year_data = monthly[monthly["year"] == year]
        ax.plot(year_data["month"], year_data["ghi"],
                marker="o", linewidth=2, label=str(year))
    ax.set_xlabel("Month", fontsize=12)
    ax.set_ylabel("Average GHI (W/m^2)", fontsize=12)
    ax.set_title("Monthly Average GHI Trend by Year", fontsize=14, fontweight="bold")
    ax.legend(fontsize=10)
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels([f"{m}月" for m in range(1, 13)])
    plt.tight_layout()
    fig_file = os.path.join(FIGURES_DIR, "annual_ghi_trend.png")
    plt.savefig(fig_file, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"  保存: {fig_file}")

    # 2. 年度 GHI 总量对比
    fig, ax = plt.subplots(figsize=(10, 5))
    yearly_total = df.groupby("year")["ghi"].sum() / 1000  # kWh/m^2
    bars = ax.bar(yearly_total.index, yearly_total.values,
                  color=plt.cm.YlOrRd(np.linspace(0.3, 0.8, len(yearly_total))),
                  edgecolor="white", width=0.6)
    for bar, val in zip(bars, yearly_total.values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 20,
                f"{val:.0f}", ha="center", fontsize=11, fontweight="bold")
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Total GHI (kWh/m^2)", fontsize=12)
    ax.set_title("Annual Total GHI by Year", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig_file = os.path.join(FIGURES_DIR, "annual_ghi_total.png")
    plt.savefig(fig_file, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"  保存: {fig_file}")

    # 3. 城市年度 GHI 对比
    fig, ax = plt.subplots(figsize=(12, 6))
    city_yearly = df.groupby(["city", "year"])["ghi"].mean().unstack(level=0)
    city_yearly.plot(kind="bar", ax=ax, edgecolor="white", width=0.8)
    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Average GHI (W/m^2)", fontsize=12)
    ax.set_title("Average GHI by City and Year", fontsize=14, fontweight="bold")
    ax.legend(title="City", fontsize=10)
    plt.xticks(rotation=0)
    plt.tight_layout()
    fig_file = os.path.join(FIGURES_DIR, "city_yearly_ghi.png")
    plt.savefig(fig_file, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"  保存: {fig_file}")

    # 4. GHI/DNI/DHI 月度趋势对比
    fig, ax = plt.subplots(figsize=(12, 6))
    monthly_rad = df.groupby("month")[["ghi", "dni", "dhi"]].mean()
    monthly_rad.plot(ax=ax, linewidth=2, marker="o")
    ax.set_xlabel("Month", fontsize=12)
    ax.set_ylabel("Irradiance (W/m^2)", fontsize=12)
    ax.set_title("Monthly Average Solar Irradiance Components", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)
    ax.set_xticks(range(1, 13))
    plt.tight_layout()
    fig_file = os.path.join(FIGURES_DIR, "monthly_irradiance_components.png")
    plt.savefig(fig_file, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"  保存: {fig_file}")


def plot_seasonal_analysis(df: pd.DataFrame) -> None:
    """季节性分析图"""
    logger.info("生成季节性分析图...")

    # 定义季节
    def get_season(month):
        if month in [12, 1, 2]: return "Winter"
        elif month in [3, 4, 5]: return "Spring"
        elif month in [6, 7, 8]: return "Summer"
        else: return "Fall"

    df_season = df.copy()
    df_season["season"] = df_season["month"].apply(get_season)

    # 季节 x 小时 GHI 热力图
    fig, ax = plt.subplots(figsize=(14, 5))
    pivot = df_season.groupby(["season", "hour"])["ghi"].mean().unstack(level=0)
    pivot = pivot[["Winter", "Spring", "Summer", "Fall"]]  # 排序
    sns.heatmap(pivot.T, cmap="YlOrRd", annot=False, cbar_kws={"label": "GHI (W/m^2)"},
                ax=ax, linewidths=0.5)
    ax.set_title("Seasonal GHI Heatmap (Hour x Season)", fontsize=14, fontweight="bold")
    ax.set_xlabel("Hour of Day")
    ax.set_ylabel("Season")
    plt.tight_layout()
    fig_file = os.path.join(FIGURES_DIR, "seasonal_ghi_heatmap.png")
    plt.savefig(fig_file, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"  保存: {fig_file}")


# ============================================================================
# 主流程
# ============================================================================

def main():
    print("=" * 60)
    print("新英格兰光伏数据分析")
    print("=" * 60)

    # 加载数据
    print("\n[1] 加载数据集...")
    df = pd.read_csv(DATA_FILE, parse_dates=["timestamp"])
    print(f"  数据: {len(df):,} 行, {len(df.columns)} 列")
    print(f"  时间: {df['timestamp'].min()} ~ {df['timestamp'].max()}")

    # 统计报告
    print("\n[2] 生成统计报告...")
    report = generate_statistical_report(df)
    print(report[:500] + "...")

    # 相关性分析
    print("\n[3] 相关性分析...")
    corr = correlation_analysis(df)

    # 特征重要性
    print("\n[4] 特征重要性分析...")
    importance = feature_importance_analysis(df)

    # 可视化
    print("\n[5] 生成可视化图表...")
    plot_weather_distributions(df)
    plot_ghi_curves(df)
    plot_annual_trends(df)
    plot_seasonal_analysis(df)

    print(f"\n{'='*60}")
    print("分析完成!")
    print(f"{'='*60}")
    print(f"  报告目录: {REPORTS_DIR}")
    print(f"  图表目录: {FIGURES_DIR}")
    print(f"\n  生成的文件:")
    for d in [REPORTS_DIR, FIGURES_DIR]:
        for f in sorted(os.listdir(d)):
            fpath = os.path.join(d, f)
            size = os.path.getsize(fpath) / 1024
            print(f"    {f} ({size:.0f} KB)")


if __name__ == "__main__":
    main()
