#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉取新英格兰实际系统负荷（真实"实际值"，用于预测准确性闭环）

支持两个数据源（--source 选择）：

1. eia（仅作独立来源存档，不作为当前模型的准确率标签）
   数据源：EIA Open Data API v2（美国能源信息署）
   端点：/v2/electricity/rto/region-data/data/（respondent=NEWE 新英格兰）
   key 注册：https://www.eia.gov/opendata/register.php （填邮箱即时发放）
   环境变量：EIA_API_KEY

2. iso_ne（ISO Express 注册用户自动获得 Web Services 访问权限）
   数据源：ISO-NE Web Services API v1.1
   端点：GET /fiveminuteestimatedzonalload/day/{YYYYMMDD}
   八区小时均值求和，以小时结束标记，仅保存完整12次采样的小时。
   认证：HTTP Basic（用户名 = ISO Express 注册邮箱，密码 = ISO Express 密码）
   环境变量：ISO_NE_USERNAME（邮箱）+ ISO_NE_PASSWORD（密码）

行为：
  1. 拉取指定日期（默认昨天）每小时实际系统负荷
  2. 写入 actual_load_data 表（INSERT IGNORE 幂等，data_source 标记来源）
  3. 新口径另行存档，查询时对齐；不覆盖旧记录，不把 EIA 回填成当前模型标签

用法：
  # EIA（独立来源存档）
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
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BACKEND_DIR, "..", ".env"))

sys.path.insert(0, BACKEND_DIR)
from realtime_api.crud import ActualLoadDataCRUD
from realtime_api.database import db_manager
from realtime_api.utils.iso_ne import fetch_hourly_actual_load, persist_actual_load
from realtime_api.utils.iso_ne_intervals import ACTUAL_SOURCE

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
    # EIA hourly period 为 UTC 整点；统一转为东部墙钟 naive（与 ISO-NE 路径口径一致）
    east = ZoneInfo("America/New_York")
    for it in data:
        period = it.get("period")  # "2026-07-30T01" (UTC)
        value = it.get("value")
        if period is None or value is None:
            continue
        ts_utc = datetime.strptime(period, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
        ts = ts_utc.astimezone(east).replace(tzinfo=None)
        rows.append((ts, float(value)))
    return rows


async def persist(rows, data_source: str, region: str = "NewEngland"):
    """按口径隔离存储；其他来源不再回填当前模型的误差标签。"""
    if data_source == ACTUAL_SOURCE:
        result = await persist_actual_load(rows)
        return result["inserted"]
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

    logger.info(f"写入历史存档: {inserted} 条；未回填当前模型标签")
    return inserted


def main():
    parser = argparse.ArgumentParser(description="拉取新英格兰实际负荷")
    parser.add_argument("day", nargs="?", default=None, help="日期 YYYYMMDD（默认昨天）")
    parser.add_argument("--source", choices=["eia", "iso_ne"], default="iso_ne",
                        help="默认 iso_ne，与当前模型的八区负荷/小时结束口径一致；eia 仅存档")
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
        data_source = ACTUAL_SOURCE

    day = datetime.strptime(args.day, "%Y%m%d").date() if args.day \
        else datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)

    logger.info(f"[{args.source}] 拉取 {day} 的实际负荷...")
    rows = fetch(day)
    logger.info(f"获取到 {len(rows)} 条小时数据（示例: {rows[0] if rows else '无'}）")

    import asyncio
    inserted = asyncio.run(persist(rows, data_source))
    logger.info(f"完成：写入 {inserted} 条（其余为已存在跳过）")


if __name__ == "__main__":
    main()
