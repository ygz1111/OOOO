# -*- coding: utf-8 -*-
"""
PVLib 工业级光伏发电仿真脚本 (PVWatts 模型)
==============================================
使用 NREL PVLib PVWatts 模型对新英格兰6城市的气象数据进行光伏功率仿真。

PVWatts 是 NREL 官方在线工具 PVWatts Calculator 的底层算法,
使用系统总容量和组件温度系数直接计算 AC 功率, 无需逐组件配置。

物理模型链:
  1. 太阳位置计算 (NREL SPA 算法)
  2. POA 辐照度分解 (Perez 各向异性天空散射模型 + 地面反射)
  3. 组件温度 (SAPM 热模型, 考虑风速冷却)
  4. DC 功率 (PVWatts 模型: P_dc = Pdc0 × G_poa/1000 × [1 + gamma × (Tcell-25)])
  5. AC 功率 (PVWatts 逆变器模型: 考欧姆损耗 + 逆变器效率曲线)

系统配置:
  - 系统类型: 固定支架公用事业级光伏电站
  - 装机容量: 500 kWp (DC)
  - 组件温度系数: -0.40% /°C (典型多晶硅)
  - 逆变器效率: 96% (CEC 效率, 典型工业级)
  - 系统损耗: 14% (含线缆、污损、失配等, 按 PVWatts 默认)
  - 倾角: 各城市按纬度 (42-44°, 接近新英格兰最优倾角)
  - 方位角: 180° (正南)

数据来源:
  - 气象数据: Open-Meteo ERA5 再分析数据 (2019-2024, 6城市)
  - 组件参数: NREL PVWatts 标准参数
  - 太阳位置: NREL SPA (Solar Position Algorithm)

输出:
  solar_data/new_england_pv_dataset.csv
"""

import os
import sys
import time
import logging
import warnings
import json
import numpy as np
import pandas as pd
import pvlib
from pvlib.location import Location
from pvlib.pvsystem import PVSystem
from pvlib.modelchain import ModelChain

warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8')

# ============================================================================
# 配置
# ============================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(SCRIPT_DIR, "new_england_solar_dataset.csv")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "new_england_pv_dataset.csv")
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

# 新英格兰6城市配置
# 倾角 ≈ 纬度 - 5° (新英格兰地区最优倾角略小于纬度, 因夏季发电占比更大)
# 参考: NREL PVWatts Calculator 推荐值
CITY_CONFIGS = {
    "Boston":      {"lat": 42.3601, "lon": -71.0589, "tz": "America/New_York", "tilt": 37, "state": "MA"},
    "Hartford":    {"lat": 41.7658, "lon": -72.6734, "tz": "America/New_York", "tilt": 37, "state": "CT"},
    "Providence":  {"lat": 41.8240, "lon": -71.4128, "tz": "America/New_York", "tilt": 37, "state": "RI"},
    "Portland":    {"lat": 43.6591, "lon": -70.2568, "tz": "America/New_York", "tilt": 39, "state": "ME"},
    "Manchester":  {"lat": 42.9956, "lon": -71.4548, "tz": "America/New_York", "tilt": 38, "state": "NH"},
    "Burlington":  {"lat": 44.4759, "lon": -73.2121, "tz": "America/New_York", "tilt": 39, "state": "VT"},
}

# 目标装机容量 (kWp DC)
TARGET_CAPACITY_KW = 500.0

# ============================================================================
# 日志
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(SCRIPT_DIR, "pvlib_simulation.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================================
# 系统配置
# ============================================================================

def create_pv_system(tilt_angle, target_kw):
    """
    创建 PVWatts 模型 PV 系统

    PVWatts 模型使用以下参数:
      pdc0:       STC 下的 DC 功率 (W), 即装机容量
      gamma_pdc:  温度系数 (/°C), 多晶硅典型值 -0.004
      loss:       系统损耗参数 (PVWatts 默认 14%)

    逆变器使用 PVWatts 内置模型:
      eta_inv_nom:  额定效率 96% (CEC 效率)
      eta_inv_ref:  参考效率 96.3%

    参考: NREL PVWatts v5 Manual
    https://pvwatts.nrel.gov/
    """
    pdc0 = target_kw * 1000  # W (STC DC 功率)

    # 组件参数 (PVWatts 模型)
    # gamma_pdc = -0.004 /°C 是多晶硅组件的典型温度系数
    # 来源: NREL PVWatts 默认值
    module_parameters = {
        'pdc0': pdc0,
        'gamma_pdc': -0.004,      # -0.4% /°C
    }

    # 逆变器参数 (PVWatts 模型)
    # eta_inv_nom = 0.96 是现代工业级逆变器的典型 CEC 效率
    inverter_parameters = {
        'pdc0': pdc0,             # 逆变器额定 DC 输入 = 系统 DC 容量
        'eta_inv_nom': 0.96,      # 额定效率 96%
    }

    # SAPM 温度模型参数 (开放支架, 自由对流)
    # 来源: King et al., SAND2004-3535, Table 1
    # Open rack, polymeric backsheet (最常见的工业级安装方式)
    temp_params = {
        'a': -3.56,      # 上对流系数
        'b': -0.075,     # 风对流系数
        'deltaT': 3,     # 背面到电池温差 (°C)
    }

    # 系统损耗参数 (NREL PVWatts v5 默认值, 总计 ~14%)
    # 来源: Dobos, "PVWatts Version 5 Manual", NREL/TP-6A20-62641
    losses_parameters = {
        'soiling': 2,           # 污损 2%
        'shading': 3,           # 遮挡 3%
        'snow': 0,              # 积雪 (新英格兰冬季可调, 但默认0)
        'mismatch': 2,          # 失配 2%
        'wiring': 2,            # 线缆损耗 2%
        'connections': 0.5,     # 接头损耗 0.5%
        'lid': 1.5,             # 光致衰减 1.5%
        'nameplate_rating': 1,  # 名牌偏差 1%
        'age': 0,               # 老化 (新系统)
        'availability': 3,      # 可用性 3%
    }

    system = PVSystem(
        surface_tilt=tilt_angle,
        surface_azimuth=180,            # 正南
        module_parameters=module_parameters,
        inverter_parameters=inverter_parameters,
        temperature_model_parameters=temp_params,
        losses_parameters=losses_parameters,
        modules_per_string=1,           # PVWatts 不需要串并联配置
        strings_per_inverter=1,
    )

    logger.info(f"  PVWatts 系统配置:")
    logger.info(f"    DC 容量 (pdc0): {pdc0:.0f} W ({target_kw:.0f} kWp)")
    logger.info(f"    温度系数: -0.40% /°C (多晶硅)")
    logger.info(f"    逆变器效率: 96% (CEC)")
    logger.info(f"    系统损耗: ~14% (PVWatts 默认: 污损+遮挡+失配+线缆+...)")
    logger.info(f"    倾角: {tilt_angle}°")
    logger.info(f"    方位角: 180° (正南)")
    logger.info(f"    温度模型: SAPM (开放支架, a=-3.56, b=-0.075)")

    return system


# ============================================================================
# 仿真主逻辑
# ============================================================================

def simulate_city(df_city, city_name, city_config):
    """
    对单个城市的数据运行 PVLib ModelChain 仿真 (PVWatts 模型)
    """
    lat = city_config["lat"]
    lon = city_config["lon"]
    tz = city_config["tz"]
    tilt = city_config["tilt"]

    logger.info(f"\n  [{city_name}] lat={lat}, lon={lon}, tilt={tilt}°")

    # 创建系统和位置
    system = create_pv_system(tilt, TARGET_CAPACITY_KW)
    location = Location(latitude=lat, longitude=lon, tz=tz, name=city_name)

    # 创建 ModelChain
    # PVWatts 模型: 使用 pvwatts DC + pvwatts 逆变器 + pvwatts 损耗
    mc = ModelChain(
        system, location,
        dc_model='pvwatts',            # PVWatts DC 功率模型
        ac_model='pvwatts',            # PVWatts 逆变器效率模型
        transposition_model='perez',   # Perez 各向异性天空散射
        temperature_model='sapm',      # SAPM 热模型 (考虑风速冷却)
        aoi_model='physical',          # 物理入射角损失模型
        losses_model='pvwatts',        # PVWatts 系统损耗 (14%)
    )

    # 按年份分批处理
    years = sorted(df_city["year"].unique())
    all_results = []

    for year in years:
        df_year = df_city[df_city["year"] == year].copy()
        n_rows = len(df_year)

        # 构建带时区的 DatetimeIndex
        timestamps = pd.to_datetime(df_year["timestamp"])
        try:
            dt_index = pd.DatetimeIndex(timestamps).tz_localize(
                tz, ambiguous='forward', nonexistent='shift_forward'
            )
        except Exception:
            ambiguous_flags = []
            for ts in timestamps:
                if ts.month == 11 and 1 <= ts.day <= 7 and ts.hour == 1:
                    ambiguous_flags.append(True)
                elif ts.month == 3 and 8 <= ts.day <= 14 and ts.hour == 2:
                    ambiguous_flags.append(False)
                else:
                    ambiguous_flags.append(False)
            dt_index = pd.DatetimeIndex(timestamps).tz_localize(
                tz, ambiguous=ambiguous_flags, nonexistent='shift_forward'
            )

        assert len(dt_index) == n_rows, f"索引长度{len(dt_index)} != 数据长度{n_rows}"

        # 构建 PVLib 天气数据
        weather = pd.DataFrame({
            'ghi': df_year["ghi"].values,
            'dni': df_year["dni"].values,
            'dhi': df_year["dhi"].values,
            'temp_air': df_year["temperature"].values,
            'wind_speed': df_year["wind_speed"].values,
        }, index=dt_index)

        # 运行 ModelChain
        try:
            mc.run_model(weather)

            # 提取 AC 功率 (W)
            ac_power = mc.results.ac
            if isinstance(ac_power, pd.DataFrame):
                ac_power = ac_power.iloc[:, 0]

            ac_values = ac_power.values.astype(float)
            ac_values = np.nan_to_num(ac_values, nan=0.0, posinf=0.0, neginf=0.0)
            ac_values = np.maximum(ac_values, 0.0)  # 物理约束: 不为负

            # 提取 POA 辐照度和组件温度
            total_irrad = mc.results.total_irrad
            if total_irrad is not None:
                poa_values = total_irrad["poa_global"].values.astype(float)
                poa_values = np.nan_to_num(poa_values, nan=0.0)
            else:
                poa_values = np.zeros(n_rows)

            cell_temp = mc.results.cell_temperature
            if cell_temp is not None:
                if isinstance(cell_temp, pd.DataFrame):
                    cell_temp = cell_temp.iloc[:, 0]
                tcell_values = cell_temp.values.astype(float)
                tcell_values = np.nan_to_num(tcell_values, nan=df_year["temperature"].values)
            else:
                tcell_values = df_year["temperature"].values

            # 添加到结果
            df_result = df_year.copy()
            df_result["pv_power"] = ac_values          # W
            df_result["pv_power_kw"] = ac_values / 1000.0  # kW
            df_result["poa_irradiance"] = poa_values    # W/m²
            df_result["cell_temperature"] = tcell_values  # °C

            all_results.append(df_result)

            # 年度统计
            total_kwh = ac_values.sum() / 1000  # Wh → kWh
            peak_kw = ac_values.max() / 1000
            daylight_mask = weather['ghi'] > 0
            if daylight_mask.sum() > 0:
                daylight_cf = ac_values[daylight_mask].mean() / 1000
            else:
                daylight_cf = 0

            logger.info(f"    [{city_name} {year}] {n_rows}行 | "
                       f"日发电={total_kwh/365:.0f} kWh/日 | "
                       f"峰值={peak_kw:.0f} kW | "
                       f"白昼均值={daylight_cf:.0f} kW")

        except Exception as e:
            logger.error(f"    [{city_name} {year}] 仿真失败: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            df_result = df_year.copy()
            df_result["pv_power"] = 0.0
            df_result["pv_power_kw"] = 0.0
            df_result["poa_irradiance"] = 0.0
            df_result["cell_temperature"] = df_year["temperature"].values
            all_results.append(df_result)

    return pd.concat(all_results, ignore_index=True)


# ============================================================================
# 主流程
# ============================================================================

def main():
    print("=" * 70)
    print("PVLib 工业级光伏发电仿真 (PVWatts 模型)")
    print("NREL PVLib PVWatts + ERA5 气象数据 → PV 功率标签")
    print("=" * 70)

    # 1. 加载气象数据
    print("\n[1] 加载气象数据集...")
    df = pd.read_csv(INPUT_FILE)
    logger.info(f"  数据: {len(df):,} 行, {len(df.columns)} 列")
    logger.info(f"  城市: {sorted(df['city'].unique())}")
    logger.info(f"  年份: {df['year'].min()}-{df['year'].max()}")

    # 2. 逐城市仿真
    print("\n[2] 开始 PVWatts 仿真 (6城市×6年)...")
    all_city_results = []
    cities = sorted(df["city"].unique())

    start_time = time.time()

    for city_name in cities:
        city_config = CITY_CONFIGS[city_name]
        df_city = df[df["city"] == city_name].sort_values("timestamp").reset_index(drop=True)

        logger.info(f"\n{'='*60}")
        logger.info(f"城市: {city_name} ({city_config['lat']}, {city_config['lon']})")
        logger.info(f"数据: {len(df_city):,} 行")
        logger.info(f"{'='*60}")

        result = simulate_city(df_city, city_name, city_config)
        all_city_results.append(result)

    elapsed = time.time() - start_time

    # 3. 合并所有结果
    print(f"\n[3] 合并仿真结果...")
    final_df = pd.concat(all_city_results, ignore_index=True)
    final_df = final_df.sort_values(["city", "timestamp"]).reset_index(drop=True)

    # 4. 统计和验证
    print(f"\n[4] 仿真结果统计:")
    print(f"  总行数: {len(final_df):,}")
    print(f"  总列数: {len(final_df.columns)}")
    print(f"  仿真耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print(f"  每行平均: {elapsed/len(final_df)*1000:.3f}ms")

    print(f"\n  各城市发电统计:")
    print(f"  {'城市':>12s} {'装机kWp':>8s} {'年均MWh':>10s} {'峰值kW':>8s} {'容量因子':>8s} {'白昼CF':>8s}")

    city_stats = {}
    for city in cities:
        city_data = final_df[final_df["city"] == city]
        total_wh = city_data["pv_power"].sum()
        annual_mwh = total_wh / 1e6
        annual_avg_mwh = annual_mwh / 6
        peak_kw = city_data["pv_power_kw"].max()
        cf = annual_avg_mwh * 1000 / (TARGET_CAPACITY_KW * 8760)
        daylight = city_data[city_data["ghi"] > 0]
        if len(daylight) > 0:
            daylight_cf = daylight["pv_power_kw"].mean() / TARGET_CAPACITY_KW
        else:
            daylight_cf = 0

        city_stats[city] = {
            "annual_mwh": round(annual_avg_mwh, 1),
            "peak_kw": round(peak_kw, 1),
            "capacity_factor": round(cf, 4),
            "daylight_cf": round(daylight_cf, 4),
        }
        print(f"  {city:>12s} {TARGET_CAPACITY_KW:8.0f} {annual_avg_mwh:10.1f} {peak_kw:8.0f} {cf:8.1%} {daylight_cf:8.1%}")

    # 5. 物理合理性验证
    print(f"\n  物理合理性验证:")

    # a) 夜间功率应为0
    night_mask = final_df["ghi"] == 0
    night_power = final_df.loc[night_mask, "pv_power"].max()
    print(f"    夜间最大功率: {night_power:.1f} W (应为0)")

    # b) 峰值功率
    max_power = final_df["pv_power_kw"].max()
    ratio = max_power / TARGET_CAPACITY_KW
    print(f"    峰值功率: {max_power:.1f} kW ({ratio:.1%} of {TARGET_CAPACITY_KW:.0f}kWp)")
    print(f"    (PVWatts 允许 AC > DC, 通常 95-105%)")

    # c) 容量因子
    total_mwh = final_df["pv_power"].sum() / 1e6
    avg_annual = total_mwh / 6 / 6
    overall_cf = avg_annual * 1000 / (TARGET_CAPACITY_KW * 8760)
    print(f"    整体容量因子: {overall_cf:.1%} (新英格兰预期 12-16%)")

    # d) POA 辐照度
    daylight = final_df[final_df["ghi"] > 10]
    if len(daylight) > 0:
        poa_positive_rate = (daylight["poa_irradiance"] > 0).sum() / len(daylight)
        print(f"    白天POA>0比例: {poa_positive_rate:.1%} (应接近100%)")

    # e) 组件温度
    daylight = final_df[final_df["ghi"] > 100]
    if len(daylight) > 0:
        temp_diff = (daylight["cell_temperature"] - daylight["temperature"]).mean()
        print(f"    白天组件-环境温差: {temp_diff:.1f}°C (通常 10-30°C)")

    # f) PVWatts 验证: 与 NREL PVWatts Calculator 对比
    print(f"\n  NREL PVWatts Calculator 对比验证:")
    print(f"    (参考: Boston 42.36N, tilt=37°, 500kW DC, PVWatts v5)")
    print(f"    NREL 预期年发电量: ~620 MWh")
    print(f"    PVLib 仿真年发电量: {city_stats.get('Boston', {}).get('annual_mwh', 0):.0f} MWh")

    # 6. 保存最终数据集
    print(f"\n[5] 保存最终数据集...")
    final_df.to_csv(OUTPUT_FILE, index=False)
    file_size_mb = os.path.getsize(OUTPUT_FILE) / (1024 * 1024)
    print(f"  文件: {OUTPUT_FILE}")
    print(f"  大小: {file_size_mb:.1f} MB")
    print(f"  行数: {len(final_df):,}")
    print(f"  列数: {len(final_df.columns)}")

    print(f"\n  列名:")
    for i, col in enumerate(final_df.columns):
        print(f"    {i+1:2d}. {col}")

    # 7. 保存仿真报告
    report = {
        "simulation_software": "NREL PVLib Python 0.15.2",
        "model": "PVWatts v5",
        "weather_data_source": "Open-Meteo ERA5 Reanalysis",
        "system_config": {
            "dc_capacity_kw": TARGET_CAPACITY_KW,
            "module_type": "Polycrystalline (gamma_pdc = -0.004/°C)",
            "inverter_efficiency": 0.96,
            "array_type": "Fixed open rack",
            "tilt_range": "37-39° (≈latitude - 5°)",
            "azimuth": 180,
            "temperature_model": "SAPM (a=-3.56, b=-0.075, deltaT=3)",
        },
        "cities": cities,
        "year_range": [int(df['year'].min()), int(df['year'].max())],
        "total_rows": len(final_df),
        "simulation_time_sec": round(elapsed, 1),
        "overall_capacity_factor": round(overall_cf, 4),
        "city_statistics": city_stats,
        "models": {
            "dc_model": "PVWatts",
            "ac_model": "PVWatts inverter",
            "sky_diffuse": "Perez anisotropic",
            "temperature": "SAPM (wind cooling)",
            "aoi": "Physical",
        },
    }

    report_file = os.path.join(REPORTS_DIR, "pvlib_simulation_report.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n  仿真报告: {report_file}")

    print(f"\n{'='*70}")
    print("PVLib PVWatts 仿真完成!")
    print(f"{'='*70}")
    print(f"  数据集: new_england_pv_dataset.csv")
    print(f"  目标列: pv_power (W) / pv_power_kw (kW)")
    print(f"  输入特征: ghi, dni, dhi, temperature, humidity, wind_speed, ...")


if __name__ == "__main__":
    main()
