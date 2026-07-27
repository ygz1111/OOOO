# -*- coding: utf-8 -*-
"""
下载广州光伏数据 (2019-2024)
使用 Open-Meteo Archive API
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

# 广州
GUANGZHOU = {"name": "Guangzhou", "state": "GD", "lat": 23.1291, "lon": 113.2644}

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
        "timezone": "Asia/Shanghai",
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
    print("广州光伏数据下载 (2019-2024)")
    print(f"  坐标: ({GUANGZHOU['lat']}, {GUANGZHOU['lon']})")
    print(f"  时区: Asia/Shanghai")
    print("=" * 60)

    for year in YEARS:
        output_file = os.path.join(RAW_DIR, f"{GUANGZHOU['name']}_{year}.csv")

        if os.path.exists(output_file) and os.path.getsize(output_file) > 1000:
            logger.info(f"  {GUANGZHOU['name']} {year} 已存在, 跳过")
            continue

        logger.info(f"  下载 {GUANGZHOU['name']} {year}...")
        df = download_year(GUANGZHOU["lat"], GUANGZHOU["lon"], year, GUANGZHOU["name"])

        if df is not None and len(df) > 0:
            df.to_csv(output_file, index=False)
            size_kb = os.path.getsize(output_file) / 1024
            logger.info(f"  保存: {output_file} ({len(df)} 行, {size_kb:.0f}KB)")
        else:
            logger.warning(f"  {GUANGZHOU['name']} {year} 下载失败!")

        time.sleep(1)

    # 验证
    print(f"\n{'='*60}")
    print("下载结果:")
    gz_files = [f for f in os.listdir(RAW_DIR) if f.startswith("Guangzhou")]
    total_rows = 0
    for f in sorted(gz_files):
        fpath = os.path.join(RAW_DIR, f)
        df = pd.read_csv(fpath)
        size_kb = os.path.getsize(fpath) / 1024
        print(f"  {f}: {len(df)} 行, {size_kb:.0f}KB")
        total_rows += len(df)
    print(f"  总计: {len(gz_files)} 个文件, {total_rows:,} 行")

    # 对比新英格兰 vs 广州
    print(f"\n{'='*60}")
    print("新英格兰 vs 广州 GHI 对比:")
    ne_df = pd.read_csv(os.path.join(SCRIPT_DIR, "new_england_solar_dataset.csv"))
    ne_ghi = ne_df["ghi"].mean()
    print(f"  新英格兰 GHI 均值: {ne_ghi:.1f} W/m²")

    if gz_files:
        gz_dfs = [pd.read_csv(os.path.join(RAW_DIR, f)) for f in sorted(gz_files)]
        gz_all = pd.concat(gz_dfs, ignore_index=True)
        gz_ghi = gz_all["ghi"].mean()
        print(f"  广州 GHI 均值:     {gz_ghi:.1f} W/m²")
        print(f"  差异: 广州比新英格兰 {'高' if gz_ghi > ne_ghi else '低'} {abs(gz_ghi-ne_ghi):.1f} W/m² ({abs(gz_ghi-ne_ghi)/ne_ghi*100:.1f}%)")


if __name__ == "__main__":
    main()
