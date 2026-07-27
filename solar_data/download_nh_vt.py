# -*- coding: utf-8 -*-
"""
下载新罕布什尔(NH)和佛蒙特(VT)光伏数据 2019-2024
补全新英格兰6州数据集
"""
import os
import sys
import time
import logging
import requests
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(SCRIPT_DIR, "raw")
os.makedirs(RAW_DIR, exist_ok=True)

API_URL = "https://archive-api.open-meteo.com/v1/archive"

# 补充的2个城市 (NH + VT)
NEW_CITIES = [
    {"name": "Manchester", "state": "NH", "lat": 42.9956, "lon": -71.4548},   # 新罕布什尔最大城市
    {"name": "Burlington", "state": "VT", "lat": 44.4759, "lon": -73.2121},   # 佛蒙特最大城市
]

YEARS = list(range(2019, 2025))

HOURLY_VARS = [
    "shortwave_radiation", "direct_radiation", "diffuse_radiation",
    "direct_normal_irradiance", "temperature_2m", "relative_humidity_2m",
    "wind_speed_10m", "wind_direction_10m", "surface_pressure",
    "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "precipitation", "sunshine_duration",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)


def download_year(lat, lon, year, city_name):
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start_date, "end_date": end_date,
        "hourly": ",".join(HOURLY_VARS),
        "timezone": "America/New_York",
    }

    for attempt in range(1, 4):
        try:
            logger.info(f"  [{city_name} {year}] 尝试 {attempt}/3: {start_date} ~ {end_date}")
            resp = requests.get(API_URL, params=params, timeout=120)
            resp.raise_for_status()
            data = resp.json()

            hourly_data = data.get("hourly", {})
            if not hourly_data or "time" not in hourly_data:
                logger.error(f"  无 hourly 数据")
                return None

            df = pd.DataFrame(hourly_data)
            rename_map = {
                "time": "timestamp",
                "shortwave_radiation": "ghi",
                "direct_normal_irradiance": "dni",
                "diffuse_radiation": "dhi",
                "direct_radiation": "direct_horizontal",
                "temperature_2m": "temperature",
                "relative_humidity_2m": "humidity",
                "wind_speed_10m": "wind_speed",
                "wind_direction_10m": "wind_direction",
                "surface_pressure": "pressure",
                "cloud_cover": "cloud_type",
                "cloud_cover_low": "cloud_low",
                "cloud_cover_mid": "cloud_mid",
                "cloud_cover_high": "cloud_high",
                "precipitation": "precipitable_water",
                "sunshine_duration": "sunshine_duration",
            }
            df = df.rename(columns=rename_map)
            df["latitude"] = lat
            df["longitude"] = lon
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df["year"] = df["timestamp"].dt.year
            df["month"] = df["timestamp"].dt.month
            df["day"] = df["timestamp"].dt.day
            df["hour"] = df["timestamp"].dt.hour

            logger.info(f"  成功: {len(df)} 行, {df['timestamp'].min()} ~ {df['timestamp'].max()}")
            return df
        except Exception as e:
            logger.error(f"  错误: {type(e).__name__}: {e}")
            if attempt < 3:
                time.sleep(10 * attempt)
    return None


def main():
    print("=" * 60)
    print("补充下载 NH(Manchester) + VT(Burlington) 2019-2024")
    print("=" * 60)

    for city in NEW_CITIES:
        print(f"\n  {city['name']}, {city['state']} ({city['lat']}, {city['lon']})")
        for year in YEARS:
            output_file = os.path.join(RAW_DIR, f"{city['name']}_{year}.csv")

            if os.path.exists(output_file) and os.path.getsize(output_file) > 1000:
                logger.info(f"  {city['name']} {year} 已存在, 跳过")
                continue

            df = download_year(city["lat"], city["lon"], year, city["name"])
            if df is not None and len(df) > 0:
                df.to_csv(output_file, index=False)
                size_kb = os.path.getsize(output_file) / 1024
                logger.info(f"  保存: {output_file} ({len(df)} 行, {size_kb:.0f}KB)")
            else:
                logger.warning(f"  {city['name']} {year} 下载失败!")
            time.sleep(1)

    # 验证
    print(f"\n{'='*60}")
    print("新增数据验证:")
    for city in NEW_CITIES:
        files = sorted([f for f in os.listdir(RAW_DIR) if f.startswith(city["name"])])
        total = 0
        for f in files:
            df = pd.read_csv(os.path.join(RAW_DIR, f))
            total += len(df)
        print(f"  {city['name']} ({city['state']}): {len(files)} 文件, {total:,} 行")

    # 列出所有原始文件
    all_files = sorted([f for f in os.listdir(RAW_DIR) if f.endswith(".csv")])
    cities = sorted(set(f.split("_")[0] for f in all_files))
    print(f"\n  当前所有城市: {cities}")
    print(f"  总文件数: {len(all_files)}")


if __name__ == "__main__":
    main()
