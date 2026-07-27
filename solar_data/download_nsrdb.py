# -*- coding: utf-8 -*-
"""
新英格兰地区光伏发电预测数据下载脚本
====================================
使用 Open-Meteo Archive API 下载 2019-2024 年太阳辐射和气象数据。
覆盖 4 个代表城市，时间分辨率为 60 分钟。

NREL NSRDB API 在部分网络环境下 SSL 握手失败，
Open-Meteo 提供等效的 ERA5 再分析数据（太阳辐射来源相同）。

数据变量映射 (NSRDB -> Open-Meteo):
  GHI          -> shortwave_radiation       (W/m^2)
  DNI          -> direct_normal_irradiance  (W/m^2)
  DHI          -> diffuse_radiation         (W/m^2)
  Temperature  -> temperature_2m            (°C)
  Humidity     -> relative_humidity_2m      (%)
  Wind Speed   -> wind_speed_10m            (m/s)
  Wind Dir     -> wind_direction_10m        (°)
  Pressure     -> surface_pressure          (hPa)
  Cloud Type   -> cloud_cover + cloud_cover_low/mid/high  (%)
  Precip Water -> precipitation             (mm) [替代]

输出: solar_data/raw/{city}_{year}.csv
"""

import os
import sys
import time
import logging
import requests
import pandas as pd
from typing import List, Dict, Optional

# ============================================================================
# 配置
# ============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(SCRIPT_DIR, "raw")
os.makedirs(RAW_DIR, exist_ok=True)

API_URL = "https://archive-api.open-meteo.com/v1/archive"

# 4 个代表城市
CITIES = [
    {"name": "Boston",     "state": "MA", "lat": 42.3601, "lon": -71.0589},
    {"name": "Hartford",   "state": "CT", "lat": 41.7658, "lon": -72.6734},
    {"name": "Providence", "state": "RI", "lat": 41.8240, "lon": -71.4128},
    {"name": "Portland",   "state": "ME", "lat": 43.6591, "lon": -70.2568},
]

YEARS = list(range(2019, 2025))  # 2019-2024

# Open-Meteo 变量
HOURLY_VARS = [
    "shortwave_radiation",          # GHI (W/m^2)
    "direct_radiation",             # 直射水平面 (W/m^2)
    "diffuse_radiation",            # DHI (W/m^2)
    "direct_normal_irradiance",     # DNI (W/m^2)
    "temperature_2m",              # 温度 (°C)
    "relative_humidity_2m",        # 相对湿度 (%)
    "wind_speed_10m",              # 风速 (m/s)
    "wind_direction_10m",          # 风向 (°)
    "surface_pressure",            # 地面气压 (hPa)
    "cloud_cover",                 # 云量 (%) -> Cloud Type
    "cloud_cover_low",             # 低云量 (%)
    "cloud_cover_mid",             # 中云量 (%)
    "cloud_cover_high",            # 高云量 (%)
    "precipitation",               # 降水量 (mm) -> 替代 Precipitable Water
    "sunshine_duration",           # 日照时长 (s)
]

# ============================================================================
# 日志
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(SCRIPT_DIR, "download.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================================
# 下载函数
# ============================================================================

def download_year(
    lat: float,
    lon: float,
    year: int,
    city_name: str,
    timeout: int = 120,
    max_retries: int = 3,
) -> Optional[pd.DataFrame]:
    """
    下载单城市单年数据

    Args:
        lat: 纬度
        lon: 经度
        year: 年份
        city_name: 城市名 (用于日志)
        timeout: 请求超时
        max_retries: 最大重试

    Returns:
        DataFrame 或 None
    """
    # 日期范围
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(HOURLY_VARS),
        "timezone": "America/New_York",
    }

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"  [{city_name} {year}] 尝试 {attempt}/{max_retries}: "
                        f"lat={lat}, lon={lon}, {start_date} ~ {end_date}")

            resp = requests.get(API_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()

            # 提取小时数据
            hourly_data = data.get("hourly", {})
            if not hourly_data or "time" not in hourly_data:
                logger.error(f"  [{city_name} {year}] API 返回无 hourly 数据")
                logger.error(f"  Response: {str(data)[:300]}")
                return None

            # 构建 DataFrame
            df = pd.DataFrame(hourly_data)

            # 重命名列 (映射到标准名称)
            rename_map = {
                "time": "timestamp",
                "shortwave_radiation": "ghi",           # GHI (W/m^2)
                "direct_normal_irradiance": "dni",      # DNI (W/m^2)
                "diffuse_radiation": "dhi",             # DHI (W/m^2)
                "direct_radiation": "direct_horizontal", # 直射水平面
                "temperature_2m": "temperature",        # °C
                "relative_humidity_2m": "humidity",     # %
                "wind_speed_10m": "wind_speed",         # m/s
                "wind_direction_10m": "wind_direction", # °
                "surface_pressure": "pressure",         # hPa
                "cloud_cover": "cloud_type",            # % (NSRDB Cloud Type 近似)
                "cloud_cover_low": "cloud_low",         # %
                "cloud_cover_mid": "cloud_mid",         # %
                "cloud_cover_high": "cloud_high",       # %
                "precipitation": "precipitable_water",  # mm (近似替代)
                "sunshine_duration": "sunshine_duration", # s
            }
            df = df.rename(columns=rename_map)

            # 添加位置信息
            df["latitude"] = lat
            df["longitude"] = lon

            # 解析时间
            df["timestamp"] = pd.to_datetime(df["timestamp"])

            # 提取 Year, Month, Day, Hour
            df["year"] = df["timestamp"].dt.year
            df["month"] = df["timestamp"].dt.month
            df["day"] = df["timestamp"].dt.day
            df["hour"] = df["timestamp"].dt.hour

            logger.info(f"  [{city_name} {year}] 成功: {len(df)} 行, "
                        f"{df['timestamp'].min()} ~ {df['timestamp'].max()}")

            return df

        except requests.exceptions.Timeout:
            logger.warning(f"  [{city_name} {year}] 请求超时 ({timeout}s)")
            if attempt < max_retries:
                time.sleep(10 * attempt)
        except requests.exceptions.HTTPError as e:
            logger.error(f"  [{city_name} {year}] HTTP错误: {e}")
            logger.error(f"  Response: {resp.text[:300]}")
            return None
        except Exception as e:
            logger.error(f"  [{city_name} {year}] 错误: {type(e).__name__}: {e}")
            if attempt < max_retries:
                time.sleep(5 * attempt)

    logger.error(f"  [{city_name} {year}] {max_retries}次重试均失败")
    return None


def download_all() -> Dict[str, List[str]]:
    """下载所有城市所有年份"""
    results = {}
    total = len(CITIES) * len(YEARS)
    done = 0
    success = 0

    for city in CITIES:
        city_name = city["name"]
        results[city_name] = []

        logger.info(f"\n{'='*60}")
        logger.info(f"城市: {city_name}, {city['state']} "
                    f"({city['lat']}, {city['lon']})")
        logger.info(f"{'='*60}")

        for year in YEARS:
            done += 1
            output_file = os.path.join(RAW_DIR, f"{city_name}_{year}.csv")

            # 跳过已存在文件
            if os.path.exists(output_file) and os.path.getsize(output_file) > 1000:
                logger.info(f"  [{done}/{total}] {city_name} {year} 已存在, 跳过")
                results[city_name].append(output_file)
                success += 1
                continue

            logger.info(f"  [{done}/{total}] 下载 {city_name} {year}...")

            df = download_year(
                lat=city["lat"],
                lon=city["lon"],
                year=year,
                city_name=city_name,
            )

            if df is not None and len(df) > 0:
                df.to_csv(output_file, index=False)
                size_kb = os.path.getsize(output_file) / 1024
                logger.info(f"  保存: {output_file} ({len(df)} 行, {size_kb:.0f}KB)")
                results[city_name].append(output_file)
                success += 1
            else:
                logger.warning(f"  {city_name} {year} 下载失败!")

            # API 限流保护
            time.sleep(1)

    logger.info(f"\n下载完成: {success}/{total} 成功")
    return results


def verify_downloads(results: Dict[str, List[str]]) -> None:
    """验证下载结果"""
    logger.info(f"\n{'='*60}")
    logger.info("下载结果验证")
    logger.info(f"{'='*60}")

    total_files = 0
    total_rows = 0

    for city, files in results.items():
        city_rows = 0
        logger.info(f"\n  {city}:")
        for f in files:
            if os.path.exists(f):
                df = pd.read_csv(f)
                size_kb = os.path.getsize(f) / 1024
                logger.info(f"    {os.path.basename(f)}: {len(df)} 行, "
                           f"{len(df.columns)} 列, {size_kb:.0f}KB")
                total_files += 1
                total_rows += len(df)
                city_rows += len(df)
            else:
                logger.warning(f"    {os.path.basename(f)}: 文件不存在!")
        logger.info(f"    小计: {city_rows:,} 行")

    logger.info(f"\n  总计: {total_files} 个文件, {total_rows:,} 行")
    logger.info(f"  预期: {len(CITIES)*len(YEARS)} 个文件, "
               f"~{len(CITIES)*len(YEARS)*8760:,} 行")


# ============================================================================
# 主流程
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("新英格兰地区光伏发电预测数据下载")
    print("数据源: Open-Meteo Archive API (ERA5)")
    print("=" * 60)
    print(f"  城市: {[c['name'] for c in CITIES]}")
    print(f"  年份: {YEARS[0]}-{YEARS[-1]} ({len(YEARS)}年)")
    print(f"  变量: {len(HOURLY_VARS)} 个 (GHI/DNI/DHI + 气象)")
    print(f"  输出: {RAW_DIR}")
    print()

    results = download_all()
    verify_downloads(results)

    print(f"\n[完成] 数据下载结束")
    print(f"  下一步: 运行 python solar_data/process_data.py")
