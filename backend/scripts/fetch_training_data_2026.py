#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉取 2026 年训练追加数据（负荷 + 气象，逐小时精确对齐）。

数据源:
  1. 负荷: ISO-NE Web Services /hourlysysload/day/{YYYYMMDD}
     - NEPOOL 全系统小时负荷（Load, MW），Basic Auth（凭据在项目根 .env）
     - BeginDate 为 ISO-8601 带东部偏移(-05:00/-04:00) → 转东部墙钟 naive 整点
  2. 气象: Open-Meteo Archive（6 站点等权平均，与系统部署口径一致）
     - temperature_2m / dewpoint_2m（摄氏），America/New_York 墙钟整点
     - Archive 有约 5-7 天发布延迟：末尾不足天数用 Forecast 接口 past_days 补

对齐口径（关键，与训练/预测一致）:
  - 时间戳 = America/New_York 墙钟 naive 整点（负荷与气象同一时间轴）
  - DST 春季跳变日 (2026-03-08) 只有 23 个小时，原样保留不补齐

用法:
  python fetch_training_data_2026.py [--start 20260101] [--end 20260902]
  python fetch_training_data_2026.py --check-db          # 追加 DB 交叉校验
输出: processed/2026_training_append/{load,weather,merged}_2026.csv + report.txt
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ISO_NE_BASE = "https://webservices.iso-ne.com/api/v1.1"
OM_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OM_FORECAST = "https://api.open-meteo.com/v1/forecast"

# 与 backend/config/locations.yaml 的活动站点一致（6 站点等权平均）
STATIONS = [
    ("Boston", 42.3601, -71.0589),
    ("Manchester", 42.9956, -71.4548),
    ("Hartford", 41.7637, -72.6851),
    ("Portland", 43.6615, -70.2553),
    ("Providence", 41.8240, -71.4128),
    ("Burlington", 44.4759, -73.2121),
]

EAST = ZoneInfo("America/New_York")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # backend/scripts -> 根
OUT_DIR = os.path.join(PROJECT_ROOT, "processed", "2026_training_append")


def load_env(path: str) -> dict:
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def iso_ne_load_for_day(day: date, username: str, password: str, retries: int = 3):
    """拉取一天 ISO-NE 小时负荷 → [(naive eastern datetime, load_mw), ...]"""
    url = f"{ISO_NE_BASE}/hourlysysload/day/{day.strftime('%Y%m%d')}"
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, auth=(username, password), timeout=30)
            if resp.status_code == 200:
                root = ET_from(resp.text)
                rows = []
                for elem in root.iter():
                    if local_tag(elem.tag) != "HourlySystemLoad":
                        continue
                    begin = None
                    load = None
                    for child in elem:
                        t = local_tag(child.tag)
                        if t == "BeginDate":
                            begin = datetime.fromisoformat(child.text.strip())
                        elif t == "Load":
                            load = float(child.text.strip())
                    if begin is not None and load is not None:
                        # 偏移已是东部(-05/-04) → 转墙钟 naive
                        begin_naive = begin.astimezone(EAST).replace(tzinfo=None)
                        rows.append((begin_naive, load))
                return rows
            if resp.status_code in (401, 403):
                print(f"    ⚠️ {day} HTTP {resp.status_code}: 认证/权限失败，跳过")
                return None
            print(f"    ⚠️ {day} HTTP {resp.status_code} (第{attempt}次)")
        except requests.RequestException as exc:
            print(f"    ⚠️ {day} 请求异常 {type(exc).__name__} (第{attempt}次): {exc}")
        time.sleep(2 * attempt)
    return None


def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def ET_from(text: str):
    import xml.etree.ElementTree as ET
    return ET.fromstring(text)


def om_fetch(lat: float, lon: float, start: date, end: date,
             use_forecast_past: bool = False):
    """拉一个站点区间小时温度/露点 → DataFrame(timestamp naive ET, temperature_2m, dewpoint_2m)"""
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,dewpoint_2m",
        "timezone": "America/New_York",
    }
    if use_forecast_past:
        # Forecast 接口补近几天：past_days 覆盖到补段起点，forecast_days=0 只取过去，
        # 响应再裁剪到 [start, end]，避免返回未来日期
        past_days = (date.today() - start).days + 2
        params.update({"past_days": min(past_days, 92), "forecast_days": 0})
        resp = requests.get(OM_FORECAST, params=params, timeout=30)
    else:
        params.update({
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
        })
        resp = requests.get(OM_ARCHIVE, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    h = data.get("hourly", {})
    if not h:
        return pd.DataFrame(columns=["timestamp", "temperature_2m", "dewpoint_2m"])
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(h["time"]),
        "temperature_2m": h.get("temperature_2m"),
        "dewpoint_2m": h.get("dewpoint_2m"),
    })
    if use_forecast_past:
        # 裁剪到请求范围（forecast 返回可能含未来/多余小时）
        lo, hi = pd.Timestamp(start), pd.Timestamp(end + timedelta(days=1))
        df = df[(df["timestamp"] >= lo) & (df["timestamp"] < hi)]
    return df


def fetch_weather(start: date, end: date) -> pd.DataFrame:
    """6 站点等权平均 → 每小时温度/露点（摄氏）

    Archive(ERA5) 发布延迟约 5-6 天：start..today-6 走 archive，
    末尾不足 6 天的部分走 Forecast past_days 补齐。
    """
    archive_end = min(end, date.today() - timedelta(days=6))
    parts = []
    for name, lat, lon in STATIONS:
        frames = []
        if archive_end >= start:
            frames.append(om_fetch(lat, lon, start, archive_end))
        if end > archive_end:
            past_start = max(start, archive_end + timedelta(days=1))
            frames.append(om_fetch(lat, lon, past_start, end, use_forecast_past=True))
        st_df = pd.concat(frames, ignore_index=True)
        st_df["station"] = name
        parts.append(st_df)
        print(f"  📡 {name}: {len(st_df)} 行")
        time.sleep(1.0)  # Open-Meteo 限速礼貌间隔
    all_df = pd.concat(parts, ignore_index=True)
    avg = (all_df.groupby("timestamp")[["temperature_2m", "dewpoint_2m"]]
                 .mean().reset_index())
    return avg.sort_values("timestamp").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description="拉取 2026 训练追加数据（负荷+气象）")
    ap.add_argument("--start", default="20260101", help="开始日期 YYYYMMDD")
    ap.add_argument("--end", default=None, help="结束日期 YYYYMMDD（默认昨天）")
    ap.add_argument("--check-db", action="store_true", help="追加与数据库已有实际负荷的交叉校验")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y%m%d").date()
    end = (datetime.strptime(args.end, "%Y%m%d").date() if args.end
           else date.today() - timedelta(days=1))

    env = load_env(os.path.join(PROJECT_ROOT, ".env"))
    username = env.get("ISO_NE_USERNAME", "").strip()
    password = env.get("ISO_NE_PASSWORD", "").strip()
    if not username or not password:
        print("❌ .env 缺少 ISO_NE_USERNAME / ISO_NE_PASSWORD"); sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"范围: {start} ~ {end}（共 {(end - start).days + 1} 天）")

    # ── 1. 负荷 ──
    print("\n[1/3] 拉取 ISO-NE 小时负荷 ...")
    load_rows, fail_days = [], []
    day = start
    while day <= end:
        rows = iso_ne_load_for_day(day, username, password)
        if rows is None:
            fail_days.append(day)
        else:
            load_rows.extend(rows)
            if (day - start).days % 30 == 0:
                print(f"  已完成 {day}（累计 {len(load_rows)} 条）")
        time.sleep(0.6)
        day += timedelta(days=1)
    load_df = pd.DataFrame(load_rows, columns=["timestamp", "system_load_mw"])
    load_df = (load_df.drop_duplicates(subset="timestamp", keep="first")
                      .sort_values("timestamp").reset_index(drop=True))
    print(f"负荷合计: {len(load_df)} 条 | 失败日期: {len(fail_days)} 天 "
          f"{[d.isoformat() for d in fail_days[:10]]}")

    # ── 2. 气象 ──
    print("\n[2/3] 拉取 Open-Meteo 6 站点区域平均 ...")
    weather_df = fetch_weather(start, end)
    print(f"气象合计: {len(weather_df)} 行")

    # ── 3. 合并对齐 ──
    print("\n[3/3] 合并与校验 ...")
    merged = pd.merge(load_df, weather_df, on="timestamp", how="outer",
                      indicator=True)
    both = merged[merged["_merge"] == "both"]
    only_load = merged[merged["_merge"] == "left_only"]
    only_weather = merged[merged["_merge"] == "right_only"]
    print(f"负荷∩气象(对齐成功): {len(both)} | 仅负荷: {len(only_load)} | 仅气象: {len(only_weather)}")

    missing = both[both["temperature_2m"].isna() | both["system_load_mw"].isna()
                   | both["dewpoint_2m"].isna()]
    print(f"对齐成功但有空值: {len(missing)} 行")
    if len(only_load):
        print("  仅负荷（气象缺）示例:", only_load["timestamp"].head(5).tolist())
    if len(only_weather):
        print("  仅气象（负荷缺）示例:", only_weather["timestamp"].head(5).tolist())

    # ── 4. DB 交叉校验 ──
    if args.check_db:
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=env["MYSQL_HOST"], port=int(env.get("MYSQL_PORT", 3306)),
                user=env["MYSQL_USER"], password=env["MYSQL_PASSWORD"],
                database=env["MYSQL_DATABASE"])
            cur = conn.cursor()
            cur.execute("""
                SELECT DATE(timestamp), AVG(actual_load_mw), COUNT(*)
                FROM actual_load_data WHERE region='NewEngland'
                  AND timestamp >= %s GROUP BY 1 ORDER BY 1
            """, (start.strftime("%Y-%m-%d"),))
            db_daily = cur.fetchall()
            cur.close(); conn.close()
            if db_daily:
                df_db = pd.DataFrame(db_daily, columns=["day", "db_avg", "db_n"])
                df_db["db_avg"] = df_db["db_avg"].astype(float)  # Decimal → float
                df_new = load_df.copy()
                df_new["day"] = df_new["timestamp"].dt.date
                new_daily = df_new.groupby("day")["system_load_mw"].mean().reset_index()
                cmp = pd.merge(new_daily, df_db, on="day", how="inner")
                cmp["diff_pct"] = (cmp["system_load_mw"] - cmp["db_avg"]) / cmp["db_avg"] * 100
                print("\nDB 交叉校验（同日均值差异%）:")
                print(cmp.to_string(index=False))
                print(f"  平均差异: {cmp['diff_pct'].mean():.2f}% | "
                      f"最大差异: {cmp['diff_pct'].abs().max():.2f}%")
            else:
                print("\nDB 无重叠日期（跳过交叉校验）")
        except Exception as exc:
            print(f"\n⚠️ DB 交叉校验失败: {exc}")

    # ── 5. 落盘 ──
    both = both.drop(columns="_merge").sort_values("timestamp")
    both = both.rename(columns={"temperature_2m": "dry_bulb_c",
                                "dewpoint_2m": "dew_point_c"})
    load_df.to_csv(os.path.join(OUT_DIR, "load_2026_hourly.csv"),
                   index=False, date_format="%Y-%m-%dT%H:%M:%S")
    weather_df.to_csv(os.path.join(OUT_DIR, "weather_2026_hourly.csv"),
                      index=False, date_format="%Y-%m-%dT%H:%M:%S")
    both.to_csv(os.path.join(OUT_DIR, "merged_2026_append.csv"),
                index=False, date_format="%Y-%m-%dT%H:%M:%S")

    with open(os.path.join(OUT_DIR, "report.txt"), "w", encoding="utf-8") as f:
        f.write(f"范围: {start} ~ {end}\n")
        f.write(f"负荷: {len(load_df)} 条 | 失败日期: {len(fail_days)} 天\n")
        f.write(f"气象: {len(weather_df)} 行\n")
        f.write(f"对齐: 成功 {len(both)} | 仅负荷 {len(only_load)} | 仅气象 {len(only_weather)}\n")
        f.write(f"空值: {len(missing)} 行\n")
        if fail_days:
            f.write(f"失败日期列表: {[d.isoformat() for d in fail_days]}\n")
    print(f"\n✅ 输出目录: {OUT_DIR}")
    print(f"  load_2026_hourly.csv    ({len(load_df)} 行)")
    print(f"  weather_2026_hourly.csv ({len(weather_df)} 行)")
    print(f"  merged_2026_append.csv  ({len(both)} 行)")
    if fail_days:
        print("⚠️ 存在失败日期，需补拉；不要直接用于训练")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
