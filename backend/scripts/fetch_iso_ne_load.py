#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉取新英格兰实际系统负荷（真实"实际值"，用于预测准确性闭环）

支持两个数据源（--source 选择）：

1. eia（推荐，key 即时免费发放）
   数据源：EIA Open Data API v2（美国能源信息署）
   端点：/v2/electricity/rto/region-data/data/（respondent=NEWE 新英格兰）
   key 注册：https://www.eia.gov/opendata/register.php （填邮箱即时发放）
   环境变量：EIA_API_KEY

2. iso_ne（ISO Express 注册用户自动获得 Web Services 访问权限）
   数据源：ISO-NE Web Services API v1.1
   端点：GET /fiveminutesystemload/day/{YYYYMMDD}（5分钟真实系统负荷，
         按小时平均为整点实际负荷，东部时区与预测对齐）
   认证：HTTP Basic（用户名 = ISO Express 注册邮箱，密码 = ISO Express 密码）
   环境变量：ISO_NE_USERNAME（邮箱）+ ISO_NE_PASSWORD（密码）

行为：
  1. 拉取指定日期（默认昨天）每小时实际系统负荷
  2. 写入 actual_load_data 表（INSERT IGNORE 幂等，data_source 标记来源）
  3. 回填 load_predictions.actual_load_mw（与 target_timestamp 匹配）

用法：
  # EIA（推荐）
  export EIA_API_KEY=你的key
  cd backend && python scripts/fetch_iso_ne_load.py --source eia [YYYYMMDD]

  # ISO-NE（ISO Express 邮箱 + 密码）
  export ISO_NE_USERNAME=你的邮箱
  export ISO_NE_PASSWORD=你的密码
  cd backend && python scripts/fetch_iso_ne_load.py --source iso_ne [YYYYMMDD]
"""
import os
import sys
import argparse
import logging
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BACKEND_DIR, "..", ".env"))

sys.path.insert(0, BACKEND_DIR)
from realtime_api.crud import ActualLoadDataCRUD
from realtime_api.database import db_manager
from realtime_api.utils.iso_ne import fetch_hourly_actual_load

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("fetch_actual_load")

# ISO-NE
ISO_NE_BASE = "https://webservices.iso-ne.com/api/v1.1"
# EIA
EIA_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
EIA_REGISTER_URL = "https://www.eia.gov/opendata/register.php"


def fetch_eia(day: date, api_key: str) -> list:
    """EIA 新英格兰（NEWE）小时级实际需求 → [(datetime, MW), ...]"""
    start = day.strftime("%Y-%m-%d")
    end = (day + timedelta(days=1)).strftime("%Y-%m-%d")
    params = {
        "frequency": "hourly",
        "data[0]": "value",
        "facets[respondent][]": "NEWE",
        "facets[type][]": "D",  # Demand
        "start": start,
        "end": end,
        "api_key": api_key,
    }
    resp = requests.get(EIA_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("response", {}).get("data", [])

    rows = []
    for it in data:
        period = it.get("period")  # "2026-07-30T01"
        value = it.get("value")
        if period is None or value is None:
            continue
        ts = datetime.strptime(period, "%Y-%m-%dT%H")
        rows.append((ts, float(value)))
    return rows


async def persist(rows, data_source: str, region: str = "NewEngland"):
    """写入 actual_load_data + 回填 load_predictions.actual_load_mw"""
    await db_manager.initialize()
    inserted = 0
    for ts, mw in rows:
        try:
            rid = await ActualLoadDataCRUD.insert_actual_load(
                timestamp=ts, actual_load_mw=mw, region=region, data_source=data_source
            )
            if rid:
                inserted += 1
        except Exception as e:
            logger.warning(f"写入失败 {ts}: {e}")

    backfilled = 0
    for ts, mw in rows:
        try:
            await db_manager.execute_sql(
                """UPDATE load_predictions SET actual_load_mw = %s
                   WHERE target_timestamp = %s AND actual_load_mw IS NULL""",
                (mw, ts),
            )
            backfilled += 1
        except Exception as e:
            logger.warning(f"回填失败 {ts}: {e}")
    logger.info(f"写入 actual_load_data: {inserted} 条；回填语句执行 {backfilled} 条")
    return inserted


def main():
    parser = argparse.ArgumentParser(description="拉取新英格兰实际负荷")
    parser.add_argument("day", nargs="?", default=None, help="日期 YYYYMMDD（默认昨天）")
    parser.add_argument("--source", choices=["eia", "iso_ne"], default="eia",
                        help="数据源（默认 eia，key 即时免费）")
    args = parser.parse_args()

    if args.source == "eia":
        api_key = os.getenv("EIA_API_KEY", "").strip()
        if not api_key:
            print(f"\n❌ 未配置 EIA_API_KEY。\n"
                  f"   注册地址: {EIA_REGISTER_URL}\n"
                  f"   然后在 .env 中设置 EIA_API_KEY=你的key\n")
            sys.exit(1)
        fetch = lambda d: fetch_eia(d, api_key)
        data_source = "eia"
    else:  # iso_ne：ISO Express 邮箱 + 密码（注册用户自动获得 Web Services 权限）
        username = os.getenv("ISO_NE_USERNAME", "").strip()
        password = os.getenv("ISO_NE_PASSWORD", "").strip()
        if not username or not password:
            print("\n❌ 未配置 ISO_NE_USERNAME / ISO_NE_PASSWORD。\n"
                  "   ISO-NE 官网：拥有 ISO Express 账户的用户自动获得 Web Services 访问权限\n"
                  "   请在 .env 中设置：\n"
                  "     ISO_NE_USERNAME=你的ISOExpress注册邮箱\n"
                  "     ISO_NE_PASSWORD=你的ISOExpress密码\n")
            sys.exit(1)
        fetch = lambda d: fetch_hourly_actual_load(d, username, password)
        data_source = "iso_ne"

    day = datetime.strptime(args.day, "%Y%m%d").date() if args.day \
        else date.today() - timedelta(days=1)

    logger.info(f"[{args.source}] 拉取 {day} 的实际负荷...")
    rows = fetch(day)
    logger.info(f"获取到 {len(rows)} 条小时数据（示例: {rows[0] if rows else '无'}）")

    import asyncio
    inserted = asyncio.run(persist(rows, data_source))
    logger.info(f"完成：写入 {inserted} 条（其余为已存在跳过）")


if __name__ == "__main__":
    main()
